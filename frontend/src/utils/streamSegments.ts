import type { Segment } from '../api';

/**
 * 追加一个流式片段：相邻同类（text / reasoning）合并累积，其余直接追加。
 *
 * 为什么是纯函数并返回**新数组**：合并必须产出新的片段对象。原实现直接
 * `last.content += …` 原地改写 —— 而 last 早就进过 React state（`setStreamSegments([...segs])`
 * 只浅拷贝数组，元素仍是同一引用），既让引用比较看不到变化，也把上一次已经提交渲染的
 * 快照一起改了。合并时保留 last 的 id，折叠状态（SegmentView 的 open）才不跳。
 */
export function appendStreamSegment(segs: Segment[], s: Segment): Segment[] {
  const last = segs[segs.length - 1];
  if (last && s.type === last.type && (s.type === 'text' || s.type === 'reasoning')) {
    return [...segs.slice(0, -1), { ...last, content: (last.content || '') + (s.content || '') }];
  }
  return [...segs, s];
}
