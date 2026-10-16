import { describe, expect, it } from 'vitest';
import { AVATAR_COLORS, pickAvatarColor } from './palette';

describe('pickAvatarColor', () => {
  it('同一 id 取色稳定', () => {
    expect(pickAvatarColor('6a3b128b89e9')).toBe(pickAvatarColor('6a3b128b89e9'));
  });

  it('永远落在色板内', () => {
    for (const seed of ['a', 'z', '0', '中文', 'plugin-x']) {
      expect(AVATAR_COLORS).toContain(pickAvatarColor(seed));
    }
  });

  it('空串落回第一个色（不让 NaN 下标漏出去）', () => {
    expect(pickAvatarColor('')).toBe(AVATAR_COLORS[0]);
  });

  it('首字符不同，颜色不同', () => {
    expect(pickAvatarColor('a')).not.toBe(pickAvatarColor('b'));
  });
});
