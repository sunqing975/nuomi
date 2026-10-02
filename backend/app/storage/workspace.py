"""storage/workspace.py · 工作区目录树（阶段 B：前端项目树 = 工作区目录）。

安全约束：只列工作区根之内的内容；跳过隐藏文件与常见构建/依赖目录；
深度与条目数上限，防止巨树拖垮前端。
"""
from __future__ import annotations

from pathlib import Path

_SKIP = {
    ".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build",
    ".DS_Store", ".idea", ".vscode", ".nuomi", ".gitignore",
}
MAX_DEPTH = 3
MAX_ENTRIES = 300


def list_tree(root: str | Path, max_depth: int = MAX_DEPTH, max_entries: int = MAX_ENTRIES) -> dict:
    """安全列出工作区目录树：{root, entries:[{name,type,size?,children?}]}。

    - 隐藏项（. 开头）与 _SKIP 中的依赖/构建目录一律跳过
    - 深度超过 max_depth 或条目数超过 max_entries 即截断（预算式，不递归爆炸）
    """
    root = Path(root).expanduser().resolve()
    budget = {"n": 0}

    def walk(d: Path, depth: int) -> list[dict]:
        if depth > max_depth or budget["n"] >= max_entries:
            return []
        out: list[dict] = []
        try:
            children = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except OSError:
            return out
        for child in children:
            if budget["n"] >= max_entries:
                break
            name = child.name
            if name.startswith(".") or name in _SKIP:
                continue
            budget["n"] += 1
            try:
                if child.is_dir():
                    out.append({"name": name, "type": "dir", "children": walk(child, depth + 1)})
                else:
                    out.append({"name": name, "type": "file", "size": child.stat().st_size})
            except OSError:
                continue
        return out

    return {"root": str(root), "entries": walk(root, 0)}


def safe_project_dirname(name: str) -> str:
    """项目名 → 安全目录名：去路径分隔符/非法字符，拒绝 . / .. / 空。"""
    import re

    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name.strip()).strip(" .")
    if cleaned in ("", ".", ".."):
        raise ValueError(f"项目名不合法：{name!r}")
    return cleaned
