"""记忆 v2 · MemoryBackend 契约测试（对齐 Hermes 设计）。

覆盖：FileMemoryBackend（内置 SQLite provider）增删改查/双档快照/容量截取/
唯一子串定位；快照渲染格式；Mem0Backend 的契约映射（fake mem0，不依赖外部服务）。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from app.domain.experts.middleware import _render_snapshot
from app.storage.memory import FileMemoryBackend, MemoryStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _backend(tmp_path, char_limits=None):
    store = MemoryStore(tmp_path / "facts.db")
    return FileMemoryBackend(store, char_limits=char_limits)


# ---------- FileMemoryBackend：增删改查 ----------


def test_add_dedup_and_list(tmp_path):
    b = _backend(tmp_path)
    b.add("用户喜欢美式咖啡", category="preference")
    b.add("用户喜欢美式咖啡")  # 完全重复 → 合并
    assert len(b.list()) == 1
    assert b.list()[0].category == "preference"


def test_replace_unique_substring(tmp_path):
    b = _backend(tmp_path)
    b.add("用户住在嘉兴，工作在杭州")
    b.add("用户养了一只猫叫糯米")
    code, msg = b.replace("嘉兴", "用户住在上海，工作在杭州")
    assert code == 1 and "上海" in msg
    assert b.list()[0].content == "用户住在上海，工作在杭州"


def test_replace_not_found(tmp_path):
    b = _backend(tmp_path)
    b.add("用户喜欢咖啡")
    code, msg = b.replace("不存在的词", "新内容")
    assert code == 0 and "未找到" in msg


def test_replace_ambiguous(tmp_path):
    b = _backend(tmp_path)
    b.add("用户喜欢美式咖啡")
    b.add("用户喜欢拿铁咖啡")
    code, msg = b.replace("咖啡", "用户喜欢茶")
    assert code == -1 and "多条" in msg


def test_remove_unique_substring(tmp_path):
    b = _backend(tmp_path)
    b.add("临时记录：明天买牛奶")
    b.add("用户住在嘉兴")
    code, msg = b.remove("明天买牛奶")
    assert code == 1
    assert len(b.list()) == 1
    # 再删不存在的 → 未找到
    assert b.remove("不存在")[0] == 0


# ---------- 双档快照 + 容量截取 ----------


def test_snapshot_two_sections_and_char_limit(tmp_path):
    b = _backend(tmp_path, char_limits={"memory": 30, "user": 20})
    b.add("A" * 25, category="fact")
    b.add("B" * 25, category="fact")
    b.add("用户喜欢咖啡", category="preference")
    snap = b.snapshot()
    sections = {s["name"]: s for s in snap["sections"]}
    mem, user = sections["MEMORY"], sections["USER"]
    # preference → USER 档；MEMORY 档不含 preference
    assert user["entries"][0].content == "用户喜欢咖啡"
    assert all(e.category != "preference" for e in mem["entries"])
    # 30 字符预算只能装 1 条 25 字符
    assert len(mem["entries"]) == 1
    assert mem["total_chars"] <= mem["char_limit"]
    assert user["total_chars"] <= user["char_limit"]


def test_snapshot_render_format(tmp_path):
    b = _backend(tmp_path)
    b.add("用户喜欢美式咖啡", category="preference")
    b.add("项目是 Rust 服务")
    text = _render_snapshot(b.snapshot())
    assert "【记忆快照】" in text
    assert "MEMORY" in text and "USER" in text
    assert "%" in text and "字符" in text
    assert "§ 项目是 Rust 服务" in text
    assert "§ 用户喜欢美式咖啡" in text


def test_snapshot_empty_backend(tmp_path):
    text = _render_snapshot(_backend(tmp_path).snapshot())
    assert "【记忆快照】" in text
    assert "MEMORY" not in text  # 无条目不渲染分段


# ---------- Mem0Backend 契约映射（fake mem0） ----------


def _install_fake_mem0(monkeypatch):
    """在 sys.modules 注入 fake mem0：Memory.from_config / add / search / update / delete / get_all。"""
    store: list[dict] = []

    class FakeMemory:
        @classmethod
        def from_config(cls, config):
            return cls(config)

        def __init__(self, config):
            self.config = config

        def add(self, message, user_id=None, metadata=None):
            store.append(
                {"id": f"m{len(store) + 1}", "memory": message, "metadata": metadata or {}}
            )
            return {"results": [{"id": f"m{len(store)}"}]}

        def search(self, query, user_id=None, limit=100):
            return {"results": [m for m in store if query in m["memory"]][:limit]}

        def update(self, memory_id, data):
            for m in store:
                if m["id"] == memory_id:
                    m["memory"] = data.get("memory", m["memory"])
            return {"success": True}

        def delete(self, memory_id):
            nonlocal store
            store = [m for m in store if m["id"] != memory_id]
            return {"success": True}

        def get_all(self, user_id=None):
            return {"results": list(store)}

    mod = types.ModuleType("mem0")
    mod.Memory = FakeMemory
    monkeypatch.setitem(sys.modules, "mem0", mod)
    return store


def _load_mem0_hook():
    spec = importlib.util.spec_from_file_location(
        "memory_mem0_hook",
        REPO_ROOT / "backend" / "app" / "domain" / "memory" / "memory-mem0" / "memory_mem0.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_mem0_backend_contract(tmp_path, monkeypatch):
    _install_fake_mem0(monkeypatch)
    Mem0Backend = _load_mem0_hook().Mem0Backend
    b = Mem0Backend({"mode": "openmemory"})
    b.add("用户喜欢美式咖啡", category="preference")
    b.add("项目是 Rust 服务")
    assert len(b.list()) == 2
    hits = b.search("咖啡")
    assert hits and "咖啡" in hits[0].content
    code, msg = b.replace("美式", "用户喜欢拿铁")
    assert code == 1
    assert b.list()[0].content == "用户喜欢拿铁"
    code, msg = b.remove("Rust")
    assert code == 1
    assert len(b.list()) == 1
    snap = b.snapshot()
    sections = {s["name"]: s for s in snap["sections"]}
    assert sections["USER"]["entries"][0].content == "用户喜欢拿铁"
    assert sections["MEMORY"]["entries"] == []


def test_mem0_plugin_apply_requires_dependency(monkeypatch, fake_app):
    """mem0ai 未安装时 apply 应明确报错（fiber FAILED，UI 可见提示）。"""
    monkeypatch.delitem(sys.modules, "mem0", raising=False)
    hook = _load_mem0_hook()
    try:
        hook.apply(fake_app)
        assert False, "未装 mem0ai 时应抛 RuntimeError"
    except RuntimeError as e:
        assert "mem0ai" in str(e)
