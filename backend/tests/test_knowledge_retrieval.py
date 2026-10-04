"""知识库检索与对话注入测试（隔离数据根；模型缓存 symlink 复用真实下载）。

覆盖：retrieve_context 端到端（跨库 top-k + 字符预算 + citations 标记）、
resolve_knowledge_base_ids（default_open 注入 / 显式覆盖 / 空列表不注入）、
工具描述格式化（空目录隐藏文案 / 附库目录）、chat 路由未知库 400。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.infra.knowledge.citations import append_citations_marker, strip_citations_marker
from app.infra.knowledge.default_open import resolve_knowledge_base_ids
from app.infra.knowledge.repo import KnowledgeRepo
from app.infra.knowledge.retrieve import retrieve_context
from app.infra.knowledge.tools import format_search_knowledge_description


@pytest.fixture(scope="module")
def kb_pair():
    """建一个含两个 ready 文档的知识库（"知识库实现"主题），供检索测试。"""
    from app.storage.db import init_db

    init_db()  # 无 TestClient 时也需建表
    from app.infra.knowledge.onnx_service import save_config

    save_config({"config": {"enabled": True, "model": "BAAI/bge-small-zh-v1.5"}})
    repo = KnowledgeRepo()
    base = repo.create_base(name="retrieve-test", description="检索测试库")
    kb_id = base.id
    docs = [
        ("rag.md", "本地知识库用 fastembed 做嵌入，SQLite 存向量，检索按余弦相似度排序。"),
        ("onnx.md", "模型从 HuggingFace 多源竞速下载，bge-small-zh-v1.5 输出 512 维向量。"),
    ]
    doc_ids: list[str] = []
    for filename, text in docs:
        row = repo.create_document(
            kb_id=kb_id, filename=filename, content_type="text/markdown", byte_size=len(text.encode())
        )
        from app.infra.knowledge.files import write_document

        write_document(kb_id, row.id, filename, text.encode())
        from app.infra.knowledge.jobs import process_document

        process_document(kb_id, row.id)
        assert repo.get_document(row.id).status == "ready"
        doc_ids.append(row.id)
    yield repo, kb_id, doc_ids
    # 清理
    repo.delete_base(kb_id)


def test_retrieve_context_hits(kb_pair) -> None:
    repo, kb_id, doc_ids = kb_pair
    context = asyncio.run(
        retrieve_context(query="知识库嵌入模型是什么", knowledge_base_ids=[kb_id], k=4)
    )
    assert "以下是知识库检索到的相关内容" in context
    assert "bge-small-zh-v1.5" in context or "fastembed" in context
    assert "<!--octop-kb-citations:" in context
    # citations 标记结构可解析
    import re

    payload = re.search(r"<!--octop-kb-citations:(\[.*?\])-->", context).group(1)
    citations = json.loads(payload)
    assert citations, "应至少有一条引用"
    assert all(c["doc_id"] in doc_ids for c in citations)


def test_retrieve_context_skip_unrelated(kb_pair) -> None:
    repo, kb_id, _ = kb_pair
    context = asyncio.run(
        retrieve_context(query="今天的天气怎么样", knowledge_base_ids=[kb_id], k=4)
    )
    # Octop 语义：无相似度阈值，top-k 有文档即返回（弱相关允许）；不得抛错，
    # 非空时必须为合法检索格式（preamble 开头）。
    assert context == "" or context.startswith("以下是知识库检索到的相关内容")


def test_retrieve_context_empty_inputs() -> None:
    assert asyncio.run(retrieve_context(query="", knowledge_base_ids=["x"])) == ""
    assert asyncio.run(retrieve_context(query="q", knowledge_base_ids=[])) == ""


def test_retrieve_char_budget(kb_pair) -> None:
    repo, kb_id, _ = kb_pair
    context = asyncio.run(
        retrieve_context(query="知识库实现", knowledge_base_ids=[kb_id], k=4, char_budget=200)
    )
    # 预算内（标记等少量溢出可忽略，正文 ≤ 预算 + 引头）
    body = strip_citations_marker(context)
    assert len(body) <= 400


def test_citations_marker_roundtrip() -> None:
    body = "检索正文"
    with_marker = append_citations_marker(
        body, [{"kb_id": "a", "kb_name": "库", "doc_id": "d1", "filename": "f.md", "path": "p/f.md"}]
    )
    assert "<!--octop-kb-citations:" in with_marker
    assert strip_citations_marker(with_marker) == body


def test_resolve_knowledge_base_ids() -> None:
    """显式指定才注入；None（未选）与 [] 均不注入（无默认打开一说）。"""
    assert resolve_knowledge_base_ids(None) == []  # 未选 = 不注入
    assert resolve_knowledge_base_ids(["b"]) == ["b"]  # 显式覆盖
    assert resolve_knowledge_base_ids([]) == []  # 明确不注入


def test_tool_description_formatting() -> None:
    none_desc = format_search_knowledge_description([])
    assert "没有可用的知识库" in none_desc
    listed = format_search_knowledge_description(
        [{"id": "kb1", "name": "产品文档", "description": "Nuomi 产品说明"}, {"id": "kb2", "name": "开发备忘"}]
    )
    assert "产品文档" in listed and "Nuomi 产品说明" in listed and "开发备忘" in listed


def test_chat_route_unknown_kb_400(client: TestClient) -> None:
    agents = client.get("/api/agents").json()
    agent = agents[0]
    r = client.post(
        f"/api/agents/{agent['agent_id']}/chat",
        json={"messages": "你好", "knowledge_base_ids": ["nope-not-exist"]},
    )
    assert r.status_code == 400
    assert "知识库不存在" in r.json()["detail"]


def test_chat_route_empty_messages_422(client: TestClient) -> None:
    """消息必填（空/空白消息 422，对齐「消息也是必要的」）。"""
    agents = client.get("/api/agents").json()
    agent = agents[0]
    for bad in ("", "   ", "\n"):
        r = client.post(
            f"/api/agents/{agent['agent_id']}/chat",
            json={"messages": bad},
        )
        assert r.status_code == 422, f"messages={bad!r} 应 422"


def test_chat_route_valid_kb_ok(client: TestClient, kb_pair) -> None:
    """合法 knowledge_base_ids 通过校验（流式 200，不校验推理内容）。"""
    agents = client.get("/api/agents").json()
    agent = agents[0]
    repo, kb_id, _ = kb_pair
    r = client.post(
        f"/api/agents/{agent['agent_id']}/chat",
        json={"messages": "知识库介绍", "knowledge_base_ids": [kb_id]},
    )
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]


def test_available_skill_keys_includes_builtin() -> None:
    """per-turn 白名单可用集合须含内置技能（对齐 Octop：catalog 含 builtin 层）。"""
    from app.transport.api import _available_skill_keys

    keys = _available_skill_keys()
    from app.domain.skills.service import skill_service

    for b in skill_service.builtin():
        assert b["name"] in keys
