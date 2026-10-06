/**
 * MessageBubble：单条对话消息气泡（用户/助手）+ 片段渲染全家桶。
 *
 * 从 Chat.tsx 抽出（P0-4，2026-10-06）——纯重构，行为不变。
 * 内部含片段级渲染依赖：MarkdownText（引用剥离）、SegmentView（思考折叠/
 * 工具调用卡片）、PluginToolCard（插件聊天面板，octop ui/ 协议）。
 */

import { RobotOutlined, UserOutlined } from '@ant-design/icons';
import { Tag } from 'antd';
import { useEffect, useState, type CSSProperties } from 'react';
import ReactMarkdown from 'react-markdown';

import type { ChatMessage, Segment } from '../../api';
import { get } from '../../api';
import { parseKnowledgeCitations, type KnowledgeCitation } from '../../utils/parseKnowledgeCitations';
import { sanitizePluginHtml } from '../../utils/sanitizePluginHtml';

/** 知识库引用标签条（citations 列表 → Tag 行） */
function CitationsTags({ citations }: { citations: KnowledgeCitation[] }) {
  if (!citations.length) return null;
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ fontSize: 12, color: 'var(--label-3)', marginBottom: 4 }}>📚 知识库引用</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
        {citations.map(c => (
          <Tag key={c.docId} style={{ fontSize: 12, margin: 0 }}>
            {c.kbName || '知识库'} · {c.filename}
          </Tag>
        ))}
      </div>
    </div>
  );
}

/** 知识库引用条（search_knowledge 工具输出含 citations 标记时展示来源） */
function KnowledgeCitations({ raw }: { raw?: string }) {
  const { text, citations } = parseKnowledgeCitations(raw);
  if (!citations.length) return null;
  return (
    <div>
      <CitationsTags citations={citations} />
      {text ? (
        <div style={{ color: 'var(--label-2)', marginTop: 2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 120, overflow: 'auto' }}>
          {text}
        </div>
      ) : null}
    </div>
  );
}

/** 正文 Markdown 渲染：剥离知识库引用标记 → md 渲染正文 → 引用标签条（历史/流式正文共用） */
export function MarkdownText({ raw, placeholder }: { raw?: string; placeholder?: string }) {
  const { text, citations } = parseKnowledgeCitations(raw);
  if (!text.trim() && !citations.length) return <>{placeholder ?? ''}</>;
  return (
    <div>
      {text.trim() ? (
        <div className="md-body" style={{ fontSize: 14, lineHeight: 1.6, wordBreak: 'break-word' }}>
          <ReactMarkdown>{text}</ReactMarkdown>
        </div>
      ) : null}
      <CitationsTags citations={citations} />
    </div>
  );
}

/** 插件聊天面板（第三层插件能力，对齐 octop ui/ 协议）：
 *  manifest.json 声明 {"ui": {"tool": "工具名", "render": "index.js"}}，
 *  index.js ES module export default { render(ctx) => HTML }。
 *  工具结果命中声明 → 动态加载 render 渲染成聊天卡片；未命中保持文本折叠。
 */
interface PluginUiTarget { pluginId: string; render: string; }

const pluginUiRegistry = new Map<string, PluginUiTarget>();
let pluginUiLoaded = false;

/** 预载插件聊天面板注册表（ChatPage 挂载时调用一次） */
export async function loadPluginUiRegistry() {
  if (pluginUiLoaded) return;
  pluginUiLoaded = true;
  try {
    const plugins = await get<{ plugin_id: string; enabled: boolean }[]>('/plugins');
    for (const p of plugins) {
      if (!p.enabled) continue;
      let manifest: { ui?: { tool?: string; render?: string } };
      try {
        manifest = await get(`/plugins/${p.plugin_id}/ui-manifest`);
      } catch {
        continue; // 未声明聊天面板（404）
      }
      if (manifest?.ui?.tool && manifest.ui.render) {
        pluginUiRegistry.set(manifest.ui.tool, { pluginId: p.plugin_id, render: manifest.ui.render });
      }
    }
  } catch {
    // 面板加载失败不影响对话
  }
}

