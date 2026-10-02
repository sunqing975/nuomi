"""Phase 2 · 知识库 RAG：词法实现（确定性，离线测试）+ 工具层。"""
from __future__ import annotations

from pathlib import Path

from app.storage.knowledge import LexicalStore, build_knowledge_store
from app.main import build_app

from .fake_llm import FakeChatModel

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_app(tmp_path, kb_type="lexical"):
    return build_app(
        llm=FakeChatModel(),
        db_path=str(tmp_path / "t.sqlite"),
        skills_dir=str(REPO_ROOT / "plugins"),
        memory_file=str(tmp_path / "mem" / "facts.json"),
        knowledge_store_type=kb_type,
        knowledge_dir=str(tmp_path / "kb"),
    )


def test_lexical_store_add_search_count(tmp_path):
    store = LexicalStore(tmp_path / "kb")
    store.add("糯米是一只住在电脑里的小猫")
    store.add("用户喜欢喝冰美式咖啡", category="preference")
    assert store.count() == 2
    hits = store.search("咖啡", top_k=1)
    assert hits[0]["content"] == "用户喜欢喝冰美式咖啡"
    assert store.search("完全不相关") == []


def test_lexical_store_persist(tmp_path):
    p = tmp_path / "kb"
    LexicalStore(p).add("持久化测试文档")
    s2 = LexicalStore(p)
    assert s2.count() == 1


def test_factory_pluggable(tmp_path):
    assert isinstance(build_knowledge_store("lexical", tmp_path), LexicalStore)
    # chroma 工厂返回 ChromaStore（构造不下载模型，只有首次调用才初始化）
    from app.storage.knowledge import ChromaStore

    assert isinstance(build_knowledge_store("chroma", tmp_path), ChromaStore)


def test_knowledge_tools_end_to_end(tmp_path):
    app = _make_app(tmp_path, kb_type="lexical")
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        # 工具经加载器收集；lifespan 已把 store 注入全局单例
        from .conftest import applied_tools

        tools = {t.name: t for t in applied_tools(str(REPO_ROOT / "plugins"))}
        r1 = tools["knowledge_add"].invoke({"content": "糯米的生日是 4 月 1 日", "category": "fact"})
        assert "已存入知识库" in r1
        r2 = tools["knowledge_search"].invoke({"query": "糯米的生日是什么时候"})
        assert "4 月 1 日" in r2


def test_health_reports_knowledge(tmp_path):
    app = _make_app(tmp_path, kb_type="lexical")
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        app.state.knowledge.add("测试文档")
        body = client.get("/health").json()
        assert body["knowledge"]["store"] == "lexical"
        assert body["knowledge"]["documents"] == 1
