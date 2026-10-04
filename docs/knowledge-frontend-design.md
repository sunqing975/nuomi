# 知识库前端设计（nuomi 控制台）

> 2026-10-04。参照：nuomi 前端（React18 + antd5 + react-router hash 路由 + `api.ts` 统一出口）与 Octop dashboard `pages/KnowledgeBases`（3458 行单页）裁剪。后端 API 契约以本设计为准（路由实现见下一块）。

---

## 1. 设计目标

- 单用户桌面控制台，**一个页面管全部**（对齐现有八页卡片体系，不加二级路由）。
- 覆盖三件事：**能力管理**（本地嵌入模型下载/切换/删除 + 启用开关）、**知识库管理**（建/改/删 + 全局默认开关）、**文档管理**（上传/新建/预览/编辑/重索引/删除 + 索引状态）。
- 状态可见：文档索引状态（pending/processing/ready/failed）实时可刷新；模型下载状态明确。
- 与对话注入衔接：Chat 页解析 `<!--octop-kb-citations-->` 展示来源（本轮只设计，实现随检索工具块）。

## 2. 页面入口

`App.tsx` NAV 增加一项（位于「存储」之前）：

| key | 图标 | label | title |
|---|---|---|---|
| `knowledge` | `<BookOutlined />` | 知识库 | 知识库 / 文档检索 |

hash 路由 `#knowledge` 直达（复用现有 `NAV` 机制，无需改 App 其他逻辑）。

## 3. 页面结构（单页三区块，自上而下）

```
┌──────────────────────────────────────────────────────────────┐
│ ① 能力状态条（KnowledgeModelsBar）                             │
│   [嵌入服务 ● 就绪/未启用] [模型 bge-small-zh-v1.5 · 512 维]     │
│   [管理模型…] [新建知识库 +]                                    │
├──────────────────────────────────────────────────────────────┤
│ ② 知识库卡片区（KnowledgeBaseGrid）                            │
│   ┌──────────┐ ┌──────────┐                                    │
│   │ 名称      │ │ 名称      │  卡片：名称/描述/文档数/索引维度    │
│   │ 默认打开 ●│ │ 默认打开 ○│  右下：默认打开 Switch · 操作菜单    │
│   └──────────┘ └──────────┘   （进入详情/重命名/删除）           │
├──────────────────────────────────────────────────────────────┤
│ ③ 文档详情区（选中卡片后展示，未选中显示空态引导）               │
│   顶栏：返回 · 库名 · 文档数 · 索引状态汇总 · [上传] [新建文本]    │
│   列表：文件名 | 类型 | 大小 | 分块数 | 状态 Tag | 操作            │
│   操作：预览 / 编辑(md·txt) / 下载 / 重索引 / 重命名 / 删除       │
└──────────────────────────────────────────────────────────────┘
```

### 3.1 ① 能力状态条

- 来自 `GET /knowledge/capability`（后端返回：`enabled / model / ready / downloaded / cache_dir / local_models / presets / deps_available`）。
- 三种态：`依赖缺失`（红，引导安装）→ `模型未下载`（橙，引导下载）→ `就绪`（绿，显示模型与维度）。
- 右侧「管理模型…」打开模型管理 Modal（见 §5.1）；「新建知识库」打开建库 Modal。

### 3.2 ② 知识库卡片区

- `GET /knowledge-bases` 返回数组；卡片网格（antd `Card` + `Row/Col`，复用 PetModels/Skills 的卡片观感）。
- 卡片字段：名称、描述（截断）、`doc_count`、`embedding_dim`、`default_open`。
- **默认打开** = 拍板的"全局默认注入"：Switch 直改 `PATCH /knowledge-bases/{id}`（`default_open`），文案"默认打开：对话时自动注入"。
- 操作菜单（Dropdown）：进入详情 / 重命名 / 删除（Popconfirm）。
- 空态：`Empty` + "新建你的第一个知识库"。

### 3.3 ③ 文档详情区

- 选中 KB 后加载 `GET /knowledge-bases/{id}/documents`（支持 `prefix` 文件夹浏览）。
- 列表行（antd `Table` 或 `List`，小屏用 List）：文件名（文件夹带目录图标）、类型 Tag、大小（字节→KB/MB 格式化）、`chunk_count`、状态 Tag（`ready` 绿 / `processing` 蓝 / `pending` 灰 / `failed` 红 + tooltip 错误信息）、更新时间。
- 顶栏操作：
  - **上传**：`Upload.Dragger`（Modal 内多选/拖拽，前端校验扩展名白名单与 100MB 上限，后端错误直接 message）。
  - **新建文本**：`TextDocEditorModal`（对齐 Octop）：选 md/txt + 文件名 + 内容草稿 → `POST /knowledge-bases/{id}/documents/text`。
  - **刷新**：重拉文档列表与状态（上传后自动轮询 3 次/2s，仍有 processing 时提示稍后刷新）。
