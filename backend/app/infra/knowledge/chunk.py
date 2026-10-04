"""定长重叠字符分块（抄 Octop ``chunk``）：稳定、无状态。"""

from __future__ import annotations


def chunk_text(text: str, *, size: int, overlap: int) -> list[str]:
    """把文本（先 strip）切成 size 字符的窗口，相邻窗口重叠 overlap 字符。

    与 Octop 行为一致（strip → step=size-overlap 固定滑窗，末块保留余数），
    保证可复算。
    """
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be non-negative and smaller than size")
    content = text.strip()
    if not content:
        return []
    step = size - overlap
    chunks: list[str] = []
    for start in range(0, len(content), step):
        chunks.append(content[start : start + size])
        if start + size >= len(content):
            break
    return chunks
