# 糯米 Nuomi · 前端架构设计

> 目标：把"一个 1439 行 styles.css + 组件内散落硬编码"演进为 **Token → 基元 → 组件 → 布局** 四层清晰架构，
> 并为 **多主题** 与 **国际化** 预留机制。本文件与 DESIGN.md（设计方针）配套：DESIGN 管"长什么样"，本文管"怎么组织"。

## 0. 现状审计（2026-10 盘点）

| 项 | 现状 | 问题 |
| --- | --- | --- |
| CSS 组织 | 单文件 `src/styles.css`（1439 行），main.tsx 一次性 import | 组件样式与全局混在一起，改一处影响面不可控 |
| Token | `:root` 定义 dsw 色板 + alias（--bg/--label/--accent/--radius…），`[data-theme="light"]` 覆盖 | 已有良好基础；但 7 处硬编码色值绕过 token（徽标绿/红/黄等） |
| 控件 | 已新增全局基元（input/textarea/select/checkbox 统一） | 基元与旧局部覆写（.setting-field input 等）并存，需要收敛 |
| 类名 | 无统一命名规范，`composer-*` `model-*` `setting-*` `thread-*` 混用 | 易碰撞、难定位归属 |
| 主题 | CSS 变量 + `data-theme` 属性 + localStorage `nuomi-theme`；深色默认、浅色可选 | 无"主题包注册"机制，新增主题需手改 :root |
| 国际化 | 无；~89 处中文文案硬编码在 10 个 tsx/ts 文件（设置 30、插件 15、App 15…） | 无法多语言；文案散落难维护 |
| 内联样式 | 5 处 `style={{}}`（main.tsx 错误边界兜底、PetBuddy SVG props） | 兜底可接受；SVG 色值应入 token |

## 1. 样式四层架构

```
┌────────────────────────────────────────────────────────────┐
│ L4 布局 Layout（全局）   app 栅格 / 侧栏宽度 / 主区 / 滚动条    │
├────────────────────────────────────────────────────────────┤
│ L3 组件 Component（随模块）  每个模块自己的样式，互不可见      │
├────────────────────────────────────────────────────────────┤
│ L2 基元 Primitives（全局）   控件(输入/选择/按钮) / 排版       │
├────────────────────────────────────────────────────────────┤
│ L1 Token（全局）            语义 token + 原始 token + 主题包   │
└────────────────────────────────────────────────────────────┘
```

- **L1 Token**：唯一的"值"来源。组件/基元/布局一律引用 token，禁止新色值。
- **L2 基元**：跨模块复用的控件形态。只允许 selector 基元级（element/伪类/属性选择器）与 `.primitive-*` 类。
- **L3 组件**：每个 `ui-*` 模块一块样式，只作用于该模块类名；不得定义全局性的 element 样式。
- **L4 布局**：应用骨架级样式（侧栏/主区/弹层定位），不属于任何模块。

## 2. 文件组织（目标态）

```
frontend/src/
  styles/                     # L1 + L2 + L4（全局，main.tsx 按序 import）
    tokens.css                # :root 深色默认 + alias（当前 styles.css 1–85 行）
    themes/                   # 主题包（见 §3）
      light.css               # [data-theme="light"] 覆盖
    primitives.css            # 控件基元 + 排版基元
    layout.css                # app 栅格 / 侧栏 / 主区 / 弹层定位 / 滚动条
  modules/
    ui-settings/SettingsModal.tsx
    ui-settings/settings.module.css      # L3：仅 .setting-* 类
    ui-input/InputBar.tsx
    ui-input/input.module.css            # L3：仅 .composer-* .model-* 类
    ...（每个 ui-* 模块一个 module.css）
```

**迁移路径**（不一步到位，见 §6）：当前先拆 `tokens.css` / `primitives.css` / `layout.css` 三个全局文件，L3 组件样式继续留在 `styles.css`（改名 `components.css`）并按模块分区维护；后续需要时再逐模块拆成 CSS Modules。

## 3. 主题机制（扩展设计）

现状已具备骨架：`data-theme` 属性 + 变量覆盖。目标形态：

- **原始 token（不变）**：`--dsw-*` 色板值，各主题包只覆盖原始 token。
- **语义 token（组件只用它）**：`--bg / --surface / --label* / --line* / --accent* / --danger / --radius* / --shadow-pop`。
- **主题包注册**：`styles/themes/<name>.css` 只写 `[data-theme="<name>"] { --dsw-…: …; }`；设置-通用下拉列出可用主题（`themes/` 目录清单或配置数组）。
- **规则**：新增 UI 只消费语义 token；新增主题只覆盖原始 token，二者永不交叉。

## 4. 国际化机制（扩展设计）

目标：文案全部走 `t()`，字典按模块域组织，locale 可切换；**不要求当前一次性迁移**，但新代码必须走字典。

```
frontend/src/i18n/
  index.ts        # t(key, params?) + setLocale + 当前 locale
  zh-CN.ts        # 默认字典（从现有文案抽取）
  en-US.ts        # 未来
```

- **key 规范**：按模块域命名，如 `settings.models.addProvider`、`input.placeholder`、`model.menu.empty`。
- **组件用法**：`t("settings.models.addProvider")`；带参数用 `t("thread.renamed", { name })`。
- **迁移策略**：按模块分批（先从高频模块开始），每次一个 `ui-*` 模块的文案整体抽离；`App.tsx`、`SettingsModal.tsx`（30 处）、`PluginManager.tsx`（15 处）优先。
- **格式**：数字/日期用 `Intl.NumberFormat / DateTimeFormat(locale)`，不手拼字符串。

## 5. 类名命名规范

- 全局层：`app / sidebar / main / modal-mask …`（布局骨架，全局唯一）。
- 基元层：`primitive-input / primitive-btn …`（若需要显式类时）。
- 组件层：`<模块域>-<元素>[--<修饰>]`，模块域即目录名语义，如 `composer-input`、`setting-model-row`、`model-menu-row`；同域样式只出现在该模块的 css 中。
- 状态：`on / active / busy / disabled` 修饰类只与本域类组合使用，不单独全局。
- **禁止**：`name / desc / title` 等无域单词作类名（已有个别残留，迁移时改名）。

## 6. 实施计划

| 级别 | 内容 | 状态 |
| --- | --- | --- |
| P0 | 拆 `tokens.css / primitives.css / layout.css`；硬编码色值入 token（`--ok / --warn`）；类名清扫 | ✅ 完成（2026-10） |
| P1 | L3 组件样式逐模块拆：`modules/<域>/<域>.css`（input/model/plugin/settings，chat 样式在 layout.css 主区段）；mini-btn/icon-btn 提升至 primitives | ✅ 完成 |
| P2 | i18n 基建（`i18n/index.ts` + `zh-CN.ts`，~89 处中文全部 t() 化，硬编码清零）；主题包注册（`styles/themes/light.css` + `themes.ts` 清单驱动设置-通用） | ✅ 完成 |

## 7. 纪律

1. 新样式：能进基元进基元，能进模块进模块，一律不准进"别的模块"。
2. 新色值：禁止。先看 token，缺语义 token 就在 `tokens.css` 加并同步 DESIGN.md。
3. 新文案：禁止硬编码中文，一律走 `i18n`（字典缺失时先加字典）。
4. 每个 UI 改动后重建 dist（桌面版加载 frontend/dist）。
