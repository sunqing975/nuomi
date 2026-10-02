# Nuomi 记忆 v2 · Provider 化设计（对齐 Hermes）

> 目标：记忆对齐 Hermes 设计（纯文件核心 + 冻结快照注入 + 可切换 provider 插件），
> 保持 Nuomi "一切皆插件" 内核不变——**换记忆方案 = 改一行 profile，不动引擎与工具**。
> 首个外部 provider：Mem0。
> 状态：**P0 + P1 已实施（2026-10-02，后端 143 项测试全绿）**。
> 适配 2026-10-02 桌面化数据架构：单用户（契约无 user 参数）、MemoryStore 已 SQLite 化
> （facts 表，接口不变）；本方案随之简化。

## 1. 原则

1. **记忆是服务，不是文件格式**：上层（工具/注入/引擎）只依赖 `MemoryBackend` 契约，不感知 SQLite/Mem0/JSON。
2. **内置默认 = 纯文件**（对齐 Hermes）：零依赖、容量有界；语义检索一律外置。
3. **外部 provider = 插件**：一个 provider 一个插件目录，profile 一行启用/停用；实现与主仓库解耦。
4. **冻结快照注入**（对齐 Hermes）：会话开始时取一次记忆快照注入 system prompt，会话内不变（保 prefix cache、省每轮检索）；写操作即时落盘、下个会话反映。
5. **渐进迁移**：现有 facts 数据零迁移（同库 SQLite 表），P0 即可上线。

## 2. 现状与差距（改造前）

| 维度 | Nuomi 现状 | Hermes | 差距 |
|---|---|---|---|
| 存储 | MemoryStore SQLite facts 表（CJK 检索/300 条淘汰） | ~/.hermes/memories/ 纯文件双档（MEMORY.md 2200 字符 + USER.md 1375 字符） | 注入无容量预算概念；无双档语义 |
| 注入 | 每轮按用户消息检索注入 | 会话开始冻结快照（含容量 header） | 每轮注入 token 成本高、prefix cache 失效 |
| 工具 | memory_write / memory_read | memory 工具 add / replace / remove（无 read，自动注入） | 缺 replace/remove；语义不清 |
| 后端 | service-memory 固定建 MemoryStore，全局 get_store() 单例 | memory.provider 配置 + 8 个外部 provider 并存 | **provider 不可切换（本次核心）** |
| 会话检索 | 无 | session_search（SQLite FTS5） | 不在本方案范围（另立） |

## 3. 目标架构（已落地）

```
┌─────────────────────────────────────────────────────────┐
│ 注入层  NuomiMiddleware（awrap_model_call）               │
│  会话开始：memory.snapshot() → 冻结快照 → system prompt    │
│  （按 thread 缓存；容量 header：MEMORY 62% · 1,240/2,000） │
├─────────────────────────────────────────────────────────┤
│ 工具层  plugins/memory（memory_write/read/replace/remove）│
│  经 get_backend() 单例读点访问，不感知 provider            │
├─────────────────────────────────────────────────────────┤
│ 契约层  MemoryBackend（Protocol，app/storage/memory.py）  │
│  list / add / replace / remove / search / snapshot       │
├──────────────┬──────────────────────┬────────────────────┤
│ 内置 file    │ memory-mem0 插件 ✅   │ 未来 provider 槽位   │
│ service-     │ (mem0ai SDK,         │ Honcho / Holographic│
│ memory ✅    │ OpenMemory/云/本地)    │ / OpenViking …      │
│ SQLite facts │ 语义提取+向量检索      │ 只写 MemoryBackend  │
└──────────────┴──────────────────────┴────────────────────┘
切换：profile 改两行（enable memory-mem0 + disable service-memory）
```
```

## 4. 契约层：MemoryBackend（已落地）

```python
# backend/app/storage/memory.py（MemoryStore 旁新增契约层，旧类保留）
@dataclass
class MemoryEntry:
    id: str
    content: str
    category: str          # preference/user → USER 档；其余 → MEMORY 档（Hermes 双档）
    created_at: float
    updated_at: float

class MemoryBackend(Protocol):
    def list(self) -> list[MemoryEntry]: ...
    def add(self, content: str, category: str = "fact") -> MemoryEntry | None: ...
    def replace(self, old_text: str, content: str) -> tuple[int, str]: ...  # (1成功/0未找到/-1多条, msg)
    def remove(self, old_text: str) -> tuple[int, str]: ...
    def search(self, query: str, top_k: int = 3) -> list[MemoryEntry]: ...
    def snapshot(self) -> dict: ...  # {sections: [{name, entries, total_chars, char_limit}]}
