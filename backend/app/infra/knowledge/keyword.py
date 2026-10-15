"""关键词召回：BM25 + 中英混合分词（与向量路并列的第二条召回通道）。

分词规则：英文与数字按词切，中文连续串按字符二元组（bigram）切，长度为 1 的中文串
保留原字；全部小写。不用 SQLite FTS5——是否可用取决于运行环境 SQLite 的编译选项，
私有化机器上不可控；个人知识库量级下，进程内全表打分与向量路成本同一量级。

IDF 用 Lucene 风格的饱和写法 ``log(1 + (N - df + 0.5) / (df + 0.5))``，保证恒非负；
TF 走 BM25 经典饱和（k1）加文档长度归一（b），避免长 chunk 靠堆词量拿高分。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

K1 = 1.2
B = 0.75

_TOKEN_RE = re.compile(r"[a-z0-9]+|[一-鿿]+")


def tokenize(text: str) -> list[str]:
    """中英混合分词：英文/数字整词 + 中文字符二元组。"""
    tokens: list[str] = []
    for part in _TOKEN_RE.findall((text or "").lower()):
        if part.isascii() or len(part) == 1:
            tokens.append(part)
        else:
            tokens.extend(part[start : start + 2] for start in range(len(part) - 1))
    return tokens


def bm25_scores(
    query: str,
    docs: Sequence[tuple[str, str]],
    *,
    k1: float = K1,
    b: float = B,
) -> dict[str, float]:
    """对 ``(chunk_key, text)`` 语料打 BM25 分，返回 ``{chunk_key: score}``。

    零分文档不入选（调用方按缺省 0 处理）；空查询或空语料返回空 dict。
    """
    terms = set(tokenize(query))
    if not terms or not docs:
        return {}
    tokenized = [(key, Counter(tokenize(text))) for key, text in docs]
    lengths = [sum(counter.values()) for _, counter in tokenized]
    total_length = sum(lengths)
    if total_length <= 0:
        return {}
    doc_count = len(tokenized)
    avg_length = total_length / doc_count
    document_frequency: Counter[str] = Counter()
    for _, counter in tokenized:
        document_frequency.update(counter.keys())

    scores: dict[str, float] = {}
    for (key, counter), length in zip(tokenized, lengths, strict=True):
        score = 0.0
        for term in terms:
            tf = counter.get(term, 0)
            if not tf:
                continue
            df = document_frequency[term]
            idf = math.log(1 + (doc_count - df + 0.5) / (df + 0.5))
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * length / avg_length))
        if score > 0:
            scores[key] = score
    return scores
