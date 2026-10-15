"""混合召回测试：BM25 关键词路 + 向量路 + 加权融合 + 降级路径。

纯函数用例不依赖嵌入模型；端到端那条 monkeypatch 掉向量化与知识库仓储，专门验证
「向量路挂了也能靠关键词出结果」这条降级，不真跑 ONNX。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.infra.knowledge import retrieve as retrieve_mod
from app.infra.knowledge.fusion import fuse
from app.infra.knowledge.index import KnowledgeIndex
from app.infra.knowledge.keyword import bm25_scores, tokenize
from app.infra.knowledge.params import get_advanced_settings

KB_ID = "hybrid-test-kb"


def test_tokenize_cjk_bigrams_and_ascii_words() -> None:
    tokens = tokenize("混合召回 BM25 与 top-k")
    assert {"混合", "合召", "召回"} <= set(tokens)
    assert {"bm25", "top", "k"} <= set(tokens)


def test_tokenize_ignores_punctuation_only_text() -> None:
    assert tokenize("") == []
    assert tokenize("！！！？？，，") == []


def test_bm25_scores_only_matching_documents() -> None:
    docs = [
        ("scholarship", "奖学金发放批次查询与学生资助政策"),
        ("card", "校园卡充值记录与门禁权限"),
    ]
    scores = bm25_scores("奖学金发放批次", docs)
    assert set(scores) == {"scholarship"}
    assert bm25_scores("", docs) == {}
    assert bm25_scores("完全无关的外文词汇", docs) == {}


def test_bm25_rare_term_outranks_common_term() -> None:
    docs = [("a", "奖学金"), ("b", "学生"), ("c", "学生")]
    rare = bm25_scores("奖学金", docs)
    common = bm25_scores("学生", docs)
    assert rare["a"] > common["b"]


def test_fuse_weight_selects_the_dominant_route() -> None:
    vector = {("kb", "c1"): 0.9, ("kb", "c2"): 0.1}
    keyword = {("kb", "c2"): 7.5, ("kb", "c3"): 2.0}

    vector_only = [key for key, _ in fuse(vector, keyword, keyword_weight=0.0)]
    assert vector_only[0] == ("kb", "c1")

    keyword_only = [key for key, _ in fuse(vector, keyword, keyword_weight=1.0)]
    assert keyword_only[0] == ("kb", "c2")

    merged = {key for key, _ in fuse(vector, keyword, keyword_weight=0.5)}
    assert merged == {("kb", "c1"), ("kb", "c2"), ("kb", "c3")}


def test_fuse_edge_cases() -> None:
    assert fuse({}, {}) == []
    # 某一路全部同分（或为空）时该路弃权：归一后全 0，排序由另一路决定
    assert all(score == 0.0 for _, score in fuse({"a": 0.5, "b": 0.5}, {}))
    assert [key for key, _ in fuse({"a": 0.5, "b": 0.5}, {}, keyword_weight=0.3)][0] in {"a", "b"}
    # 权重越界被钳制，不产生负数或超 1 的权重
    assert fuse({"a": 1.0, "b": 0.0}, {"a": 0.0, "b": 1.0}, keyword_weight=5.0)[0][0] == "b"


def test_hybrid_keyword_weight_param(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KNOWLEDGE_HYBRID_KEYWORD_WEIGHT", raising=False)
    assert get_advanced_settings()["hybrid_keyword_weight"] == pytest.approx(0.3)
    monkeypatch.setenv("KNOWLEDGE_HYBRID_KEYWORD_WEIGHT", "70")
    assert get_advanced_settings()["hybrid_keyword_weight"] == pytest.approx(0.7)
    monkeypatch.setenv("KNOWLEDGE_HYBRID_KEYWORD_WEIGHT", "999")
    assert get_advanced_settings()["hybrid_keyword_weight"] == pytest.approx(1.0)
    monkeypatch.setenv("KNOWLEDGE_HYBRID_KEYWORD_WEIGHT", "abc")
    assert get_advanced_settings()["hybrid_keyword_weight"] == pytest.approx(0.3)


@pytest.fixture()
def kb_index() -> KnowledgeIndex:
    index = KnowledgeIndex(KB_ID)
    index.replace_doc_chunks(
        "doc-scholarship",
        ["奖学金发放批次查询失败原因与补卡流程", "校园一卡通充值记录"],
        [[1.0, 0.0], [0.0, 1.0]],
    )
    index.replace_doc_chunks("doc-access", ["门禁权限申请流程"], [[0.2, 0.9]])
    yield index
    index.path.unlink(missing_ok=True)


def test_keyword_search_returns_bm25_hits(kb_index: KnowledgeIndex) -> None:
    hits = kb_index.keyword_search("奖学金发放批次", k=5)
    assert [hit.doc_id for hit in hits] == ["doc-scholarship"]
    assert hits[0].score > 0
    assert "奖学金" in hits[0].text


def test_keyword_search_empty_cases(kb_index: KnowledgeIndex) -> None:
    assert kb_index.keyword_search("完全无关的外文词汇", k=5) == []
    assert kb_index.keyword_search("奖学金", k=0) == []


def test_retrieve_degrades_to_keyword_only_when_embedding_fails(
    kb_index: KnowledgeIndex,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retrieve_mod, "load_config", lambda: SimpleNamespace(enabled=True, model="dummy-model")
    )

    def _boom(_texts: list[str]) -> list[list[float]]:
        msg = "embedding offline"
        raise RuntimeError(msg)

    monkeypatch.setattr(retrieve_mod, "embed_knowledge_texts", _boom)

    documents = [
        SimpleNamespace(
            id="doc-scholarship", filename="奖学金.md", path="", status="ready", is_dir=False
        ),
        SimpleNamespace(id="doc-access", filename="门禁.md", path="", status="ready", is_dir=False),
    ]
    monkeypatch.setattr(
        retrieve_mod,
        "KnowledgeRepo",
        lambda: SimpleNamespace(
            get_base=lambda kb_id: SimpleNamespace(id=kb_id, name="测试库"),
            list_documents=lambda kb_id: documents,
        ),
    )

    context = asyncio.run(
        retrieve_mod.retrieve_context(query="奖学金发放批次", knowledge_base_ids=[KB_ID], k=3)
    )
    assert context.startswith("以下是知识库检索到的相关内容")
    assert "奖学金" in context
    assert "门禁" not in context


def test_retrieve_skipped_when_knowledge_feature_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        retrieve_mod, "load_config", lambda: SimpleNamespace(enabled=False, model=None)
    )
    context = asyncio.run(
        retrieve_mod.retrieve_context(query="奖学金", knowledge_base_ids=[KB_ID], k=3)
    )
    assert context == ""