/** 工具结果卡片容器样式：对齐 octop builtin 卡片（白底/圆角/边框/阴影，硬编码保证可见） */
const toolCardStyle: CSSProperties = {
  marginTop: 4,
  padding: '12px 14px',
  borderRadius: 10,
  border: '1px solid var(--line-3)',
  background: 'var(--surface)',
  color: 'var(--label-1)',
  maxWidth: 480,
  boxShadow: '0 1px 2px rgba(16, 24, 40, 0.06)',
  fontSize: 13,
};

/** 工具结果卡片：动态加载插件 render 模块，调 render(ctx) 产出 HTML 渲染
 *  ctx: { result, args, data（解析后的结构化输出）, textFallback } —— 对齐 octop 渲染协议 */
function PluginToolCard({ toolName, result, args }: { toolName: string; result: string; args?: string }) {
  const [html, setHtml] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let target = pluginUiRegistry.get(toolName);
      if (!target) {
        await loadPluginUiRegistry(); // 兜底：registry 未就绪时补一次
        target = pluginUiRegistry.get(toolName);
      }
      if (!target) { setFailed(true); return; }
      try {
        // 运行时绝对 URL 动态加载（@vite-ignore：非构建期模块）
        const mod = await import(/* @vite-ignore */ `/api/plugins/${target.pluginId}/ui/${target.render}`);
        const fn = mod?.default?.render;
        // 尝试解析结构化输出传给 renderer（对齐 octop：data / textFallback 进 ctx）
        let data: unknown = null;
        try { data = JSON.parse(result); } catch { /* 非 JSON 文本 */ }
        const ctx = { result, args, data, textFallback: result };
        const out = typeof fn === 'function' ? String(fn(ctx) ?? '') : '';
        if (cancelled) return;
        // XSS 防护：插件 renderer 产出 HTML，而它插值的数据来自 tool 结果（可能是
        // LLM 读进来的外部网页/文档）。净化逻辑抽到 utils/sanitizePluginHtml 并单测覆盖
        // （原先内联调用无法单测，且 <img onerror> / <svg onload> / <iframe src=javascript:>
        // 等 8 种 payload 全部能绕过旧的「正则剥 <script>」实现 —— 与后端同源，注入即可读
        // /api/settings/env 明文密钥）。
        // supported=false 表示 DOM 不可用：此时 DOMPurify 会静默原样返回，必须显式降级。
        const { html: clean, supported } = sanitizePluginHtml(out);
        if (!supported) {
          setFailed(true);
          return;
        }
        setHtml(clean);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => { cancelled = true; };
  }, [toolName, result, args]);

  if (failed) {
    // 兜底：渲染失败/未声明面板时保留卡片样式框 + 原始结果文本（React 文本节点自动转义）
    return <div style={toolCardStyle}>{result}</div>;
  }
  if (html === null) {
    return <div style={{ fontSize: 12, color: 'var(--label-3)', marginTop: 4 }}>加载插件卡片…</div>;
  }
  if (!html.trim()) {
    // render 返回空：同样兜底为原始结果文本
    return <div style={toolCardStyle}>{result}</div>;
  }
  return (
    <div style={toolCardStyle} dangerouslySetInnerHTML={{ __html: html }} />
  );
}

