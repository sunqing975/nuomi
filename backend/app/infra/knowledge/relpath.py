"""知识库相对路径：文件夹与文档路径规范化（抄 Octop ``relpath``）。

工作区风格相对路径：无前导斜杠、无 ``..``、反斜杠转正斜杠。
"""

from __future__ import annotations


def normalize_kb_path(raw: str | None) -> str:
    """返回工作区风格相对路径（无前导斜杠、无 ``..``）；空输入返回空串。"""
    text = str(raw or "").replace("\\", "/").strip()
    if not text or text == ".":
        return ""
    if text.startswith("/"):
        text = text[1:]
    parts = [part for part in text.split("/") if part and part != "."]
    if any(part == ".." for part in parts):
        raise ValueError("invalid knowledge document path")
    return "/".join(parts)


def path_basename(path: str) -> str:
    normalized = normalize_kb_path(path)
    if not normalized:
        return ""
    return normalized.rsplit("/", 1)[-1]


def path_parent(path: str) -> str:
    normalized = normalize_kb_path(path)
    if "/" not in normalized:
        return ""
    return normalized.rsplit("/", 1)[0]


def path_is_direct_child(path: str, prefix: str) -> bool:
    """True 当 *path* 是文件夹 *prefix* 的直接子项（空 prefix = 根）。"""
    normalized = normalize_kb_path(path)
    parent = normalize_kb_path(prefix)
    if not normalized or normalized == parent:
        return False
    if not parent:
        return "/" not in normalized
    if not normalized.startswith(parent + "/"):
        return False
    rest = normalized[len(parent) + 1 :]
    return bool(rest) and "/" not in rest


def ancestor_dirs(path: str) -> list[str]:
    """自根到文件的父文件夹路径（不含文件自身）。"""
    normalized = normalize_kb_path(path)
    if "/" not in normalized:
        return []
    parts = normalized.split("/")[:-1]
    out: list[str] = []
    acc: list[str] = []
    for part in parts:
        acc.append(part)
        out.append("/".join(acc))
    return out
