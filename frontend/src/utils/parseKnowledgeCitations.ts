/**
 * 解析 search_knowledge 工具输出中的知识库引用标记（协议沿用 Octop）：
 *   <!--octop-kb-citations:[{"kb_id","kb_name","doc_id","filename","path"},...]-->
 * 返回展示文本（去掉标记）与结构化引用列表。
 */

export type KnowledgeCitation = {
  kbId: string;
  kbName: string;
  docId: string;
  filename: string;
  path?: string;
};

const CITATIONS_MARKER_RE =
  /\n*\s*<!--octop-kb-citations:(\[[\s\S]*?\])-->\s*$/;

function asCitation(raw: unknown): KnowledgeCitation | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  const docId = String(row.doc_id ?? row.docId ?? '').trim();
  if (!docId) return null;
  const path = String(row.path ?? '').trim();
  return {
    kbId: String(row.kb_id ?? row.kbId ?? '').trim(),
    kbName: String(row.kb_name ?? row.kbName ?? '').trim(),
    docId,
    filename: String(row.filename ?? '').trim() || docId,
    ...(path ? { path } : {}),
  };
}

/** 拆分工具输出：展示文本 + 结构化引用（有标记才解析）。 */
export function parseKnowledgeCitations(rawOutput: string | undefined): {
  text: string;
  citations: KnowledgeCitation[];
} {
  const raw = rawOutput ?? '';
  if (!raw) return { text: '', citations: [] };
  const match = raw.match(CITATIONS_MARKER_RE);
  if (!match) return { text: raw, citations: [] };
  const text = raw.slice(0, match.index).replace(/\s+$/, '');
  let parsed: unknown;
  try {
    parsed = JSON.parse(match[1] ?? '[]');
  } catch {
    return { text: raw, citations: [] };
  }
  if (!Array.isArray(parsed)) return { text, citations: [] };
  const citations: KnowledgeCitation[] = [];
  const seen = new Set<string>();
  for (const item of parsed) {
    const citation = asCitation(item);
    if (!citation || seen.has(citation.docId)) continue;
    seen.add(citation.docId);
    citations.push(citation);
  }
  return { text, citations };
}
