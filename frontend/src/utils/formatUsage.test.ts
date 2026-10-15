import { describe, expect, it } from 'vitest';
import { accumulateUsage, compactTokens, formatUsage } from './formatUsage';

describe('compactTokens', () => {
  it('小于 1000 原样，万以上保留一位小数', () => {
    expect(compactTokens(356)).toBe('356');
    expect(compactTokens(1234)).toBe('1.23k');
    expect(compactTokens(12400)).toBe('12.4k');
    expect(compactTokens(2_400_000)).toBe('2.40M');
  });
});

describe('formatUsage', () => {
  it('给出 ↑↓ 与缓存命中率', () => {
    const v = formatUsage({
      input_tokens: 12400, uncached_input_tokens: 1600, cache_read_tokens: 10800, output_tokens: 356,
    })!;
    expect(v.label).toBe('↑12.4k · ↓356 · 缓存 87%');
    expect(v.cacheRatio).toBeCloseTo(0.871, 3);
    expect(v.detail).toContain('输入 12,400');
    expect(v.detail).toContain('缓存命中 10,800');
  });

  it('缺 input_tokens 时用 uncached + cache_read 兜底', () => {
    const v = formatUsage({ uncached_input_tokens: 200, cache_read_tokens: 800, output_tokens: 50 })!;
    expect(v.label).toContain('↑1.00k');
    expect(v.cacheRatio).toBeCloseTo(0.8, 3);
  });

  it('什么都没有 → null（不放「↑0 ↓0」这种看着像坏了的占位）', () => {
    expect(formatUsage(undefined)).toBeNull();
    expect(formatUsage({})).toBeNull();
    expect(formatUsage({ input_tokens: 0, output_tokens: 0 })).toBeNull();
  });

  it('provider 没发 cache_read 字段时不显示缓存段（也不假装 0%）', () => {
    const v = formatUsage({ input_tokens: 500, output_tokens: 80 })!;
    expect(v.label).toBe('↑500 · ↓80');
    expect(v.cacheRatio).toBeNull();
  });

  it('明确发了 cache_read_tokens: 0 → 显示「缓存 0%」（前缀每次被重写，这正是要看的信号）', () => {
    const v = formatUsage({ input_tokens: 500, cache_read_tokens: 0, output_tokens: 80 })!;
    expect(v.cacheRatio).toBe(0);
    expect(v.label).toBe('↑500 · ↓80 · 缓存 0%');
  });

  it('思考 token 只在确实小于输出时才单独提', () => {
    expect(formatUsage({ input_tokens: 100, output_tokens: 300, reasoning_tokens: 200 })!.label).toContain('含思考 200');
    expect(formatUsage({ input_tokens: 100, output_tokens: 50, reasoning_tokens: 500 })!.label).not.toContain('含思考');
  });
});

describe('accumulateUsage', () => {
  it('逐帧求和：一轮里多次 LLM 调用才是真实花费', () => {
    const a = accumulateUsage(undefined, { input_tokens: 1000, cache_read_tokens: 800, output_tokens: 100 });
    const b = accumulateUsage(a, { input_tokens: 2000, cache_read_tokens: 1500, output_tokens: 50 });
    expect(b).toEqual({ input_tokens: 3000, cache_read_tokens: 2300, output_tokens: 150 });
    expect(formatUsage(b)!.label).toBe('↑3.00k · ↓150 · 缓存 77%');
  });

  it('只累加白名单键（SSE 载荷不可信，未知字段不进结果）', () => {
    const acc = accumulateUsage(undefined, { input_tokens: 5, node: 'model', evil: 1 } as never);
    expect(Object.keys(acc).sort()).toEqual(['input_tokens']);
  });
});
