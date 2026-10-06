import { describe, expect, it } from 'vitest';
import {
  applyCssTokens, APP_RADIUS, CORE_KEYS, resolveTokens, THEME_OVERRIDES, THEME_TOKENS,
} from './theme';

/**
 * 设计 token 的结构性保证。
 *
 * 这里**不做**「两份值比对」—— token 只有一处定义（theme.ts），启动时注入成 CSS 变量，
 * 组件统一 `var(--x)`，所以漂移在结构上不可能发生。测试转而锁住几件真正会出事的事：
 * 主题覆盖是否完整、注入是否真的落到了 root 上。
 */
describe('设计 token', () => {
  it('深色覆盖层必须包含全部核心键（漏一个就会在深色下露白）', () => {
    for (const key of CORE_KEYS) {
      expect(THEME_OVERRIDES.dark).toHaveProperty(key);
    }
  });

  it('浅色不需要覆盖（它就是基底）', () => {
    expect(Object.keys(THEME_OVERRIDES.light)).toHaveLength(0);
  });

  it('resolveTokens 深色 = 浅色基底 + 深色覆盖', () => {
    const dark = resolveTokens('dark');
    expect(dark.bg).toBe(THEME_OVERRIDES.dark.bg);
    expect(dark.accent).toBe(THEME_TOKENS.accent); // 未覆盖的沿用基底
    expect(resolveTokens('light')).toEqual(THEME_TOKENS);
  });

  it('所有 token 名都是合法的 CSS 变量名，且值非空', () => {
    for (const [name, value] of Object.entries(THEME_TOKENS)) {
      expect(name).toMatch(/^[a-z0-9-]+$/);
      expect(value).toBeTruthy();
    }
  });

  it('applyCssTokens 把合并后的 token 全部写到 root，并打上 data-theme', () => {
    const root = document.createElement('div');
    applyCssTokens('dark', root);
    for (const [name, value] of Object.entries(resolveTokens('dark'))) {
      expect(root.style.getPropertyValue(`--${name}`)).toBe(value);
    }
    expect(root.dataset.theme).toBe('dark');
  });

  it('切换主题会覆盖同名变量（而不是叠加出两套）', () => {
    const root = document.createElement('div');
    applyCssTokens('light', root);
    expect(root.style.getPropertyValue('--bg')).toBe(THEME_TOKENS.bg);
    applyCssTokens('dark', root);
    expect(root.style.getPropertyValue('--bg')).toBe(THEME_OVERRIDES.dark.bg);
    expect(root.dataset.theme).toBe('dark');
  });

  it('antd 常量与 token 同源（antd 不能读 var()，只能给它字面值）', () => {
    expect(APP_RADIUS).toBe(parseInt(THEME_TOKENS['radius-md'], 10));
  });
});
