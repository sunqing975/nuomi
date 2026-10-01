/** i18n · 入口：t(key, params?) 翻译 + locale 管理（localStorage 持久化）。 */
import zhCN, { type MessageKey } from "./zh-CN";

export type Locale = "zh-CN";

const DICTS: Record<Locale, Record<MessageKey, string>> = {
  "zh-CN": zhCN,
};

export const LOCALES: { id: Locale; label: string }[] = [{ id: "zh-CN", label: "中文" }];

let current: Locale =
  (typeof localStorage !== "undefined" && (localStorage.getItem("nuomi-locale") as Locale | null)) ||
  "zh-CN";

export function getLocale(): Locale {
  return current;
}

export function setLocale(l: Locale): void {
  current = l;
  try {
    localStorage.setItem("nuomi-locale", l);
  } catch {
    /* 忽略存储不可用 */
  }
}

/** 翻译：key 必须在 zh-CN 字典中存在（类型强约束）；params 做 {x} 插值。 */
export function t(key: MessageKey, params?: Record<string, string | number>): string {
  let s = DICTS[current][key] ?? (DICTS["zh-CN"][key] as string | undefined) ?? key;
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      s = s.split(`{${k}}`).join(String(v));
    }
  }
  return s;
}
