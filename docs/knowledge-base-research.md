# Octop 知识库实现调研（为 nuomi M6 知识库做准备）

> 2026-10-04。参照代码：`Octop/src/octop/infra/knowledge/`（18 个模块，约 2800 行）+ `Octop/src/octop/infra/db/repos/knowledge.py` + `Octop/src/octop/api/routers/knowledge_bases.py` + 对话注入（chat/turn.py、agents/manager.py、experts.py）。已实现的细节以代码为准。

---

## 1. 一句话架构

**每知识库 = 目录（原始文档文件）+ 主库元数据行 + 一个独立 SQLite sidecar 向量索引**。文档上传后异步索引：**解析 → 定长重叠分块 → 向量化 → 存进该 KB 的 index.sqlite**；对话时由内置工具 `search_knowledge` 按需检索：**query 向量化 → 各 KB 索引余弦相似度 top-k → 跨 KB 合并排序 → 按字符预算截取 → 带引用的上下文注入**。

整个功能是一等公民（工具+中间件+门控+OCR+引用协议），不是外挂 RAG。

---

## 2. 数据模型（SQLite 主库）

### knowledge_bases（每个知识库一行）
| 字段 | 说明 |
|---|---|
| `id` | 对外短 id（`new_short_id`，16 次重试防撞） |
| `owner_user_id` | 属主（权限核心） |
| `name` / `description` | 名称（`UNIQUE(owner_user_id, name)`）/ 描述（≤2000 字，会被截 240 字进工具描述） |
| `default_open` | 创建者的"默认打开"偏好：**该用户发起对话未显式指定 KB 时自动注入** |
| `shared` | 共享位：1 时其他用户只读可见 |
| `icon_name` | 图标名 |
| `embedding_model` / `embedding_dim` | 当前嵌入模型 / 首个文档索引后回填的向量维度 |
| `doc_count` | 文档数（上传时自增，删除时扣减） |
| `max_documents` | 每库文档上限（默认 100，0=不限，上限 10000） |

### knowledge_documents（每文档一行）
`id`(ulid) / `kb_id` / `path`（相对路径，支持文件夹，`normalize_kb_path` 防 `..`）/ `filename` / `is_dir` / `content_type` / `byte_size` / `content_hash` / **`status`（pending → processing → ready / failed）** / `error_message` / `chunk_count` / 时间戳。

### 限制
每用户最多 **20 个知识库**（`MAX_BASES_PER_OWNER`）；单文档大小受全局 `max_upload_mb` 限制；知识库功能整体是一开关（`knowledge_bases_enabled`）。

---

## 3. 入库链路（写路径）

```
上传/创建 → POST /knowledge-bases/{kb_id}/documents
  → KnowledgeService.upload_document（写权限校验 → 类型白名单 → 写文件）
  → 文件落盘：{knowledge_dir}/{kb_id}/docs/{doc_id}{suffix}
  → enqueue_index_document（异步任务，进程内 Semaphore(2) 限并发）
    → process_document（线程池 executor，避免阻塞事件循环）
      → parse_document 提取文本
      → chunk_text 分块（默认 800 字，重叠 120）
      → embed_knowledge_texts 向量化
      → KnowledgeIndex.replace_doc_chunks（原子替换该 doc 全部 chunk）
      → status=ready / failed（失败记 error_message）
```

### 3.1 文档解析（parse.py）——格式覆盖很全
| 类别 | 格式 |
|---|---|
| 纯文本 | md / markdown / txt / rst / yaml / yml / jsonl（UTF-8 优先，**GB18030 回退**——避免中文 GBK 文档乱码） |
| 结构化 | json（美化输出）/ html / htm（内建 HTMLParser 去 script/style/模板，块级标签换行）/ csv / tsv / xlsx / xlsm / xls |
| Office | pdf（pypdf 提取；无文本时走 OCR）/ docx（**含表格、altChunk、文本框**，python-docx XML 层遍历）/ pptx |
| 图片 | png / jpg / jpeg / webp → OCR（可选开关） |

### 3.2 分块（chunk.py）——固定大小字符窗口
`step = size - overlap` 滑窗切分，稳定、无状态。默认 `chunk_size=800 / overlap=120`，可全局配置（100–8000 / 0–size-1）。

### 3.3 向量化（embed.py）——本地 ONNX 优先，远端 API 可选
- 默认 **本地 ONNX**（`knowledge_embedding_backend=onnx`）：从 ONNX 模型目录下载嵌入模型（如 BGE 系），进程内服务嵌入；
- 可选 **远端**（OpenAI 兼容 `/embeddings`，批量 ≤20 保序）；用已配置的 provider + 模型；
- 换模型 = 全局重索引（`reindex_all_documents` 把所有文档置 pending 重新排队）。

