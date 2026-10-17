import { describe, expect, it } from 'vitest';
import { feedChatStream, chatStream, type ChatEvent } from './api';

/**
 * 一次完整响应的帧序列（octop 原生事件帧）。中间刻意混入空行、非 data 行、
 * 未知 type、非法 JSON —— 都应当被忽略且不影响后续帧。
 */
const BODY = [
  'data: {"type":"reasoning","content":"先想一下"}',
  '',
  'data: {"type":"tool_call_chunk","name":"search_knowledge","args":"{\\"q\\":\\"糯米\\"}","plugin_id":"kb-plugin"}',
  'event: ping',
  'data: {"type":"tool_result","messages":[{"name":"search_knowledge","content":"命中 3 条","plugin_id":"kb-plugin"}]}',
  'data: {"type":"usage","usage":{"input_tokens":12400,"uncached_input_tokens":1600,"cache_read_tokens":10800,"output_tokens":356,"total_tokens":12756},"node":"model"}',
  'data: {"type":"token","content":"你"}',
  'data: {"type":"token","content":"好"}',
  'data: {"type":"unknown","content":"忽略我"}',
  'data: {"type":"token","content": broken json',
  'data: {"type":"error","message":"上游超时"}',
  'data: {"type":"done"}',
  '',
].join('\n');

const EXPECTED: ChatEvent[] = [
  { type: 'reasoning', content: '先想一下' },
  { type: 'tool_call', name: 'search_knowledge', content: '{"q":"糯米"}', plugin_id: 'kb-plugin' },
  { type: 'tool_result', name: 'search_knowledge', detail: '命中 3 条', plugin_id: 'kb-plugin' },
  { type: 'usage', usage: { input_tokens: 12400, uncached_input_tokens: 1600, cache_read_tokens: 10800, output_tokens: 356, total_tokens: 12756 } },
  { type: 'token', content: '你' },
  { type: 'token', content: '好' },
  { type: 'error', content: '上游超时' },
  { type: 'done' },
];

const BYTES = new TextEncoder().encode(BODY);

/** 把整段响应按 size 字节切片喂进去（模拟网络分片），返回累计事件。 */
function feedInSlices(size: number): ChatEvent[] {
  const decoder = new TextDecoder('utf-8');
  let buf = '';
  const events: ChatEvent[] = [];
  for (let i = 0; i < BYTES.length; i += size) {
    const parsed = feedChatStream(buf, decoder.decode(BYTES.subarray(i, i + size), { stream: true }));
    buf = parsed.buf;
    events.push(...parsed.events);
  }
  // 流结束：flush 解码器残留（本例没有，但真实链路同样要收尾）
  const tail = feedChatStream(buf, decoder.decode());
  events.push(...tail.events);
  return events;
}

describe('feedChatStream · SSE 分帧', () => {
  // size=1/2 会切在多字节中文字符（3 字节）中间，同时验证 TextDecoder 流式解码与半行缓冲
  it.each([1, 2, 3, 5, 7, 13, 64, 4096, BYTES.length])('按 %i 字节切片喂入，事件序列一致', size => {
    expect(feedInSlices(size)).toEqual(EXPECTED);
  });

  it('token/reasoning/tool_call/tool_result/usage/error/done 七类都能解析出来', () => {
    const types = new Set(feedInSlices(7).map(e => e.type));
    expect([...types].sort()).toEqual(['done', 'error', 'reasoning', 'token', 'tool_call', 'tool_result', 'usage']);
  });

  it('半行留在残留缓冲，不产生半截事件', () => {
    const first = feedChatStream('', 'data: {"type":"token","cont');
    expect(first.events).toEqual([]);
    expect(first.buf).toBe('data: {"type":"token","cont');

    const second = feedChatStream(first.buf, 'ent":"嗨"}\ndata: {"type":"done"}\n');
    expect(second.events).toEqual([{ type: 'token', content: '嗨' }, { type: 'done' }]);
    expect(second.buf).toBe('');
  });

  it('CRLF 行尾同样解析', () => {
    expect(feedChatStream('', 'data: {"type":"token","content":"a"}\r\n').events).toEqual([
      { type: 'token', content: 'a' },
    ]);
  });

  it('非 data 行、空 payload、非法 JSON 全部跳过且不中断', () => {
    const parsed = feedChatStream('', [
      ': keep-alive',
      'data:',
      'data: not-json',
      'data: {"type":"token","content":"ok"}',
      '',
    ].join('\n'));
    expect(parsed.events).toEqual([{ type: 'token', content: 'ok' }]);
  });

  it('透出 approval_requested 审批帧（含 request 卡片数据）', () => {
    const parsed = feedChatStream(
      '',
      [
        'data: {"type":"tool_call_chunk","name":"mes_submit_work_report","args":"{\\"work_order_id\\":\\"WO-A-2026-0071\\"}"}',
        'data: {"type":"approval_requested","request_id":"abc123","request":{"action_requests":[{"name":"mes_submit_work_report","args":{"work_order_id":"WO-A-2026-0071","quantity":50}}]}}',
        'data: {"type":"done"}',
        '',
      ].join('\n'),
    );
    expect(parsed.events).toEqual([
      { type: 'tool_call', name: 'mes_submit_work_report', content: '{"work_order_id":"WO-A-2026-0071"}', plugin_id: undefined },
      {
        type: 'approval_requested',
        request_id: 'abc123',
        request: {
          action_requests: [
            { name: 'mes_submit_work_report', args: { work_order_id: 'WO-A-2026-0071', quantity: 50 } },
          ],
        },
      },
      { type: 'done' },
    ]);
  });
});

describe('chatStream · 流收尾', () => {
  /** 用假 reader 顶掉 fetch：只关心「最后一行没有尾随换行」时的收尾行为 */
  function fakeResponse(chunks: string[]): Response {
    let i = 0;
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      body: {
        getReader: () => ({
          read: async () => (i < chunks.length
            ? { done: false, value: new TextEncoder().encode(chunks[i++]) }
            : { done: true, value: undefined }),
        }),
      },
      json: async () => ({}),
    } as unknown as Response;
  }

  it('末尾没有换行的 done 帧不能丢（read 循环退出时必须 flush 缓冲）', async () => {
    const realFetch = globalThis.fetch;
    const seen: ChatEvent[] = [];
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/session-token')) return fakeResponse(['{"token":"t"}']);
      // 注意：最后一行刻意不带换行 —— 真实链路里后端 close 前就是这样收尾的
      return fakeResponse(['data: {"type":"token","content":"好"}\n\ndata: {"type":"done"}']);
    }) as typeof fetch;
    try {
      await chatStream('agent-1', 'hi', 'thread-1', e => seen.push(e));
    } finally {
      globalThis.fetch = realFetch;
    }
    expect(seen).toEqual([{ type: 'token', content: '好' }, { type: 'done' }]);
  });
});
