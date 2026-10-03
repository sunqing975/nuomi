# 插件概念对齐 Octop（重构实况，v0.7）

> 状态：**已执行（2026-10-02，重构完成）**
>
> - 决策链：Octop 对比 → 概念模糊诊断（22 插件混四类职责）→ 方案 v1（kind 预演）→ 用户拍板"直接重构，不要 kind 区分" → v0.7 落地。
> - 验证：`make check` 全绿（ruff lint + format-check + mypy + 143 tests）；前端 `npm run build` 通过。

## 1. 背景：为什么 "插件" 概念模糊

重构前 `plugins/` 下 22 个 "插件" 混了四种完全不同的东西：

| 实际承担的职责 | 例 |
| --- | --- |
| **给 LLM 的能力**（注册工具） | datetime / fs / shell / web / voice / knowledge / memory / mcp-notes / pyfunc |
| **文档资产**（Agent preset / 技能，无运行时代码） | agent-companion / agent-researcher |
| **运行时钩子**（订阅事件 / 挂中间件 / 模式开关） | mood / robot / team / voice-input / memory-mem0 |
| **内核服务**（基础设施，LLM 根本不该 "选用" 的） | service-agent-loop / service-memory / service-sessions / service-settings / service-system-prompt / service-tools |

同时豆包把 "插件" 定义为产品层"连接器 + 技能组合"，Octop 定义为工程层"分发单元 + kind 分类"。一个词承载三层含义，是模糊的根源。

## 2. 参照系：Octop 插件模型

Octop（octop-harness）的插件模型：

1. **分发单元**：一个文件夹 = 一个插件（`plugin.yaml` + `main.py` 定义 `setup(ctx)`）
2. **能力分类** `kind`：`tool`（`ctx.tool(name, fn, ...)` 注册多个工具）/ `skill`（`ctx.skills(...)` 同步 SKILL.md）/ `hook`（`ctx.middleware(...)`）
3. **界面** `ui/`：可选预构建前端 → Dashboard 渲染卡片
4. **发现** `icon` + `group`（8 分组：lifestyle/news/finance/media/fun/games/tools/ops）
5. **治理** `requires` + `version`：安装时自动装 Python 依赖

**技能包是独立概念**：多个 SKILL.md 聚合为技能包（DB 管理、记 skill_count），可发布进共享池。插件装 "代码"，技能包装 "文档"。

关键洞察：Octop 让 "一个词只承担一件事，其余拆成显式字段/独立目录"。

## 3. 对齐后的 nuomi 概念模型（v0.7 目标态）

### 3.1 术语表

| 术语 | 定义 | 落点 |
| --- | --- | --- |
| **插件** | 分发单元：`plugins/<name>/` 目录 + `plugin.json`，可独立安装 / 启停；入口向 LLM 注册工具 | `plugins/`（9 个） |
| **模块** | 内核组成部分：`backend/app/modules/<name>/`，随系统启动、builtin、不建议停用（原"内置服务" + 原"运行时钩子"） | `backend/app/modules/`（13 个） |
| **技能** | 单个 SKILL.md 文档资产（喂给 LLM 的说明书），独立于插件启停、全量可用 | `skills/<name>/SKILL.md`（10 个） |
| **技能包** | 多个技能的聚合单元（Octop 概念） | **暂不引入**（用户拍板，后续再说） |

### 3.2 对齐取舍（用户拍板）

- **不用 `kind`**：Octop 用 kind 在"一个分发单元"内区分 tool/skill/hook/service；nuomi 选择直接**按职责分目录**（插件 / 模块 / 技能），目录即分类，无 kind 字段。
- **hook 类并入模块**：mood / robot / team / voice-input / memory-mem0 属于内核运行时行为，不是用户可选用能力 → 并入 `modules/`，builtin 判定"modules_dir 下存在即 builtin"。
- **技能独立成区**：10 个 SKILL.md 全部迁到仓库根 `skills/<name>/SKILL.md`；技能区全量注入 system prompt、`skill_doc` 读取不随插件启停过滤。
- **内置服务 = 模块**：`service-*` 移入 `modules/`，术语统一叫"模块"（内核组成部分）。

### 3.3 语义边界

- **插件 ≠ 模块**：插件是可选能力（用户可安装/卸载/停用），模块是内核组成部分（随系统启动）。
- **插件 ≠ 技能**：插件是携带者（代码/目录），技能是内容（SKILL.md）；同名即关联展示（`contributions.skills` = 技能区同名技能）。
- **技能 ≠ 技能包**：技能是单文件文档资产；技能包是聚合单元（未引入）。