### 3.4 索引（index.py）——每 KB 一个 SQLite sidecar
`{knowledge_dir}/{kb_id}/index.sqlite`，单表 `chunks(chunk_id=doc_id:ordinal, doc_id, ordinal, text, embedding BLOB(float32 小端), meta_json)`。
检索 = **进程内全表扫描 + 余弦相似度排序 top-k**（无 ANN/无外部向量库）。文档量小时够用；量大会退化（后续可换 sqlite-vec / hnsw）。

### 3.5 任务与状态机（jobs.py）
- `pending → processing → ready/failed`，失败保留 `error_message`；
- 启动时 `resume_pending_documents`：把卡在 processing 的（上次进程中断）重置为 pending 重新排队；
- 索引并发 `Semaphore(2)`，索引在 executor 线程池跑（CPU/IO 密集不占事件循环）。

---

## 4. 对话检索链路（读路径）

```
Chat turn（body 可带 knowledge_base_ids，[] = 显式退出 default_open）
  → metadata["knowledge_base_ids"] → InboundMessage
  → stamp_turn_knowledge_config：把 kb_ids + catalog + user_is_admin + locale 写入 harness configurable
  → manager 装配：build_knowledge_tools → StructuredTool "search_knowledge"（内置，随 agent 工具集）
  → KnowledgeSearchHintMiddleware（每轮改写工具描述 / 无选中时隐藏工具）
  → LLM 决定调用 search_knowledge(query, k=8)
    → retrieve_context：query 向量化 → 对每个选中 KB 的 index.sqlite 搜 top-k
    → 只保留 status=ready 的文档 → 跨 KB 合并按分数排序
    → 按 context_char_budget（默认 6000 字符）截取 → 每条带引用前缀
    → 追加机器可读引用标记 <!--octop-kb-citations:[...]-->（LLM 通常忽略，前端解析展示）
  → 工具结果（精选段落 + 引用）回给 LLM 组织回答
```

### 4.1 工具设计（tools.py）——要点
- 工具名 `search_knowledge`，参数 `query`（聚焦检索串，非聊天回复）+ `k`（默认 8，1–20）；
- 描述里明确 **"Do not invent citations; only use returned passages"**（禁止编造引用）；
- 每轮由中间件把**选中 KB 的名称/描述**写进工具 description（≤240 字/条），模型知道有哪些库、各自主题；
- **没有任何选中 KB 时，直接从工具列表移除该工具**（比"写了也别调"更强）。

### 4.2 中间件（hint.py）
`KnowledgeSearchHintMiddleware` 挂在 agent 中间件链（`wrap_model_call` / `awrap_model_call`），在模型调用前改写工具描述。这是"每轮注入知识库清单"的关键机制。

### 4.3 引用协议（citations.py）
工具输出正文后追加 HTML 注释标记：`<!--octop-kb-citations:[{"kb_id","kb_name","doc_id","filename","path"},...]-->`；dashboard 前端 `parseKnowledgeCitations.ts` 解析后展示来源（文件名/序号）。同一文档去重为一条引用。

### 4.4 默认打开（default_open.py）
`merge_knowledge_base_ids`：本轮未显式指定时，用**当前用户自己创建的 default_open 库**；专家配置的 `extra_ids` 并入（仍校验可见性）。`[]` 表示显式退出默认注入。

---

## 5. 能力门控与 OCR（可选但设计完整）

### 5.1 门控（gate.py）
知识库是**可选能力**：`knowledge_bases_enabled` 开关 + 前置检查（嵌入模型已选/已下载、本地依赖可用、或远端 provider 就绪）。未启用/前置不满足 → 上传/检索直接报可区分错误（`KNOWLEDGE_FEATURE_DISABLED` / `PREREQUISITES_FAILED`）。启用时先自动装依赖（允许 install）。

### 5.2 OCR（ocr.py）
- 图片（png/jpg/jpeg/webp）+ 扫描 PDF（pymupdf 逐页转图）；
- 后端：本地 **RapidOCR(ONNX)**（默认，依赖按需安装）或远端 **vision 模型**；
- 远端模式有**拒答检测**（模型说"没收到图片"之类的短回复不被当正文索引，而是判空→文档失败，防止毒化知识库）；
- OCR 是独立开关（`knowledge_ocr_enabled`），未启用时上传图片直接拒绝。

---

