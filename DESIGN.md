# 糯米 Nuomi · 设计方针

> **本文件描述控制台的*实际*设计，并规定新增界面必须遵守的规则。**
> 上一版是一份从未实现的理想稿（声称"深色 bluish + DeepSeek 蓝 + `styles.css` 里的 `:root` token"，
> 而实际界面是**浅色 + 琥珀主色**、全仓没有一个 CSS 变量）。描述与实现相反的文档会主动误导人和
> agent —— 本项目已经因此走过弯路。所以现在的规矩是：**文档跟着实现走；要改设计先改实现，再改这里。**

## 1. 设计语言一句话

**浅色中性底 + 单一琥珀强调色**：白色卡片浮在浅灰蓝底色上，文字三层灰阶，强调只用一个琥珀色
（`#f59e0b`，与品牌 logo 圆点一致）。不做第二个强调色。

技术形态：antd 5（`defaultAlgorithm`）+ 组件内联样式。没有 CSS 框架、没有样式方案库。

## 2. Token 体系（唯一定义处：`frontend/src/theme.ts`）

Token **只在 `src/theme.ts` 里定义一次**（带 TypeScript 约束，拼错即编译失败），
应用启动时由 `applyCssTokens()` 写成 `document.documentElement` 上的 CSS 变量，
组件统一写 `var(--x)`。

> 为什么不放在 CSS 里：两处定义必然漂移（上一版文档就栽在这上面）。
> 只有一个来源，漂移在结构上不可能发生，也就不需要"两份值比对"的测试。
> antd 组件的 token 无法读 `var()`（它的算法要拿色值参与计算），所以 `theme.ts` 额外导出
> `APP_TOKENS` 字面量供 `main.tsx` 的 `ConfigProvider` 使用 —— 它的值也来自同一处。

| 语义 | 变量 | 值（浅色） | 用途 |
| --- | --- | --- | --- |
| 页面底 | `--bg` | `#f7f8fa` | Layout 背景 |
| 卡片面 | `--surface` | `#ffffff` | Card / Modal / 输入框 |
| 更深一层 | `--surface-2` | `#fafafa` | 折叠块、次级底 |
| 主文 | `--label-1` | `#1f2937` | 正文、标题 |
| 次文 | `--label-2` | `#6b7280` | 说明、次要信息 |
| 弱文 | `--label-3` | `#9ca3af` | 占位符、12px 辅助字 |
| 弱文（备用） | `--label-4` | `#8c8c8c` | 已有的另一档灰（待合并到 label-3） |
| 行分隔 | `--line-1` | `#f0f0f0` | 列表内分隔 |
| 控件边框 | `--line-2` | `#e5e7eb` | 卡片/头部边框 |
| 重边框 | `--line-3` | `#d0d5dd` | 工具卡片描边 |
| 强调 | `--accent` | `#f59e0b` | 主色、品牌点、选中态 |
| 强调柔光 | `--accent-soft` | `rgba(245,158,11,.18)` | 选中底/光环 |
| 强调文字 | `--accent-text` | `#874d00` | 琥珀底上的深字 |
| 链接/信息 | `--link` | `#1677ff` | 链接、信息态 |
| 成功 / 警告 / 危险 | `--ok` `--warn` `--danger` | `#52c41a` `#faad14` `#ef4444` | 仅状态语义 |
| 警告底/边 | `--warn-bg` / `--warn-line` | `#fffbe6` / `#ffe58f` | 提示条 |
| 圆角 | `--radius-sm/md/lg` | `6 / 8 / 12 px` | 与 antd `borderRadius: 8` 对齐 |
| 阴影 | `--shadow-pop` | 见文件 | **仅弹层**（Modal/Menu/Dropdown） |

**深色主题**：`THEME_OVERRIDES.dark` 已备好覆盖层（`CORE_KEYS` 必须有值，测试会断言），
调用 `applyCssTokens('dark')` 即整体切换。**但切换入口尚未接入** —— 接入时还要同时把
`main.tsx` 的 antd `algorithm` 换成 `theme.darkAlgorithm`，否则 antd 组件仍是浅色。