## 4. 三区目录现状

| 区 | 数量 | 内容 |
| --- | --- | --- |
| `plugins/` | 9 | datetime fs knowledge mcp-notes memory pyfunc shell voice web |
| `backend/app/modules/` | 13 | service-agent-loop service-memory service-sessions service-settings service-system-prompt service-tools mood robot team voice-input memory-mem0 agent-companion agent-researcher |
| `skills/`（仓库根） | 10 | datetime fs knowledge mcp-notes memory memory-mem0 pyfunc shell voice web |

## 5. 落地记录（含踩坑）

### 5.1 迁移

- `git mv` 13 个目录 → `backend/app/modules/`；10 个 SKILL.md → `skills/<name>/SKILL.md`（git mv 对 untracked 会失败，fallback `mv`）。
- `loader.py` v0.7：`scan_plugins(dir, category=...)` 复用扫插件与模块（`category="plugin"|"module"`）；新增 `scan_skills` / `SkillDescriptor` / `collect_skill_catalog(skills)`。
- `lifecycle.py` v0.7：`build_plugin_list` 的 skills 贡献改为"技能区同名技能关联展示"；`build_skill_tool(skills)` 吃技能列表（技能独立，不随插件启停过滤）。
- `composer.py`：新增 `modules_dir` 与 `_plugin_dir(name)`（先 modules/ 后 plugins/）；`builtin` 判定含"modules_dir 下存在"。
- `main.py`：`build_app` 三区参数（plugins_dir/modules_dir/skills_dir），lifespan 装配 `app.state.plugins`（插件 + 模块）+ `app.state.skills`；skill_catalog 改技能区。
- 打包：`sidecar_main.py` frozen 时设 `SKILLS_DIR`；`nuomi.spec` datas 增 `skills`。
- 测试：13 个测试文件适配三区；`conftest.py` 重写（PLUGINS_DIR/MODULES_DIR/SKILLS_DIR + applied_app 三参数 + state.skills）。

### 5.2 关键踩坑（已验证做不通，勿重试）

- **mypy "Duplicate module named hook"**：`modules/` 下多个 `hook.py` 同名冲突 → 模块入口统一改名 `<目录名转下划线>.py`（如 `service_agent_loop.py` / `memory_mem0.py` / `mood.py`），并同步 `plugin.json` 的 `entry` 字段。
- **`entry` 字段此前从未生效**：Fiber 构造默认 `hook.py`，不读 plugin.json 的 entry；plugins 里 `entry: "tool.py"` 全是摆设（实际一直加载 hook.py）。本次让 composer 读 entry 真正生效（模块唯一入口名依赖它），并把 plugins 的遗留 entry 字段清理掉。
- **lifecycle._apply 的 PluginContext 缺 `config`**：runtime 版 `PluginContext(app)` 未声明 config（fiber 用的是 core/context 版，构造时设置了 config）。删除遗留 entry 后插件 hook.py 首次真正被 lifecycle 执行，暴露此问题 → runtime 版补 `self.config` 声明 + `_apply` 填充。
- **memory-mem0 的 `Mem0Backend.list` 遮蔽内建 list**：迁入 modules 后被 mypy 检查暴露，方法移到类末尾解决（与内置 MemoryBackend 同款问题）。
- **测试污染**：早期一次失败运行（`skills_dir` 参数语义错位）把测试安装的 greet/calc/dup/weather 写进了真实 `plugins/`，已确认删除；若再出现同名目录说明有测试把插件写进了真实目录，属 bug。

### 5.3 验证结果

- `make check` 全绿：ruff lint 通过、format-check 96 文件通过、mypy 48 source files 无问题、pytest **143 passed**。
- 前端：api.ts 补 `category` 字段、插件页页头文案更新为三区说明；`npm run build` 通过。
- 语义回归说明：停用插件（如 memory/datetime toggle）不再影响技能目录与 skill_doc 读取——这是新设计（技能独立），不是回归；查 mood 这类不在技能区的名字返回"未知技能"。

## 6. 对齐边界（不做的事）

