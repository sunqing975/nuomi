import DOMPurify from 'dompurify';

/**
 * 插件聊天卡片（plugin renderer 产出的 HTML）净化。
 *
 * 为什么单独成模块：renderer 插值的数据来自 tool 结果，而 tool 结果往往是 LLM 读进来的
 * 外部网页/文档。原先只用正则剥 `<script>`，`<img onerror>` / `<svg onload>` /
 * `<iframe src=javascript:>` 等 8 种 payload 全部绕过；控制台与后端同源，注入即可读
 * `/api/settings/env`（明文密钥）或调插件导入接口。改用 DOMPurify 白名单净化后，
 * 这段逻辑必须能被单测覆盖，所以从 Chat.tsx 内联调用抽到这里。
 */

export interface SanitizedPluginHtml {
  /** 净化后的 HTML；`supported === false` 时为空串（调用方应降级为纯文本渲染） */
  html: string;
  /**
   * DOMPurify 是否具备可用 DOM。
   * 关键：DOM 不受支持时 DOMPurify.sanitize 会**静默原样返回**（不抛错），
   * 所以必须显式判 isSupported，否则拿到的“净化结果”其实就是原始 HTML，等于没消毒。
   */
  supported: boolean;
}

const SANITIZE_CONFIG: Parameters<typeof DOMPurify.sanitize>[1] = {
  // style 一并禁掉：卡片只需结构，CSS 注入可做钓鱼覆盖
  FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'link', 'base'],
  FORBID_ATTR: ['srcdoc', 'formaction'],
  ALLOW_DATA_ATTR: false,
};

/** 净化插件 renderer 产出的 HTML。 */
export function sanitizePluginHtml(raw: string): SanitizedPluginHtml {
  if (!DOMPurify.isSupported) return { html: '', supported: false };
  return { html: DOMPurify.sanitize(raw ?? '', SANITIZE_CONFIG), supported: true };
}
