"""两路召回结果的加权融合（Dify / Octop 的 weighted-score 路线，不是 RRF）。

BM25 分数是无界正数、余弦相似度在 [-1, 1]，直接相加等于让量纲大的那一路说了算，
所以两路各自做 min-max 归一到 [0, 1] 再加权：

    fused = weight * 关键词归一分 + (1 - weight) * 向量归一分

约定与取舍：
- 只出现在一路的候选，另一路按 0 分计——关键词没命中的段落不该因为向量凑巧高就被
  判成"两边都说好"，反之同理；
- 某一路全空或全部同分（归一分母为 0）时，该路统一给 0 分，等价于这一路弃权，
  结果由另一路决定，不会炸；
- ``weight`` 由调用方保证在 [0, 1]（见 ``params.get_advanced_settings`` 的钳制）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def _normalize(scores: Sequence[float]) -> list[float]:
    low, high = min(scores), max(scores)
    if high <= low:
        return [0.0] * len(scores)
    span = high - low
    return [(value - low) / span for value in scores]


def fuse[KeyT](
    vector_scores: Mapping[KeyT, float],
    keyword_scores: Mapping[KeyT, float],
    *,
    keyword_weight: float = 0.3,
) -> list[tuple[KeyT, float]]:
    """合并两路分数，返回按融合分降序的 ``(key, score)`` 列表。

    key 可以是 chunk_id，也可以是 ``(kb_id, chunk_id)``——跨库检索时用后者，
    避免不同库里同名 chunk 互相覆盖。
    """
    keys = list(dict.fromkeys([*vector_scores.keys(), *keyword_scores.keys()]))
    if not keys:
        return []
    vector_norm = dict(
        zip(keys, _normalize([vector_scores.get(key, 0.0) for key in keys]), strict=True)
    )
    keyword_norm = dict(
        zip(keys, _normalize([keyword_scores.get(key, 0.0) for key in keys]), strict=True)
    )
    weight = max(0.0, min(1.0, keyword_weight))
    fused = [(key, weight * keyword_norm[key] + (1 - weight) * vector_norm[key]) for key in keys]
    fused.sort(key=lambda item: (item[1], str(item[0])), reverse=True)
    return fused