| 不做 | 原因 |
| --- | --- |
| 插件市场 / zip 安装器 | 单用户桌面产品，目录即插件；导入 API 已有（install/install-upload），市场形态未来再说 |
| 完整 octop_ui 前端渲染协议 | 需配套 Dashboard 卡片渲染；前端暂无插件卡片协议 |
| 照搬 8 分组 | 按 nuomi 实际精简（模块/插件/技能三区即分组） |
| 多用户 / 权限 / 共享池 / 技能包 | 单用户产品无此需求；技能包暂缓（用户拍板"后续再说"） |

## 7. 一句话总结

> 插件 = 可选能力分发单元（plugins/），模块 = 内核组成部分（modules/），技能 = 独立文档资产（skills/）。
> 不用 kind、不用技能包：**目录即分类**。一个词只干一件事——这就是 Octop 清晰感的来源，也是 nuomi v0.7 的对齐结果。

---

# 附录 A：v0.7.1 格式体系（2026-10-03，用户"都改"）

## A.1 动因

用户："之前的插件的格式是不是都需要变更呢，插件有插件的格式，模块有模块的格式，技能有技能的格式。我们的系统是不是也需要根据概念重新设计架构呢。我觉得octop的领域设计就非常合理。"

## A.2 判断：机制不分，格式分离

- **运行时机制不分**：插件与模块同构（一套 Fiber/apply/ctx 引擎）是优点——不用 kind 区分加载路径，仅目录归属（modules_dir / plugins_dir）+ 清单文件名不同。
- **manifest 格式随概念分离**（对齐 Octop 声明式领域）：
  - 插件 `plugin.json`：能力导向——给 LLM 用（工具/指令/健壮性），无 provides/hooks。
  - 模块 `module.json`：内核导向——运行时服务，`provides[]`（声明的 ctx 服务）+ `hooks[]`（订阅的事件）**声明式元数据**，扫描期即可见（不 import 入口）。
  - 技能 `SKILL.md`：frontmatter 即清单（v0.7 已独立，不变）。

## A.3 模块 provides/hooks 声明（探查真实调用得出）

| 模块 | provides | hooks |
| --- | --- | --- |
| agent-companion | preset:companion | — |
| agent-researcher | preset:researcher | — |
| memory-mem0 | memory | — |
| mood | — | response_done |
| robot | — | plugin_toggled |
| service-agent-loop | agents, agentLoop | settings/changed, plugin/toggled, plugins/loaded, plugin_toggled, llm/switched |
| service-memory | memory | — |
| service-sessions | sessions | — |
| service-settings | settings | — |
| service-system-prompt | systemPrompt | — |
| service-tools | tools | — |
| team | — | plugin_toggled |
| voice-input | voice_input | plugin_toggled |

## A.4 代码改动

- `loader.py`：`MANIFEST_NAMES = {"plugin": "plugin.json", "module": "module.json"}`；`scan_plugins(dir, category)` 按 category 扫对应 manifest，module 分支解析 provides/hooks 到 `PluginDescriptor` 新字段（默认空列表）；错误消息按 manifest 名（插件"plugin.json 解析失败"保持，兼容 test_chat 断言）。
- `lifecycle.py`：`_collect` 服务/事件 = `_dedupe(声明 ∪ 运行时)`（保序去重）。
- `fiber.py`：`_merge_plugin_meta` 先读 module.json、缺则回退 plugin.json（插件仍走 plugin.json）。
- `composer.py`：静态 `_read_manifest(dir)`（module.json 优先）；`_mount` 入口 entry 改从 `_read_manifest` 读；`list_entry` 服务/事件 = `dict.fromkeys(声明 ∪ 运行时)` 保序去重，meta 统一 `_read_manifest`。
- 13 个模块 `plugin.json` → `module.json`（保留 name/version/description/entry + 可选 load/system_instruction/settings/settings_key，补 provides/hooks），删除 plugin.json。
- 注释同步：modules/voice-input、memory-mem0、service-settings、loader/composer/main 的"plugin.json"通用措辞改为清单/manifest（插件专属语境保留）。

## A.5 验证（2026-10-03 全绿）

- pytest **143 passed** 一次通过（贡献视图值不变，测试零适配）。
- `make check` 全绿（ruff lint + format-check + mypy 48 源文件 + 143 tests）。

## A.6 边界

- 插件不引入 provides/hooks：插件的能力面是工具注册（Octop 插件语义），服务/事件是模块职责。
- 技能包（Octop skill 集合概念）仍暂缓（用户拍板"后续再说"）。