- 行操作：预览（Modal 显示提取文本，`GET /preview`）/ 编辑（仅 md·txt，`GET`+`PUT /content`，保存后状态回 pending 并自动重索引）/ 下载（`GET /file` 新窗口打开）/ 重索引（`POST /reindex`）/ 重命名（Modal，`POST /rename`）/ 删除（Popconfirm，`DELETE`）。
- 空态：`Empty` "还没有文档，上传文件或新建文本"。

## 4. 组件划分（新建文件）

| 文件 | 内容 | 规模预估 |
|---|---|---|
| `src/pages/Knowledge.tsx` | 主页面：三区块组装 + 状态管理（kbList/docList/modelState） | ~300 行 |
| `src/pages/KnowledgeModelsModal.tsx` | 模型管理 Modal（§5.1） | ~150 行 |
| `src/pages/KnowledgeDocEditorModal.tsx` | 新建/编辑 md·txt（对齐 Octop TextDocumentEditorModal，简化） | ~120 行 |
| `src/pages/KnowledgeUploadModal.tsx` | 拖拽/多选上传 + 类型校验 | ~90 行 |

其余（KB 卡片、文档列表、状态 Tag）留在主页面组件内（不拆过度，对齐现有页面单文件习惯；若超 600 行再拆 `KnowledgeDocs.tsx`）。

## 5. 关键交互

### 5.1 模型管理 Modal（对齐 Octop onnx 面板，简化）

- 列表：`GET /knowledge/capability` 的 `presets` + `local_models`（fastembed 支持目录，标注推荐）。
- 行操作：未下载 → `[下载]`（`POST /knowledge/onnx-download`，后端任务式下载，前端轮询 `GET /knowledge/capability` 直到 `downloaded=true`，显示"下载中…"禁用按钮）；已下载 → `[已就绪]` + `[删除]`（Popconfirm，`DELETE /knowledge/onnx-model`）。
- 切换：`PUT /knowledge/feature` 选模型 + `enabled=true`；若与当前不同，后端触发全量重索引，前端 message 提示"模型已切换，正在重建索引"。
- 就绪检查失败（依赖缺失）：显示安装指引（uv 命令）与「重试」。

### 5.2 全局默认注入

- KB 卡片 Switch 控制 `default_open`；对话未显式指定 `knowledge_base_ids` 时自动注入所有 default_open 库（后端逻辑，前端只展示开关）。
- 说明文案放卡片 Tooltip："打开后，新对话会自动检索该知识库"。

### 5.3 引用展示（Chat 页，随检索工具块实现）

- 对齐 Octop `utils/parseKnowledgeCitations.ts`：解析消息里 `<!--octop-kb-citations:[...]-->` 标记，在 Chat 消息下方渲染来源条（库名/文件名/序号，点击打开文档详情）。
- 本轮只在设计文档约定协议，不动 Chat.tsx。

## 6. API 契约（前端视角；路由后端实现随后）

| 方法 | 路径 | 前端用途 |
|---|---|---|
| GET | `/api/knowledge/capability` | 状态条 + 模型管理 |
| PUT | `/api/knowledge/feature` | 启停/模型切换（触发 reindex_all） |
| POST | `/api/knowledge/onnx-download` | 下载模型（body: model） |
| DELETE | `/api/knowledge/onnx-model?model=` | 删除模型 |
| GET/POST | `/api/knowledge-bases` | 列表 / 建库 |
| GET/PATCH/DELETE | `/api/knowledge-bases/{id}` | 详情 / 改名·默认打开·上限 / 删除 |
| GET | `/api/knowledge-bases/{id}/documents?prefix=` | 文档列表（文件夹浏览） |
| POST | `/api/knowledge-bases/{id}/folders` | 建文件夹 |
| POST | `/api/knowledge-bases/{id}/documents` | 上传（FormData `file`） |
| POST | `/api/knowledge-bases/{id}/documents/text` | 新建 md/txt |
| GET | `/api/knowledge-bases/{id}/documents/{doc}/preview` | 预览提取文本 |
| GET | `/api/knowledge-bases/{id}/documents/{doc}/file` | 下载原文件 |
| GET/PUT | `/api/knowledge-bases/{id}/documents/{doc}/content` | 读/写 md·txt |
| POST | `/api/knowledge-bases/{id}/documents/{doc}/rename` | 重命名 |
| POST | `/api/knowledge-bases/{id}/documents/{doc}/reindex` | 单文档重索引 |
| DELETE | `/api/knowledge-bases/{id}/documents/{doc}` | 删除文档 |

## 7. 实现顺序

1. `App.tsx` 加导航项 + 空 `Knowledge.tsx` 骨架（占位 + 状态条接入 `/knowledge/capability`）。
2. 模型管理 Modal + 下载/切换/删除。
3. KB 卡片区（列表/建库/重命名/删除/默认打开）。
4. 文档详情区（列表/上传/新建/预览/编辑/重索引/删除/刷新）。
5. `tsc && vite build` 验证；后端路由实现后联调（重启壳整体验证）。

> 依赖后端未实现项（先 Mock 或等路由块）：`/knowledge/*` 与 `/knowledge-bases/*` 全部路由。建议前后端同轮实现，前端先按契约写好，后端路由落地后直接联调。