## 3. 控件与布局

| 项 | 现状 |
| --- | --- |
| 侧边栏 | 200px，浅色，`borderRight: 1px solid var(--line-2)` |
| 顶栏 | 60px，`var(--surface)` 底 + 下边框；右侧后端连通性 Tag |
| 卡片网格 | `Row/Col` + `List`，同行等高靠 `.nuomi-grid`（见 `index.css`） |
| 弹窗 | antd `Modal`，破坏性操作一律 `Popconfirm` |
| 圆角 | 统一取自 antd `borderRadius: 8`（等于 `--radius-md`） |
| 按钮 | 一律 antd `Button`（有 `.mini-btn` 等尺寸约定），**禁止裸 `<button>`** |
| 错误兜底 | `src/ErrorBoundary.tsx` 套在 `App` 外层（渲染期抛错不至整站白屏） |

## 4. 规则（新增界面必须遵守）

1. **不许写新色值。** 需要新颜色 → 先在 `theme.ts` 加 token 并说明理由，再在组件里 `var()`。
   （现状有例外，见 §5 欠账。）
2. **不许新增 CSS 文件。** 全局样式只放 `src/index.css`（它只承载跨页面的结构性规则，如网格等高、
   Markdown 排版）。组件样式用内联 `style` 或 antd 属性。
3. **状态与空态分开。** 请求失败必须显示错误与重试，**不能把错误渲染成"暂无数据"**
   （多处历史实现犯过这个：Market / Plugins / AvatarModels 曾把加载失败显示成"市场暂无插件"）。
4. **加载/空/错误三态齐全**（参考 `pages/Memory.tsx` 的 `error` + `Alert` 写法）。
5. **深色兼容**：新样式不得假设底色是浅色（用 token 即自动跟随）。
6. **无障碍底线**：可点击的非按钮元素要有 `role`/`tabIndex`，图标按钮要有 `aria-label`
   （现状欠账见 §5，但新增的必须做）。

## 5. 迁移欠账（如实记录，不用"已对齐"糊过去）

截至 2026-10-06 的实测：

| 项 | 数量 | 说明 |
| --- | --- | --- |
| `var(--x)` 引用 | 58 处 | 已迁移的中性色/主色 |
| tsx 内剩余裸 hex | 60 处 | 其中 4 处是 antd `color="…"` prop；其余是**装饰性标签色板**（`#8b5cf6` `#ec4899` `#3b82f6` `#14b8a6` `#f97316` `#722ed1` `#eb2f96`）与少量语义色 |
| 内联 `style={{` | 278 处 | 未做系统化抽取；多数是布局（`margin`/`gap`/`flex`）而非颜色，风险低 |
| **i18n** | 不存在 | 文案全为硬编码中文，**没有** `i18n/` 基建（曾有一份已删文档声称「i18n 基建 ✅ 完成、~89 处全部 t() 化」——那是**从未存在**的东西）。单用户中文形态下暂不做；要做则先立字典再逐页迁移 |

处理顺序建议：先把装饰标签色板收成一个 `utils/palette.ts`（三份 `AVATAR_COLORS` 重复定义已经存在），
再逐页收内联样式。**不要为了"清零"而做大范围无验证的重写** —— 内联布局改动容易破版。

## 6. 变更流程

1. 改设计 → 先改 `theme.ts`（token）→ 再改组件。
2. 跑 `cd frontend && npx tsc --noEmit && npm run test:run && npm run build`
   （token 结构测试在 `src/theme.test.ts`）。
3. 前端改动后必须 `npm run build`：壳的控制面板加载的是后端挂载的 `frontend/dist`
   （只改源码不 build → "web 对、桌面壳不对"）。`make start` 已依赖 build。
4. 深浅两主题都要过一遍（深色入口接入后）。
5. 本文件与实现不一致时，**以实现为准并立即更新本文件**。
