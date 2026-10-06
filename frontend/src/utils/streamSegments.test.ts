import { describe, expect, it } from 'vitest';
import type { Segment } from '../api';
import { appendStreamSegment } from './streamSegments';

describe('appendStreamSegment', () => {
  it('相邻 text 合并：内容拼接、保留首段 id、不原地改写已进 state 的对象', () => {
    const first: Segment = { id: 'seg-1', type: 'text', content: '你好' };
    const before: Segment[] = [first];

    const after = appendStreamSegment(before, { id: 'seg-2', type: 'text', content: '，世界' });

    expect(after).toEqual([{ id: 'seg-1', type: 'text', content: '你好，世界' }]);
    expect(after).not.toBe(before);
    // 关键回归点：原实现会把 first 就地改掉（引用不变、内容变了）
    expect(first.content).toBe('你好');
    expect(before).toEqual([{ id: 'seg-1', type: 'text', content: '你好' }]);
  });

  it('相邻 reasoning 同样合并', () => {
    const after = appendStreamSegment(
      [{ id: 'r1', type: 'reasoning', content: '先' }],
      { id: 'r2', type: 'reasoning', content: '想' },
    );
    expect(after).toEqual([{ id: 'r1', type: 'reasoning', content: '先想' }]);
  });

  it('类型不同不合并（正文→思考→正文各成一段）', () => {
    let segs: Segment[] = [];
    segs = appendStreamSegment(segs, { id: 'a', type: 'text', content: '答案' });
    segs = appendStreamSegment(segs, { id: 'b', type: 'reasoning', content: '再想' });
    segs = appendStreamSegment(segs, { id: 'c', type: 'text', content: '补充' });
    expect(segs.map(s => [s.type, s.content])).toEqual([
      ['text', '答案'],
      ['reasoning', '再想'],
      ['text', '补充'],
    ]);
  });

  it('工具片段一律追加不合并（即使同名同类型相邻）', () => {
    let segs: Segment[] = [];
    segs = appendStreamSegment(segs, { id: 't1', type: 'tool_call', name: 'x' });
    segs = appendStreamSegment(segs, { id: 't2', type: 'tool_call', name: 'x' });
    expect(segs).toHaveLength(2);
    expect(segs[0]).not.toBe(segs[1]);
  });

  it('空数组追加返回新数组', () => {
    const empty: Segment[] = [];
    const after = appendStreamSegment(empty, { id: 'x', type: 'text', content: 'a' });
    expect(after).toHaveLength(1);
    expect(empty).toHaveLength(0);
  });

  it('缺失 content 时按空串处理', () => {
    const after = appendStreamSegment(
      [{ id: 'x', type: 'text' }],
      { id: 'y', type: 'text', content: 'ok' },
    );
    expect(after[0].content).toBe('ok');
  });
});
