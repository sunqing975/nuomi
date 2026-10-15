/**
 * 深色/浅色主题的**运行时状态**（localStorage 持久化 + React 订阅）。
 *
 * 为什么要单独一个模块而不是 props 往下传：主题要同时被两处消费——
 * `main.tsx` 的 antd `ConfigProvider`（在 App 外层）和 `App.tsx` 顶栏的切换按钮（在里层），
 * props 穿透整棵页面树只为一个开关不值当。
 *
 * 为什么默认浅色：界面是按浅色设计的（token 基底即浅色），深色只是覆盖层
 * （`THEME_OVERRIDES.dark`）；而且部分页面仍有硬编码浅色值（见 HANDOVER §8.2
 * 「内联样式 160 处」），所以入口明确做成**用户可选**，不跟着系统自动切，
 * 免得哪天截图/录屏突然变黑。
 */

import { useSyncExternalStore } from 'react';

import { applyCssTokens, type ThemeMode } from './theme';

const STORAGE_KEY = 'nuomi.theme';

let current: ThemeMode = readStored();
const listeners = new Set<() => void>();

function readStored(): ThemeMode {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) === 'dark' ? 'dark' : 'light';
  } catch {
    // 隐私模式 / 测试环境没有 storage：按默认浅色
    return 'light';
  }
}

export function getThemeMode(): ThemeMode {
  return current;
}

/** 切换主题：写 CSS 变量 → 落盘 → 通知订阅者（antd 与 CSS 变量必须同源变，否则半深半浅）。 */
export function setThemeMode(mode: ThemeMode): void {
  current = mode;
  applyCssTokens(mode);
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, mode);
  } catch {
    /* 存不下也要能切（本次会话内生效） */
  }
  listeners.forEach(l => l());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useThemeMode(): [ThemeMode, (mode: ThemeMode) => void] {
  const mode = useSyncExternalStore(
    subscribe,
    getThemeMode,
    () => 'light' as ThemeMode, // SSR 快照：本项目没有 SSR，仅满足 hook 签名
  );
  return [mode, setThemeMode];
}
