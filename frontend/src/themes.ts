/** 主题注册表：新增主题 = 在此加一条 + styles/themes/<id>.css（data-theme 覆盖原始 token）。 */
import type { MessageKey } from "./i18n/zh-CN";

export interface ThemeDef {
  id: string;
  label: MessageKey;
}

export const THEMES: ThemeDef[] = [
  { id: "dark", label: "settings.general.themeDark" },
  { id: "light", label: "settings.general.themeLight" },
];