## 6. API 清单（`/knowledge-bases`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/capability` | 功能开关 + 嵌入/OCR 就绪检查 + 限额 |
| GET | `/embedding-options` / `/ocr-options` | 后端选项（本地 ONNX 目录 + 远端 provider 模型） |
| PUT | `/feature` | 启停知识库 + 嵌入后端/模型 + OCR；变更模型触发全量重索引 |
| POST | `/onnx-download` / `/onnx-activate` / `/onnx-test` | 本地嵌入模型下载/启用/探测 |
| GET/POST | `` / `/{kb_id}` / PATCH / DELETE | 知识库 CRUD（可见/可读/可写/属主四级权限） |
| GET | `/default-open` | 当前用户的默认打开库 |
| GET | `/{kb_id}/documents` | 文档列表（`prefix` 支持文件夹浏览） |
| POST | `/{kb_id}/folders` | 建文件夹（自动补祖先目录） |
| POST | `/{kb_id}/documents/text` | 创建 md/txt 文档（可带草稿内容，随即入队索引） |
| POST | `/{kb_id}/documents` | 上传文档（multipart） |
| GET | `/{kb_id}/documents/{doc_id}/preview` | 预览提取文本 |
| GET | `/{kb_id}/documents/{doc_id}/file` | 下载/内联打开原文件 |
| GET/PUT | `/{kb_id}/documents/{doc_id}/content` | 读写 md/txt 原文（改后自动重索引） |
| POST | `/{kb_id}/documents/{doc_id}/rename` | 重命名（文件夹级联重写子路径） |
| DELETE | `/{kb_id}/documents/{doc_id}` | 删文档（连索引+文件） |
| POST | `/{kb_id}/documents/{doc_id}/reindex` | 单文档重建索引 |
| POST | `/{kb_id}/reindex` | 整库重建索引 |

错误映射到统一错误码（NOT_FOUND / FORBIDDEN / FEATURE_DISABLED / PREREQUISITES_FAILED / DOC_LIMIT / DOC_TOO_LARGE / BASE_LIMIT / UNSUPPORTED_TYPE / NAME_TAKEN / NAME_INVALID），前端可直译。

---

## 7. 对 nuomi 的落地建议（衔接 M6）

nuomi 已用 octop-harness，知识库可以按同一模式做，且比 Octop 更简单（单用户桌面端）：

1. **复用 Octop 的 knowledge 模块思路，但按 nuomi 裁剪**：
   - 保留：parse（格式全覆盖）、chunk（定长重叠）、index（每 KB SQLite sidecar 余弦）、retrieve（合并排序+字符预算）、citations（引用标记）、jobs（状态机+并发信号量）、gate（能力开关）、ocr（图片+扫描 PDF）。
   - 简化：**去掉多用户权限**（owner/shared/members → nuomi 单用户直接全可见）；**嵌入走本地 ONNX 模型**（已拍板，先于远端 API——参考 Octop onnx 目录下载 + 进程内服务，备选 fastembed）；
   - **OCR 进 M6**（已拍板）：RapidOCR(ONNX) 本地后端，图片（png/jpg/jpeg/webp）+ 扫描 PDF（pymupdf 逐页转图），拒答检测可简化为本地模式不需要（本地 OCR 无 LLM 拒答问题）。
2. **嵌入工具到 harness**：nuomi 的 `infra/harness/chat.py` 已能传工具（插件链已验证），知识库工具 `search_knowledge` 作为**内置工具**随 agent 装配即可（对齐 Octop：`HarnessAgentConfig.tools` + 每轮改写描述）。
3. **对话注入**：nuomi 的 chat API 已收 `thread_id`，扩展 body 收 `knowledge_base_ids`（`[]`=退出默认）→ 写入 request configurable → 工具执行时从 langgraph config 读。
4. **存储**：nuomi 单根工作区 `/Users/superman/Nuomi` 下建 `knowledge/<kb_id>/docs/` + `index.sqlite`，元数据进 nuomi.db（对齐现有 agents/plugins 表模式，字段可对齐 Octop 的 knowledge_bases/knowledge_documents 精简版）。
5. **前端**：nuomi 控制台五页卡片体系已成熟，新增"知识库"页（KB 卡片 + 文档列表 + 上传/新建 md + 引用展示）。引用展示参考 Octop dashboard `parseKnowledgeCitations`。
6. **默认打开语义（已拍板：全局默认）**：nuomi 单用户，default_open 简化为**全局默认注入**——用户创建的库可标记"默认打开"，对话未显式指定 `knowledge_base_ids` 时自动注入全部默认库；`[]` 显式退出。不做专家级绑定（Octop 的 agents/experts `knowledge_base_ids` 字段不引入，agents 表暂不对齐该字段）。