/** 单片段渲染：思考折叠块 / 工具调用卡片 / 工具结果卡片（按对话真实顺序穿插） */
export function SegmentView({ seg }: { seg: Segment }) {
  const isTool = seg.type === 'tool_call' || seg.type === 'tool_result';
  const hasCard = seg.type === 'tool_result' && pluginUiRegistry.has(seg.name || '');
  // 有聊天卡片的工具结果默认展开（卡片是醒目结果，不需先点折叠）
  const [open, setOpen] = useState(isTool && hasCard);
  if (seg.type === 'reasoning') {
    return (
      <div style={{ marginBottom: 6, fontSize: 12, color: 'var(--label-4)' }}>
        <a onClick={() => setOpen(v => !v)} style={{ color: 'var(--accent-text)' }}>
          {open ? '▾' : '▸'} 💭 深度思考
        </a>
        {open && (
          <div style={{
            marginTop: 4, padding: '6px 8px', background: 'var(--surface-2)', borderRadius: 6,
            border: '1px solid var(--line-1)',
            whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 200, overflow: 'auto',
          }}>
            {seg.content}
          </div>
        )}
      </div>
    );
  }
  if (seg.type === 'tool_call' || seg.type === 'tool_result') {
    const isCall = seg.type === 'tool_call';
    const hasDetail = isCall ? !!(seg.args && seg.args !== '{}') : !!seg.content;
    const hasCard = seg.type === 'tool_result' && pluginUiRegistry.has(seg.name || '');
    return (
      <div style={{
        marginBottom: 6, fontSize: 12, padding: '4px 8px', borderRadius: 6, maxWidth: 520,
        background: isCall ? '#fff7e6' : '#f6ffed',
        border: `1px solid ${isCall ? '#ffd591' : '#d9f7be'}`,
      }}>
        <a onClick={() => setOpen(v => !v)} style={{ color: isCall ? '#d97706' : '#52c41a', fontWeight: 500, cursor: 'pointer' }}>
          {open ? '▾' : '▸'} {isCall ? '⚙ 调用' : '✓ 结果'} {seg.name || '(工具)'}
          {seg.plugin_id && (
            <Tag style={{ fontSize: 10, marginLeft: 6, marginRight: 0 }}>{seg.plugin_id}</Tag>
          )}
        </a>
        {open && hasDetail && (
          <div style={{ color: 'var(--label-2)', marginTop: 2, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: isCall ? 80 : 120, overflow: 'auto' }}>
            {hasCard
              ? <PluginToolCard toolName={seg.name || ''} result={seg.content ?? ''} args={seg.args} />
              : (isCall ? seg.args : (seg.name === 'search_knowledge' ? <KnowledgeCitations raw={seg.content} /> : seg.content))}
          </div>
        )}
      </div>
    );
  }
  return null;
}

/** 消息气泡：左侧助手（分段渲染）/ 右侧用户（纯文本）
 *
 * 气泡样式常量导出给 MessageList（流式块复用同一视觉，不出现两套气泡）。
 * 全站基准：助手=surface 白底细边框（克制），用户=primary 实色白字（强归属）；
 * 头像 32px：助手主色淡底+主色图标，用户 primary 底+白图标。
 */
export const assistantBubbleStyle: CSSProperties = {
  padding: '8px 12px',
  borderRadius: '4px 12px 12px 12px',
  background: 'var(--surface)',
  border: '1px solid var(--line-3)',
  color: 'var(--label-1)',
};
export const userBubbleStyle: CSSProperties = {
  padding: '8px 12px',
  borderRadius: '12px 12px 4px 12px',
  background: 'var(--primary)',
  color: '#fff',
};
export const assistantAvatarStyle: CSSProperties = {
  width: 32, height: 32, borderRadius: '50%', flexShrink: 0,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  background: '#f59e0b1a', border: '1px solid #f59e0b55',
};
export const userAvatarStyle: CSSProperties = {
  width: 32, height: 32, borderRadius: '50%', flexShrink: 0,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
  background: 'var(--primary)',
};

export function MessageBubble({ message, index }: { message: ChatMessage; index: number }) {
  const isUser = message.role === 'user';
  return (
    <div style={{ display: 'flex', marginBottom: 12, justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
      <div style={{ maxWidth: '78%', display: 'flex', gap: 8, flexDirection: isUser ? 'row-reverse' : 'row' }}>
        <div style={isUser ? userAvatarStyle : assistantAvatarStyle}>
          {isUser ? <UserOutlined style={{ color: '#fff', fontSize: 14 }} /> : <RobotOutlined style={{ color: '#d97706', fontSize: 15 }} />}
        </div>
        <div style={{ minWidth: 0 }}>
          {isUser
            ? message.segments.map((s, j) => (
                <div key={s.id ?? `m${index}-${j}`} style={{
                  ...userBubbleStyle, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 14, lineHeight: 1.6,
                }}>
                  {s.content}
                </div>
              ))
            : message.segments.map((s, j) =>
                s.type === 'text' ? (
                  <div key={s.id ?? `m${index}-${j}`} style={{ ...assistantBubbleStyle, marginBottom: 6, fontSize: 14, lineHeight: 1.6 }}>
                    <MarkdownText raw={s.content} placeholder="（空回复）" />
                  </div>
                ) : (
                  <SegmentView key={s.id ?? `m${index}-${j}`} seg={s} />
                ),
              )}
        </div>
      </div>
    </div>
  );
}
