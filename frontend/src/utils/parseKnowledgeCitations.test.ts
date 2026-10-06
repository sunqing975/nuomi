import { describe, expect, it } from 'vitest';
import { parseKnowledgeCitations } from './parseKnowledgeCitations';

/** 引用标记协议（Octop 沿用）：<!--octop-kb-citations:[{...}]--> 必须完整出现在输出末尾 */
const MARK = (json: string) => `<!--octop-kb-citations:${json}-->`;

describe('parseKnowledgeCitations', () => {
  it('标记跨 token 被截断：不解析、不抛错，原文原样保留', () => {
    // 流式/分块读出时标记可能只到一半（这里是 JSON 中途截断）
    const raw = '命中 2 条文档。\n' + '<!--octop-kb-citations:[{"doc_id":"d1","filename":"a.md"';
    const out = parseKnowledgeCitations(raw);
    expect(out.citations).toEqual([]);
    expect(out.text).toBe(raw);
  });

  it('标记未闭合（缺 -->）：不解析，原文原样保留', () => {
    const raw = '命中 1 条文档。\n' + '<!--octop-kb-citations:[{"doc_id":"d1","filename":"a.md"}]';
    const out = parseKnowledgeCitations(raw);
    expect(out.citations).toEqual([]);
    expect(out.text).toBe(raw);
  });

  it('标记内是非法 JSON：不解析、不抛错，原文原样保留', () => {
    const raw = '命中 1 条文档。\n' + MARK('[{doc_id:d1}]');
    const out = parseKnowledgeCitations(raw);
    expect(out.citations).toEqual([]);
    expect(out.text).toBe(raw);
  });

  it('合法标记：剥离标记、结构化引用去重且 filename 缺省回落 doc_id', () => {
    const raw =
      '命中 2 条文档。\n' +
      MARK(
        JSON.stringify([
          { kb_id: 'kb1', kb_name: '手册', doc_id: 'd1', filename: 'a.md', path: 'docs/a.md' },
          { kb_id: 'kb1', kb_name: '手册', doc_id: 'd1', filename: 'a.md' },
          { kb_id: 'kb2', kb_name: '规范', doc_id: 'd2' },
          { doc_id: '' },
        ]),
      );
    const out = parseKnowledgeCitations(raw);
    expect(out.text).toBe('命中 2 条文档。');
    expect(out.citations).toEqual([
      { kbId: 'kb1', kbName: '手册', docId: 'd1', filename: 'a.md', path: 'docs/a.md' },
      { kbId: 'kb2', kbName: '规范', docId: 'd2', filename: 'd2' },
    ]);
  });

  it('空输入安全', () => {
    expect(parseKnowledgeCitations(undefined)).toEqual({ text: '', citations: [] });
    expect(parseKnowledgeCitations('')).toEqual({ text: '', citations: [] });
  });
});