### 落地工作量估算（参考）
| 项 | 工作量 | 说明 |
|---|---|---|
| 存储+repo（kb/doc 表 + 文件布局） | M | 对齐现有 nuomi.db 模式 |
| parse+chunk+index+retrieve | M | 可基本复用 Octop 代码逻辑（MIT 参考） |
| 嵌入后端（本地 ONNX） | M | 已拍板本地模型：onnx 目录下载 + 进程内服务（参考 Octop onnx_service） |
| OCR（RapidOCR + 扫描 PDF） | M | 已拍板进 M6；依赖 rapidocr/onnxruntime/pymupdf |
| 工具+中间件+对话注入 | S | 插件链已验证，模式相同 |
| API + 前端页 | M | 卡片体系现成 |
| 引用协议 | S | tool 输出后追加标记 + 前端解析 |

> **已拍板（2026-10-04）**：①嵌入先做**本地模型**（ONNX，远端 API 后置）；②**OCR 进 M6**（图片 + 扫描 PDF）；③绑定粒度 = **全局默认注入**（非专家级）。

---

## 8. 本地模型目录设计（2026-10-04）

工作区 `models/` 现有 `2D/`（桌宠 Live2D 表现层资产）。本地 AI 模型（嵌入/OCR）**不宜混入 `2D/`**，按"表现层资产 vs 智能模型"分层：

```
/Users/superman/Nuomi/models/
├── 2D/                          # 桌宠 Live2D（表现层资产，现状不动）
│   └── <model_id>/              # cat / aidang / hiyori（仓库种子 assets/models/2D 幂等播种）
└── ai/                          # 智能模型（AI 能力资产，M6 知识库起）
    ├── embedding/               # 嵌入模型（ONNX，本地优先路线）
    │   ├── .downloaded/         # 下载完成标记（对齐 Octop：<name.replace('/','--')> 空文件）
    │   └── <model_id>/          # 模型文件（HF 风格 models--<owner>--<name>，或 fastembed cache_dir）
    └── ocr/                     # OCR 模型（预留：RapidOCR 显式 model_path；默认用包内模型）
```

**设计原则**：
1. **语义分层**：`2D/` = 表现层资产（壳消费），`ai/` = 智能模型（后端消费）；`ai/<type>/` 按用途扩展（未来 TTS/ASR 直接加 `models/ai/tts/`、`models/ai/asr/`），不互相污染。
2. **对齐 Octop 机制**：`embedding/.downloaded/<id>` 下载完成标记 + gate 就绪检查（`is_model_downloaded`）；模型 id 用 HF 风格 `owner/name`（如 `BAAI/bge-small-zh-v1.5`），目录名 `models--<owner>--<name>`（对齐 Octop `model_cache_dir`，`/`→`--` 防路径穿越）。
3. **单根一致**：仍在 `NUOMI_HOME` 下，不加新环境变量；后端 `settings.workspace_path / "models" / "ai" / ...` 与现有 `pet/service.py` 的 `MODEL_DIR` 同级但不同语义。
4. **实现路径（已拍板 2026-10-04：完全仿 Octop）**：**下载 = Octop 自研多源竞速**（`onnx_download.py`：httpx 探测 HF 官方 `https://huggingface.co` + 镜像 `https://hf-mirror.com`（可选 COS），超时选胜者；按 allow patterns 拉文件清单：`config.json` / `tokenizer*.json` / `vocab*.txt` / `merges.txt` / `*.onnx` / `onnx/*.onnx` 等，写临时目录→原子移动到 `models/ai/embedding/models--<owner>--<name>/`，完成写 `.downloaded` 标记）；**推理加载 = fastembed**（与 Octop 一致：`TextEmbedding(model_name=model, cache_dir=models/ai/embedding)`，内部 onnxruntime + tokenizer + pooling 全由 fastembed 处理，不手写推理管线）。模型目录/元数据同样对齐 fastembed（`get_onnx_model_meta` → hf_source 确定 HF 仓库 id）。**候选模型**：`BAAI/bge-small-zh-v1.5`（Octop 默认推荐，中文小模型，优先）、`jinaai/jina-embeddings-v2-base-zh`、`intfloat/multilingual-e5-large`。
5. **OCR**：rapidocr 3.x 模型内嵌包内（零下载可用），`models/ai/ocr/` 仅预留显式 `model_path` 场景（换模型时再落文件）。

> **已拍板（2026-10-04）**：目录命名 `models/ai/<type>/`；嵌入实现 = 手写 HF 多源下载 + onnxruntime 直跑（不用 fastembed 加载）。
