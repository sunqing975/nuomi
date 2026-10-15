/**
 * 本轮 token 用量的展示格式化（纯函数，有单测）。
 *
 * 为什么要单独一层：后端 `infra/harness/chat.py` 每轮都发 `usage` 帧
 * （`_USAGE_KEYS` 白名单），但前端此前 `ChatEvent` 里没有 `'usage'` 分支，
 * 整条链的用量数据在浏览器里被**静默丢掉**——用户看不到花了多少，
 * 也看不到 P0 缓存（前缀缓存命中，DeepSeek 命中价 1/50）到底有没有生效。
 *
 * 口径说明（别把两个"输入"搞混）：
 * - `input_tokens` = 本轮输入总量（含命中部分）
 * - `uncached_input_tokens` = 未命中的输入（按全价计费）
 * - `cache_read_tokens` = 命中的输入（按缓存价计费）
 * 命中率 = cache_read / input。字段缺了就少说一段，不编数字；
 * 但**明确为 0 是要显示的信号**（缓存 0% = 前缀每次被重写），不能当成"没数据"。
 */

import type { ChatUsage } from '../api';

/** 缺失/非法 → null；0 是合法值，保留。 */
function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

/** 1234 → 1.2k；1234567 → 1.2M（用量展示要短，不要千位分隔符那种长串） */
export function compactTokens(value: number): string {
  if (value < 1000) return String(value);
  if (value < 1_000_000) return `${(value / 1000).toFixed(value < 10_000 ? 2 : 1)}k`;
  return `${(value / 1_000_000).toFixed(2)}M`;
}

export interface UsageView {
  /** 一行短标签，如「↑12.4k · ↓356 · 缓存 87%」 */
  label: string;
  /** 悬浮/详情里的完整口径 */
  detail: string;
  /** 缓存命中率 0–1；provider 没发 cache_read 字段时为 null（不显示缓存段） */
  cacheRatio: number | null;
}

/**
 * 把 usage 帧转成展示结构；没有可用数字时返回 null（调用方据此不渲染，
 * 避免出现「↑0 ↓0」这种看着像坏了的占位）。
 */
export function formatUsage(usage?: ChatUsage | null): UsageView | null {
  if (!usage) return null;
  const input = num(usage.input_tokens);
  const output = num(usage.output_tokens);
  const cached = num(usage.cache_read_tokens);
  const uncached = num(usage.uncached_input_tokens);
  // 全空或全 0 = provider 根本没回 usage，不渲染（与「缓存 0%」是两回事）
  if (![input, output, cached, uncached].some(v => v !== null && v > 0)) return null;

  // 输入侧：优先 input_tokens；缺它时用 uncached + cache_read 兜底（两家 provider 字段不一）
  const fallbackTotal = (uncached ?? 0) + (cached ?? 0);
  const inputTotal = input ?? (fallbackTotal > 0 ? fallbackTotal : null);
  const ratio = inputTotal !== null && inputTotal > 0 && cached !== null ? cached / inputTotal : null;

  const parts: string[] = [];
  if (inputTotal !== null) parts.push(`↑${compactTokens(inputTotal)}`);
  if (output !== null) parts.push(`↓${compactTokens(output)}`);
  const reason = num(usage.reasoning_tokens);
  if (reason !== null && output !== null && reason < output) parts.push(`含思考 ${compactTokens(reason)}`);
  if (ratio !== null) parts.push(`缓存 ${Math.round(ratio * 100)}%`);

  const detailParts: string[] = [];
  if (inputTotal !== null) detailParts.push(`输入 ${inputTotal.toLocaleString('zh-CN')}`);
  if (cached !== null) detailParts.push(`其中缓存命中 ${cached.toLocaleString('zh-CN')}`);
  if (uncached !== null) detailParts.push(`未命中 ${uncached.toLocaleString('zh-CN')}`);
  if (output !== null) detailParts.push(`输出 ${output.toLocaleString('zh-CN')}`);
  if (reason !== null) detailParts.push(`其中思考 ${reason.toLocaleString('zh-CN')}`);

  return { label: parts.join(' · '), detail: detailParts.join(' ｜ '), cacheRatio: ratio };
}

/**
 * usage 帧的数值键（与后端 infra/harness/chat.py 的 `_USAGE_KEYS` 对齐）。
 * 显式列出来而不是遍历对象：SSE 载荷是不可信外部输入，
 * `Object.keys` 遍历 + 原型键名会把 `__proto__` 之类带进累加结果。
 */
const USAGE_KEYS = [
  'input_tokens',
  'uncached_input_tokens',
  'cache_read_tokens',
  'cache_write_tokens',
  'output_tokens',
  'reasoning_tokens',
  'total_tokens',
] as const;

/**
 * 累加多个 usage 帧 → 这一轮的合计用量。
 *
 * 为什么要累加：一轮带工具的对话里 harness 会**每次 LLM 调用各发一帧**，
 * 而每次调用都各自计一次输入（provider 就是按次计费的），所以求和才是
 * 这一轮真实花掉的量；取最后一帧会少掉前面的调用，取第一帧会漏掉后面的。
 */
export function accumulateUsage(acc: ChatUsage | undefined, add: ChatUsage): ChatUsage {
  const out: Record<string, number> = { ...(acc ?? {}) };
  for (const key of USAGE_KEYS) {
    const value = add[key];
    if (typeof value !== 'number' || !Number.isFinite(value)) continue;
    const prev = typeof out[key] === 'number' ? (out[key] as number) : 0;
    out[key] = prev + value;
  }
  return out as ChatUsage;
}
