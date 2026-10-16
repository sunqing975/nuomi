/**
 * 糯米控制台 · 设计 token（**唯一定义处**）
 *
 * ⚠️ 背景：`DESIGN.md` 曾描述一套「深色 bluish + DeepSeek 蓝 + styles.css 里的 :root token」
 * 的设计 —— 但那套东西**从未实现**：实际界面是**浅色 + 琥珀主色**，且全仓没有一个 CSS 变量。
 * 描述与实现相反的文档比没有文档更糟：它会主动误导人和 agent（本项目前几轮就被它误导过）。
 *
 * 现在改为：token 只在**这里**定义（带类型，能约束拼写），启动时由 `applyCssTokens()`
 * 写进 `document.documentElement` 的 CSS 变量；组件里统一 `var(--x)`。
 * 只有一个来源 → 结构上不可能漂移，也就不需要"两份值比对"的测试。
 *
 * 为什么保留浅色而不是按旧文档改成深色：那是用户可见的视觉改版，不属于"还技术债"。
 * 深色作为 `THEME_TOKENS.dark` 的覆盖层已备好（切换入口尚未接入，见 DESIGN.md 待办）。
 */

// darkAlgorithm 要参与 antd 的色值推导，只能在这里引真实对象（不能传字符串名）
import { theme as antdTheme } from 'antd';

/** 主题变量名 → 值。键名即 CSS 变量名（不经额外映射，避免又一处漂移点）。 */
export interface ThemeTokens {
  'bg': string;
  'surface': string;
  'surface-2': string;
  'label-1': string;
  'label-2': string;
  'label-3': string;
  'label-4': string;
  'line-1': string;
  'line-2': string;
  'line-3': string;
  'accent': string;
  'accent-soft': string;
  'accent-text': string;
  /**
   * 交互主色（按钮/链接/聚焦）：琥珀深档，白字对比度达标。
   * 与 `accent`（品牌亮档，logo/选中态/高亮点缀）同系：亮档做点缀、深档做交互。
   */
  'primary': string;
  'link': string;
  'ok': string;
  'warn': string;
  'danger': string;
  'warn-bg': string;
  'warn-line': string;
  /** 工具「结果」卡片底色/描边（浅色绿系；深色必须覆盖，否则深底顶着荧光绿块） */
  'ok-bg': string;
  'ok-line': string;
  /** 工具「调用」卡片底色（浅色蓝系）。与 ok-bg 成对：深色漏覆盖同样是荧光块压深底 */
  'info-soft': string;
  /** 知识库选择器「选中行」底色（浅粉，跟 #eb2f96 勾选符同色系，别拿它当通用高亮） */
  'pink-soft': string;
  'radius-sm': string;
  'radius-md': string;
  'radius-lg': string;
  'shadow-pop': string;
}

/** 深色主题需要覆盖的子集（其余沿用浅色值）。`CORE_KEYS` 必须是它的子集。 */
export type ThemeOverrides = Partial<ThemeTokens>;

export const THEME_TOKENS: ThemeTokens = {
  bg: '#f7f8fa',
  surface: '#ffffff',
  'surface-2': '#fafafa',
  'label-1': '#1f2937',
  'label-2': '#6b7280',
  'label-3': '#9ca3af',
  'label-4': '#8c8c8c',
  'line-1': '#f0f0f0',
  'line-2': '#e5e7eb',
  'line-3': '#d0d5dd',
  accent: '#f59e0b',
  'accent-soft': 'rgba(245, 158, 11, 0.18)',
  'accent-text': '#874d00',
  primary: '#d97706',
  link: '#d97706',
  ok: '#52c41a',
  warn: '#faad14',
  danger: '#ef4444',
  'warn-bg': '#fffbe6',
  'warn-line': '#ffe58f',
  'ok-bg': '#f6ffed',
  'ok-line': '#d9f7be',
  'info-soft': '#f0f7ff',
  'pink-soft': '#fff0f6',
  'radius-sm': '6px',
  'radius-md': '8px',
  'radius-lg': '12px',
  'shadow-pop': '0 6px 16px rgba(0, 0, 0, 0.08), 0 3px 6px -4px rgba(0, 0, 0, 0.12)',
};

