"""fs 能力插件：工作区文件工具（read_file / write_file / list_dir / search_files / delete_file）。

路径安全：所有路径 resolve 后必须落在工作区根（backend/data/workspace）内，
`..` 穿越 / 绝对路径逃逸一律拒绝——对齐 dsh 文件工具的工作区边界语义。
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool

from app.config import settings

_MAX_READ = 8000


def _workspace() -> Path:
    return settings.workspace_path


def _resolve(path: str) -> Path:
    """把相对/绝对路径解析到工作区内；越界抛 ValueError。"""
    ws = _workspace().resolve()
    p = Path(path).expanduser()
    p = p if p.is_absolute() else ws / p
    p = p.resolve()
    if p != ws and ws not in p.parents:
        raise ValueError(f"路径必须在工作区内（{ws}），收到：{path}")
    return p


def _safe(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except FileNotFoundError:
        return "（文件或目录不存在）"
    except IsADirectoryError:
        return "（目标是目录，不是文件）"
    except PermissionError:
        return "（无权限访问）"
    except ValueError as e:
        return f"⛔ {e}"
    except Exception as e:  # OSError 等
        return f"操作失败：{e.__class__.__name__}: {e}"


@tool
def read_file(path: str, max_chars: int = _MAX_READ) -> str:
    """读取工作区内一个文本文件，返回内容（最多 max_chars 字符）。"""
    return _safe(_read, path, max_chars)


def _read(path: str, max_chars: int) -> str:
    p = _resolve(path)
    if not p.is_file():
        return f"（文件不存在：{path}）"
    data = p.read_text(encoding="utf-8", errors="replace")
    if len(data) > max_chars:
        data = data[:max_chars] + "\n…（内容已截断）"
    return data or "（空文件）"


@tool
def write_file(path: str, content: str, mode: str = "overwrite") -> str:
    """把内容写入工作区文件。mode=overwrite 覆盖 / append 追加；父目录自动创建。"""
    return _safe(_write, path, content, mode)


def _write(path: str, content: str, mode: str) -> str:
    if mode not in ("overwrite", "append"):
        return f"未知 mode {mode}，可选：overwrite / append"
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append":
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
        return f"已追加到 {path}（{len(content)} 字符）"
    p.write_text(content, encoding="utf-8")
    return f"已写入 {path}（{len(content)} 字符）"


@tool
def list_dir(path: str = ".") -> str:
    """列出工作区目录下的条目（名称 + 类型 + 大小），一层。"""
    return _safe(_list, path)


def _list(path: str) -> str:
    p = _resolve(path)
    if not p.is_dir():
        return f"（目录不存在：{path}）"
    rows = []
    for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if child.is_dir():
            rows.append(f"📁 {child.name}/")
        else:
            size = child.stat().st_size
            rows.append(f"📄 {child.name}  ({size} B)")
    return "\n".join(rows) if rows else "（空目录）"


@tool
def search_files(pattern: str, path: str = ".") -> str:
    """在工作区目录下按文件名 glob 模式递归搜索（如 *.md、notes/*.txt）。"""
    return _safe(_search, pattern, path)


def _search(pattern: str, path: str) -> str:
    p = _resolve(path)
    if not p.is_dir():
        return f"（目录不存在：{path}）"
    hits = sorted(str(x.relative_to(_workspace())) for x in p.rglob(pattern) if x.is_file())
    hits = hits[:200]
    if not hits:
        return f"（未匹配 {pattern}）"
    return "\n".join(hits) + (f"\n…共 {len(hits)} 项" if len(hits) >= 200 else "")


@tool
def delete_file(path: str) -> str:
    """删除工作区内的一个文件（不可恢复，谨慎使用）。"""
    return _safe(_delete, path)


def _delete(path: str) -> str:
    p = _resolve(path)
    if not p.is_file():
        return f"（文件不存在：{path}）"
    p.unlink()
    return f"已删除 {path}"


TOOLS = [read_file, write_file, list_dir, search_files, delete_file]
