"""知识库存储层 + 索引端到端验证（smoke test）。

用法（backend/ 下）：`.venv/bin/python probe_knowledge.py`

验证目标：
1. 建库 → 上传 md 文档（文件夹路径）→ 异步索引（状态机 ready/chunk_count）
2. 每 KB SQLite sidecar 索引：chunk 落库、embedding_dim 回填
3. 检索语义：相关文档 chunk 得分高于无关文档
4. 编辑文档（update_text_document）→ 重索引生效；删除文档 → 索引清理
"""
from __future__ import annotations

import asyncio
import time

from app.infra.knowledge.embed import embed_knowledge_texts
from app.infra.knowledge.index import KnowledgeIndex
from app.infra.knowledge.jobs import enqueue_index_document

# 若模型尚未下载则先下载（对齐 probe_embeddings 流程）
from app.infra.knowledge.onnx_download import download_model_raced
from app.infra.knowledge.onnx_service import (
    DEFAULT_EMBEDDING_MODEL,
    embedding_models_dir,
    is_model_downloaded,
    mark_model_downloaded,
    require_embedding_prerequisites,
)
from app.infra.knowledge.service import KnowledgeService
from app.storage.db import init_db

KB_NAME = f"probe-kb-{int(time.time())}"


def _ensure_model() -> None:
    model = DEFAULT_EMBEDDING_MODEL
    if not is_model_downloaded(model):
        print(f"[download] {model} …")
        winner = download_model_raced(model, embedding_models_dir())
        mark_model_downloaded(model)
        print(f"[ok] 下载完成（源={winner}）")
    require_embedding_prerequisites()


async def _index(doc_ids: list[tuple[str, str]]) -> None:
    """并发入队并等待全部完成（索引并发 2，验证任务调度）。"""
    tasks = [enqueue_index_document(kb, doc) for kb, doc in doc_ids]
    await asyncio.gather(*tasks)


async def main() -> None:
    init_db()
    _ensure_model()
    svc = KnowledgeService()

    kb = svc.create_base(
        name=KB_NAME,
        description="知识库存储层验证",
        default_open=False,
    )
    print(f"[ok] 建库: {kb.id} {kb.name} (max_documents={kb.max_documents}, model={kb.embedding_model})")

    # 1) 上传两个主题不同的 md + 一个文件夹路径文档
    relevant = """# Nuomi 知识库架构
知识库由文档、向量索引与检索工具组成。文档上传后被异步解析、分块并向量化，
向量写入每个知识库独立的 SQLite sidecar 索引。对话时通过内置工具按余弦相似度
检索 top-k 片段，把带引用的上下文注入给模型。嵌入默认使用本地 ONNX 模型，
例如 BAAI/bge-small-zh-v1.5，维度 512。分块默认 800 字符、重叠 120。"""
    unrelated = """# 周末行程
周六去公园散步，周日在家看电影。天气好的话带相机拍照，
晚上约朋友吃火锅。记得提前买票，避免排队太久。"""
    doc_a = svc.upload_document(
        kb.id, filename="knowledge.md", content_type="text/markdown", content=relevant.encode("utf-8")
    )
    doc_b = svc.upload_document(
        kb.id, filename="notes/weekend.md", content_type="text/markdown", content=unrelated.encode("utf-8")
    )
    print(f"[ok] 上传: {doc_a.path} / {doc_b.path}")

    # 2) 异步索引（并发 2）
    await _index([(kb.id, doc_a.id), (kb.id, doc_b.id)])

    rows = svc.list_documents(kb.id)
    by_id = {r.id: r for r in rows}
    assert by_id[doc_a.id].status == "ready" and by_id[doc_a.id].chunk_count > 0, "文档A索引未就绪"
    assert by_id[doc_b.id].status == "ready" and by_id[doc_b.id].chunk_count > 0, "文档B索引未就绪"
    refreshed = svc.get_base(kb.id)
    assert refreshed.embedding_dim == 512, f"embedding_dim 未回填: {refreshed.embedding_dim}"
    assert refreshed.doc_count == 2
    print(f"[ok] 索引就绪: A chunks={by_id[doc_a.id].chunk_count} B chunks={by_id[doc_b.id].chunk_count} dim={refreshed.embedding_dim}")
    print(f"[ok] 文件夹行: {[r.path for r in rows if r.is_dir]}")

    # 3) 检索语义：相关查询应命中文档 A，无关查询命中 B
    idx = KnowledgeIndex(kb.id)
    q_rel = embed_knowledge_texts(["知识库的向量索引用什么存储？"])[0]
    hits_rel = idx.search(q_rel, k=3)
    top_rel = hits_rel[0].doc_id if hits_rel else ""
    print(f"[retrieve] 相关查询 top: {top_rel} score={hits_rel[0].score:.4f}" if hits_rel else "[retrieve] 无命中")
    assert top_rel == doc_a.id, "相关查询未命中知识库文档"

    q_un = embed_knowledge_texts(["周末去哪里玩？"])[0]
    hits_un = idx.search(q_un, k=3)
    top_un = hits_un[0].doc_id if hits_un else ""
    assert top_un == doc_b.id, "无关查询未命中周末文档"
    print(f"[retrieve] 无关查询 top: {top_un} score={hits_un[0].score:.4f}")

    # 4) 编辑文档 → 重索引生效；删除文档 → 索引清理
    svc.update_text_document(kb.id, doc_a.id, content="知识库现在只有一句话：本周四发布新版。")
    await _index([(kb.id, doc_a.id)])
    again = next(r for r in svc.list_documents(kb.id) if r.id == doc_a.id)
    assert again.status == "ready" and again.chunk_count == 1
    hits_after = idx.search(q_rel, k=3)
    assert not any(h.doc_id == doc_a.id for h in hits_after if "向量" in h.text), "旧内容未清出索引"
    print("[ok] 编辑重索引: chunk_count=1，旧向量已替换")

    svc.delete_document(kb.id, doc_a.id)
    rows_after = svc.list_documents(kb.id)
    assert all(r.id != doc_a.id for r in rows_after), "文档A未删除"
    assert svc.get_base(kb.id).doc_count == 1
    hits_after_del = idx.search(q_rel, k=3)
    assert not any(h.doc_id == doc_a.id for h in hits_after_del), "文档A的 chunk 未从索引清除"
    print(f"[ok] 删除清理: 行/文件/索引均已移除（剩余命中均属 doc_b: {[h.doc_id for h in hits_after_del]}）")

    # 5) 清理：删除整个知识库
    svc.delete_base(kb.id)
    print(f"[ok] 清理: 知识库 {kb.id} 已删除（含 docs 与 index.sqlite）")
    print("[ok] 验证全部通过 —— 存储层/索引/状态机链路正常")


if __name__ == "__main__":
    asyncio.run(main())