```

- `FileMemoryBackend`：包装现有 MemoryStore（**SQLite facts 表，数据零迁移**），category 映射双档语义，
  快照按 char_limit（MEMORY 2000 / USER 1000，可配）按"常用/最新"截取。
- `replace/remove` 用**唯一子串**定位（Hermes 语义；0 条→未找到、多条→要求更精确片段）。
- 单例读点：`set_backend(backend)` / `get_backend()`（未 set 时回退包装 get_store()）。
  停用 provider 插件时 `set_backend(None)` 自动回退内置。

## 5. 注入层：冻结快照（已落地，替换每轮检索注入）

- `NuomiMiddleware`：每个 thread 首次构造模型输入时调 `memory.snapshot()` 生成快照文本并缓存
  （`_snapshots: dict[thread_key, str]`），会话内复用；middleware 重建/换 thread 失效。
- 快照格式（对齐 Hermes）：

```
【记忆快照】
MEMORY（我的笔记）[62% — 1,240/2,000 字符]
§ 用户的项目是 Rust web 服务…
§ 本机 macOS + Docker…
USER（用户画像）[35% — 480/1,000 字符]
§ 用户偏好简洁回复…
```
- 注入职责从 service-system-prompt 移交 middleware（该服务不再 inject memory）；
  provider 失败降级为"无快照"（不阻断对话）。
- 语义分层：停用 **memory 能力插件** → 工具不注册；停用 **记忆服务**（service-memory / memory-mem0）→ 无快照注入。

## 6. 工具层：memory 工具对齐 Hermes（已落地）

| 工具 | Hermes 对应 | 说明 |
|---|---|---|
| memory_write | add | 写一条，自动去重；category 可选 fact/preference/event（preference → USER 档） |
| memory_read | search | 按需补充查询（快照外的细节），保留原语义 |
| memory_replace | replace | old_text 唯一子串 → 替换（新工具） |
| memory_remove | remove | old_text 唯一子串 → 删除（新工具） |

- 访问方式：`app.storage.memory.get_backend()`（单例读点）；service-memory / memory-mem0 启动时 `set_backend(impl)`。
- 容量：存储层 300 条淘汰（沿用）；快照层 char 预算截取；工具返回清晰错误（未找到/多条）。

## 7. provider 插件：memory-mem0（已落地）

**目录形态**（与现有插件同构，已建）：

```
plugins/memory-mem0/
├── plugin.json      # settings schema（mode: openmemory/cloud/local, api_key, base_url, llm 配置）
├── hook.py          # Mem0Backend(MemoryBackend) + apply：依赖探测 → set_backend → provide("memory")
└── SKILL.md         # 自述"语义记忆：模糊回想用我"
```

**实现要点**：
- `mem0ai` **懒依赖**：apply 时探测 import，未安装 → 插件 FAILED（UI 可见提示：
  `cd backend && uv pip install mem0ai`）；运行期首次调用才连接 Mem0 服务。
- `Mem0Backend`：add/search/replace/remove/list/snapshot 全部映射 mem0 API
  （replace/remove 用"语义检索 + 子串过滤"保证契约的唯一子串语义）。
- 三种模式：`openmemory`（默认，本地自托管，数据不出本机）/ `cloud`（Mem0 云，需 api_key）/
  `local`（全本地向量库 + LLM 提取）。
- 配置合并：profile config ← settings 插件设置（`memory-mem0` 键，设置页可配）。

**切换方式（profile 两行）**：

```yaml
# NUOMI_HOME/nuomi.json profile patch
- enable: memory-mem0
- disable: service-memory     # 停用内置 file provider
```

**依赖与配置**：mem0ai 可选依赖（`uv pip install mem0ai`）；LLM 提取复用 OpenAI 兼容端点
（默认 DeepSeek；api_key 继承 DEEPSEEK_API_KEY / LLM_API_KEY / MEM0_API_KEY 环境变量）。

**注意（诚实取舍）**：mem0 是"对话级自动提取+语义检索"，与内置"整句写入+词法检索"是不同心智——
切换后写入口径、快照条目格式需适配；云版数据出本机，需用户知情（默认本地模式）。

## 8. 迁移与兼容

- **数据零迁移**：内置 provider 直接读现有 SQLite facts 表（同库 nuomi.db，无需拷贝）。
- `MemoryStore` 类保留（FileMemoryBackend 内部使用）；`get_store/set_store` 保留兼容读点，
  新代码统一 `get_backend/set_backend`。
- `app.state.memory` 兼容读点：service-memory 仍设 MemoryStore；memory-mem0 设为 None，
  health 改走 `get_backend().list()`（通用计数）。
- 测试：`test_memory.py` 保持绿；新增 `test_backend_contract.py`（file 契约 + 双档快照 +
  渲染格式 + Mem0Backend fake 映射 + 依赖缺失报错）；`test_context.py` 新增冻结快照端到端
  （同 thread 不变 / 新 thread 反映新写入）。
- 单用户形态（2026-10-02 桌面化）：契约无 `user` 参数，多用户相关段落已删。

## 9. 实施状态

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 契约+冻结快照 | MemoryBackend + FileMemoryBackend + 注入改冻结快照（含容量 header）+ 工具 replace/remove | ✅ 已落地（143 项测试全绿） |
| P1 Mem0 插件 | plugins/memory-mem0（懒依赖 + settings schema + 契约测试 fake mem0 + profile 切换） | ✅ 已落地（真实 mem0 服务待用户配置后端到端验证） |
| P2 打磨 | 设置页 provider 选择 UI、容量满合并提示、真实 Mem0 端到端演示 | ⏳ 待办 |

## 10. 风险与取舍

- **Mem0 数据出本机**（云版）→ 设置页明示，默认本地模式。
- **mem0 提取依赖 LLM** → 冷启动慢、有 API 成本；本地 file 模式零成本兜底。
- **双 provider 并存的服务名冲突** → Cordis scope 已跟踪 owner；profile 互斥启用，测试覆盖"停 file 启 mem0 / 反向"。
- **冻结快照与"每轮检索"的行为差异** → 会话内新写入不即时出现在 prompt（Hermes 同款，工具返回即所见）；文档/UI 说明。
