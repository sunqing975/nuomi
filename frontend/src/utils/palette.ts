/**
 * 头像/图标底色：按实体 id 首字符稳定取色（同一实体颜色固定，不随刷新变）。
 *
 * 原先 5 个页面各抄了一份同样的 8 色表（Plugins / Connectors / Skills / Market /
 * SkillMarketPage），改一处忘四处。装饰色**不参与深色 token 化**：这 8 个色在
 * #0f1115 深底上依然可读，且它们是「区分实体」的标识，不该跟着主题变。
 */

export const AVATAR_COLORS = [
  '#f59e0b', '#3b82f6', '#10b981', '#ef4444',
  '#8b5cf6', '#ec4899', '#14b8a6', '#f97316',
] as const;

/** 取色：空串/非法首字符落回第一个色（保持原 `(seed.charCodeAt(0) || 0)` 语义）。 */
export function pickAvatarColor(seed: string): string {
  return AVATAR_COLORS[(seed.charCodeAt(0) || 0) % AVATAR_COLORS.length];
}
