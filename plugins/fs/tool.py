"""fs 能力插件：文件工具（read_file / write_file / list_dir / search_files / delete_file）。

作用域（V2 需求：项目绑定本机真实目录）：
- 工具执行时经 langchain 注入的 `config: RunnableConfig` 取 thread_id，
  查会话所属项目的绑定目录；绑定则所有操作限定在该目录内，未绑定回退工作区。
路径安全：resolve 后必须落在作用域根内，`..` 穿越 / 绝对路径逃逸一律拒绝。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.config import settings
from app.projects import ProjectStore

_MAX_READ = 8000


def _projects() -> ProjectStore:
    """模块级缓存 ProjectStore（同一 SQLite，读取为主，低频写）。"""
    store = getattr(_projects, "_store", None)
    if store is None:
        store = ProjectStore(Path(settings.db_file).parent / "threads.db")
        _projects._store = store  # type: ignore[attr-defined]
    return store


def _thread_id(config: RunnableConfig | None) -> str | None:
    """当前会话 thread_id：优先 contextvars（stream 入口设置，create_agent 工具
    执行不注入 config），回退 config.configurable.thread_id（直接 invoke 场景）。"""
    # 注意：此处不直接 import app.thread_ctx（避免 plugins 与 app 循环），用延迟导入
    try:
        from app.thread_ctx import get_thread_id

        tid = get_thread_id()
        if tid:
            return tid
    except Exception:
        pass
    if not config:
        return None
    c = config.get("configurable") or {}
    tid = c.get("thread_id")
    if not tid:
        return None
    tid = str(tid)
    # 后端 checkpointer key 为 "{user}::{thread_id}"（无 user 时纯 thread_id），
    # 而 threads 表主键是纯 thread_id——剥离前缀后查询
    return tid.rsplit("::", 1)[-1] if "::" in tid else tid


def _root(config: RunnableConfig | None) -> tuple[Path, str]:
    """作用域根：项目绑定目录（存在时）或工作区。返回 (根路径, 根描述)。"""
    tid = _thread_id(config)
    if tid:
        try:
            directory = _projects().directory_of_thread(tid)
        except Exception:
            directory = None
        if directory and Path(directory).expanduser().resolve().is_dir():
            return Path(directory).expanduser().resolve(), f"项目目录 {directory}"
    ws = settings.workspace_path
    return ws.resolve(), f"工作区 {ws}"


def _resolve(path: str, config: RunnableConfig | None) -> Path:
    """把相对/绝对路径解析到当前作用域根内；越界抛 ValueError。"""
    root, desc = _root(config)
    p = Path(path).expanduser()
    p = p if p.is_absolute() else root / p
    p = p.resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"路径必须在{desc}内，收到：{path}")
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
def read_file(path: str, max_chars: int = _MAX_READ, config: RunnableConfig | None = None) -> str:
    """读取当前作用域（项目绑定目录或工作区）内的文本文件，返回内容（最多 max_chars 字符）。"""
    return _safe(_read, path, max_chars, config)


def _read(path: str, max_chars: int, config: RunnableConfig | None) -> str:
    p = _resolve(path, config)
    if not p.is_file():
        return f"（文件不存在：{path}）"
    data = p.read_text(encoding="utf-8", errors="replace")
    if len(data) > max_chars:
        data = data[:max_chars] + "\n…（内容已截断）"
    return data or "（空文件）"


@tool
def write_file(path: str, content: str, mode: str = "overwrite", config: RunnableConfig | None = None) -> str:
    """把内容写入当前作用域内的文件。mode=overwrite 覆盖 / append 追加；父目录自动创建。"""
    return _safe(_write, path, content, mode, config)


def _write(path: str, content: str, mode: str, config: RunnableConfig | None) -> str:
    if mode not in ("overwrite", "append"):
        return f"未知 mode {mode}，可选：overwrite / append"
    p = _resolve(path, config)
    p.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append":
        with p.open("a", encoding="utf-8") as f:
            f.write(content)
        return f"已追加到 {path}（{len(content)} 字符）"
    p.write_text(content, encoding="utf-8")
    return f"已写入 {path}（{len(content)} 字符）"


@tool
def list_dir(path: str = ".", config: RunnableConfig | None = None) -> str:
    """列出当前作用域目录下的条目（名称 + 类型 + 大小），一层。"""
    return _safe(_list, path, config)


def _list(path: str, config: RunnableConfig | None) -> str:
    p = _resolve(path, config)
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
def search_files(pattern: str, path: str = ".", config: RunnableConfig | None = None) -> str:
    """在当前作用域目录下按文件名 glob 模式递归搜索（如 *.md、notes/*.txt）。"""
    return _safe(_search, pattern, path, config)


def _search(pattern: str, path: str, config: RunnableConfig | None) -> str:
    p = _resolve(path, config)
    if not p.is_dir():
        return f"（目录不存在：{path}）"
    root, _ = _root(config)
    hits = sorted(str(x.relative_to(root)) for x in p.rglob(pattern) if x.is_file())
    hits = hits[:200]
    if not hits:
        return f"（未匹配 {pattern}）"
    return "\n".join(hits) + (f"\n…共 {len(hits)} 项" if len(hits) >= 200 else "")


@tool
def delete_file(path: str, config: RunnableConfig | None = None) -> str:
    """删除当前作用域内的一个文件（不可恢复，谨慎使用）。"""
    return _safe(_delete, path, config)


def _delete(path: str, config: RunnableConfig | None) -> str:
    p = _resolve(path, config)
    if not p.is_file():
        return f"（文件不存在：{path}）"
    p.unlink()
    return f"已删除 {path}"


TOOLS: list[Any] = [read_file, write_file, list_dir, search_files, delete_file]