export const THEME_OVERRIDES: Record<'light' | 'dark', ThemeOverrides> = {
  light: {},
  dark: {
    bg: '#0f1115',
    surface: '#171a21',
    'surface-2': '#1d212a',
    'label-1': '#e5e7eb',
    'label-2': '#9ca3af',
    'label-3': '#6b7280',
    // label-4（次级灰字，Composer/MessageBubble 在用）深色下必须比 label-3 亮一档，
    // 否则浅色的 #8c8c8c 压在 #0f1115 上对比度不够，小字直接糊掉。
    'label-4': '#98a1b0',
    'line-1': '#262b36',
    'line-2': '#2f3542',
    'line-3': '#3a4150',
    'accent-text': '#ffd591',
    'warn-bg': '#2b2411',
    'warn-line': '#5c4a12',
    // 工具结果卡：深色必须是「暗绿底 + 暗描边」。不覆盖的话深底上顶着一块荧光绿。
    'ok-bg': '#162318',
    'ok-line': '#2b4a30',
    // 调用卡/选择行同理：暗蓝、暗粉，压到 #0f1115 / #171a21 上不刺眼
    'info-soft': '#16233a',
    'pink-soft': '#3a1a2b',
    'shadow-pop': '0 6px 16px rgba(0, 0, 0, 0.5), 0 3px 6px -4px rgba(0, 0, 0, 0.4)',
  },
};

/** 切主题时必须被覆盖的键（漏掉会出现"深色下露白"）。深色覆盖层必须包含它们。 */
export const CORE_KEYS: (keyof ThemeTokens)[] = [
  'bg',
  'surface',
  'surface-2',
  'label-1',
  'label-2',
  'line-1',
  'line-2',
];

export type ThemeMode = 'light' | 'dark';

/** 合并后的 token（浅色基底 + 指定模式覆盖）。 */
export function resolveTokens(mode: ThemeMode = 'light'): ThemeTokens {
  return { ...THEME_TOKENS, ...THEME_OVERRIDES[mode] };
}

/**
 * 把 token 写成 CSS 变量。
 *
 * 传入 root 便于测试（不必真的碰 DOM）；默认 `document.documentElement`。
 * 主题切换只需再调一次（覆盖同名变量即可）。
 */
export function applyCssTokens(mode: ThemeMode = 'light', root?: HTMLElement): void {
  const target = root ?? (typeof document !== 'undefined' ? document.documentElement : undefined);
  if (!target) return;
  for (const [name, value] of Object.entries(resolveTokens(mode))) {
    target.style.setProperty(`--${name}`, value);
  }
  target.dataset.theme = mode;
}

/** antd 主题用得到的少量常量（antd 的算法要参与计算，不能接受 var() 字符串）。 */
export const APP_TOKENS = {
  accent: THEME_TOKENS.accent,
  primary: THEME_TOKENS.primary,
  link: THEME_TOKENS.link,
  bg: THEME_TOKENS.bg,
  surface: THEME_TOKENS.surface,
  label1: THEME_TOKENS['label-1'],
  label2: THEME_TOKENS['label-2'],
  label3: THEME_TOKENS['label-3'],
  line2: THEME_TOKENS['line-2'],
} as const;

export const APP_RADIUS = 8;

/**
 * antd `ConfigProvider` 的 theme 配置（与 CSS 变量**同源**：都出自 `resolveTokens(mode)`）。
 *
 * 为什么需要函数版：`APP_TOKENS` 取的是**浅色基底**的字面值，深色模式下若继续用它，
 * antd 组件（按钮/输入框/弹层）会保持浅色而页面背景变深 → 半深半浅。
 * antd 的 algorithm 要参与计算，只能给它字面值，不能给 `var(--x)`。
 */
export function buildTheme(mode: ThemeMode = 'light') {
  const t = resolveTokens(mode);
  return {
    algorithm: mode === 'dark' ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      colorPrimary: t.primary,
      colorLink: t.link,
      colorBgLayout: t.bg,
      colorBgContainer: t.surface,
      colorBgElevated: t.surface,
      colorText: t['label-1'],
      colorTextSecondary: t['label-2'],
      colorTextTertiary: t['label-3'],
      colorBorderSecondary: t['line-2'],
      borderRadius: APP_RADIUS,
    },
  };
}
