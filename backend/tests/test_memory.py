"""MemoryStore 单测：增删、去重、检索打分、上限淘汰、持久化。"""
from __future__ import annotations

import json

from app.storage.memory import MemoryStore


def test_add_and_dedup(tmp_path):
    s = MemoryStore(tmp_path / "facts.json")
    s.add("用户喜欢美式咖啡", category="preference")
    # 完全重复 → 合并，不新增
    s.add("用户喜欢美式咖啡")
    # 已包含新内容 → 合并，不新增
    s.add("美式咖啡")
    assert len(s.facts) == 1
    assert s.facts[0].category == "preference"
    assert s.facts[0].access_count >= 2


def test_search_relevance(tmp_path):
    s = MemoryStore(tmp_path / "facts.json")
    s.add("用户喜欢美式咖啡")
    s.add("用户养了一只猫叫糯米")
    s.add("用户住在嘉兴")
    hits = s.search("咖啡", top_k=3)
    assert hits[0].content == "用户喜欢美式咖啡"
    assert s.search("嘉兴")[0].content == "用户住在嘉兴"
    assert s.search("完全不相关的话题") == []


def test_recent_order(tmp_path):
    s = MemoryStore(tmp_path / "facts.json")
    s.add("第一条")
    s.add("第二条")
    r = s.recent(top_k=1)
    assert r[0].content == "第二条"


def test_eviction_drops_least_used(tmp_path):
    s = MemoryStore(tmp_path / "facts.json")
    # 直接注入超过上限（300）前先小规模验证淘汰逻辑
    from app.storage.memory import _MAX_FACTS

    s.facts = []
    for i in range(_MAX_FACTS + 10):
        s.add(f"事实{i}")
    assert len(s.facts) == _MAX_FACTS
    # 早写入且未被访问的应被淘汰
    contents = {f.content for f in s.facts}
    assert "事实0" not in contents


def test_persist_reload(tmp_path):
    p = tmp_path / "facts.json"
    s = MemoryStore(p)
    s.add("用户叫小明")
    s2 = MemoryStore(p)
    assert [f.content for f in s2.facts] == ["用户叫小明"]


def test_empty_add_ignored(tmp_path):
    s = MemoryStore(tmp_path / "facts.json")
    assert s.add("   ") is None
    assert s.facts == []
