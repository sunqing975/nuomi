/** 主题注册表（对齐 Octop dashboard 主题体系）：
 *  - 明暗双模式（dark/light，data-theme 覆盖原始 token）
 *  - 品牌色板（8 个 curated palette + 可自定义，对齐 Octop rose/tech/indigo/teal/violet/emerald/amber/slate）
 *  色板色同时注入 antd ConfigProvider token（colorPrimary）与 CSS 变量。 */
import type { MessageKey } from "./i18n/zh-CN";

export interface ThemeDef {
  id: string;
  label: MessageKey;
}

export const THEMES: ThemeDef[] = [
  { id: "dark", label: "settings.general.themeDark" },
  { id: "light", label: "settings.general.themeLight" },
];

export type PaletteId =
  | "rose"
  | "tech"
  | "indigo"
  | "teal"
  | "violet"
  | "emerald"
  | "amber"
  | "slate";

export interface PaletteDef {
  id: PaletteId;
  label: MessageKey;
  color: string; // 品牌主色（对齐 Octop PALETTE_SWATCH）
}

export const PALETTES: PaletteDef[] = [
  { id: "rose", label: "palette.rose", color: "#E85D75" },
  { id: "tech", label: "palette.tech", color: "#4B74FA" },
  { id: "indigo", label: "palette.indigo", color: "#6366F1" },
  { id: "teal", label: "palette.teal", color: "#0D9488" },
  { id: "violet", label: "palette.violet", color: "#7C3AED" },
  { id: "emerald", label: "palette.emerald", color: "#10B981" },
  { id: "amber", label: "palette.amber", color: "#F59E0B" },
  { id: "slate", label: "palette.slate", color: "#64748B" },
];

export const DEFAULT_PALETTE: PaletteId = "rose";
export const PALETTE_STORAGE_KEY = "nuomi-palette";

export function isPaletteId(v: string): v is PaletteId {
  return PALETTES.some((p) => p.id === v);
}
