"""知识库 API 端到端测试（FastAPI TestClient，隔离数据根）。

覆盖：能力状态/启用开关、建库（含重名 409/超限）、上传→异步索引→就绪、
新建文本、预览、编辑重索引、重命名、下载、重索引、删除文档/删库、
不支持类型 400、图片 OCR 门禁 400、404 分支、未知模型 400。
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

MODEL = "BAAI/bge-small-zh-v1.5"


def _wait_ready(c: TestClient, kb_id: str, doc_id: str, timeout: float = 60.0) -> dict:
    """轮询文档直到 ready；failed 直接断言失败（带错误信息）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        docs = c.get(f"/api/knowledge-bases/{kb_id}/documents").json()
        row = next((d for d in docs if d["id"] == doc_id), None)
        if row is None:
            raise AssertionError(f"document {doc_id} missing from listing")
        if row["status"] == "ready":
            return row
        if row["status"] == "failed":
            raise AssertionError(f"index failed: {row.get('error_message')}")
        time.sleep(0.3)
    raise AssertionError(f"timeout waiting for document {doc_id} to index")


# —— 能力 / 模型 ——


def test_capability(client: TestClient) -> None:
    r = client.get("/api/knowledge/capability")
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == MODEL
    assert body["enabled"] is False  # 默认关闭
    assert body["downloaded"] is True  # symlink 复用真实模型缓存
    assert body["max_bases"] == 20
    assert body["ocr_enabled"] is False  # OCR 后置


def test_feature_enable(client: TestClient) -> None:
    r = client.put("/api/knowledge/feature", json={"enabled": True, "model": MODEL})
    assert r.status_code == 200, r.text
    assert r.json()["enabled"] is True
    assert r.json()["model"] == MODEL
    # 恢复默认（避免影响后续用例的默认注入语义）
    client.put("/api/knowledge/feature", json={"enabled": False})


def test_feature_unknown_model(client: TestClient) -> None:
    r = client.put("/api/knowledge/feature", json={"enabled": True, "model": "not/a-model"})
    assert r.status_code == 400


def test_onnx_delete_unknown_model(client: TestClient) -> None:
    r = client.delete("/api/knowledge/onnx-model", params={"model": "not/a-model"})
    assert r.status_code == 400


# —— 建库 ——


def test_create_base_and_duplicate(client: TestClient) -> None:
    body = {"name": "api-test-bases", "description": "创建/重复名"}
    r1 = client.post("/api/knowledge-bases", json=body)
    assert r1.status_code == 200, r1.text
    kb = r1.json()
    assert kb["name"] == "api-test-bases"
    assert kb["doc_count"] == 0
    r2 = client.post("/api/knowledge-bases", json=body)
    assert r2.status_code == 409  # 同名冲突


def test_patch_base_fields(client: TestClient) -> None:
    """PATCH 支持 name/description/icon_name/max_documents（无 default_open 一说）。"""
    kb = client.post("/api/knowledge-bases", json={"name": "api-test-open"}).json()
    r = client.patch(
        f"/api/knowledge-bases/{kb['id']}",
        json={"description": "改了描述", "max_documents": 50},
    )
    assert r.status_code == 200
    assert r.json()["description"] == "改了描述"
    assert r.json()["max_documents"] == 50
    assert "default_open" not in r.json()


# —— 文档全链路 ——


def test_document_lifecycle(client: TestClient) -> None:
    kb = client.post("/api/knowledge-bases", json={"name": "api-test-lifecycle"}).json()
    kb_id = kb["id"]

    # 1. 上传 markdown → pending → ready
    md = "# Nuomi Knowledge\n\n本地知识库使用 fastembed 与 SQLite 向量索引。\n\n嵌入模型 bge-small-zh-v1.5。".encode()
    r = client.post(
        f"/api/knowledge-bases/{kb_id}/documents",
        files={"file": ("docs/api.md", md, "text/markdown")},
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["status"] == "pending"
    row = _wait_ready(client, kb_id, doc["id"])
    assert row["chunk_count"] >= 1
    assert row["content_type"] == "text/markdown"

    # 2. 文件夹自动出现（docs/）
    folders = [d for d in client.get(f"/api/knowledge-bases/{kb_id}/documents").json() if d["is_dir"]]
    assert any(f["path"] == "docs" for f in folders)

    # 3. 新建文本 → 索引
    r = client.post(
        f"/api/knowledge-bases/{kb_id}/documents/text",
        json={"name": "note.txt", "content": "随手记录：RAG 上下文预算 6000 字符。"},
    )
    assert r.status_code == 200, r.text
    note = r.json()
    _wait_ready(client, kb_id, note["id"])

    # 4. 预览（提取文本）
    r = client.get(f"/api/knowledge-bases/{kb_id}/documents/{doc['id']}/preview")
    assert r.status_code == 200
    assert "Nuomi Knowledge" in r.json()["text"]

    # 5. 下载原文件
    r = client.get(f"/api/knowledge-bases/{kb_id}/documents/{doc['id']}/file")
    assert r.status_code == 200
    assert r.content == md

    # 6. 读/写文本内容 → 重索引生效
    r = client.get(f"/api/knowledge-bases/{kb_id}/documents/{note['id']}/content")
    assert r.status_code == 200 and "RAG" in r.json()["text"]
    r = client.put(
        f"/api/knowledge-bases/{kb_id}/documents/{note['id']}/content",
        json={"content": "更新后的笔记内容，重新索引验证。"},
    )
    assert r.status_code == 200
    _wait_ready(client, kb_id, note["id"])
    r = client.get(f"/api/knowledge-bases/{kb_id}/documents/{note['id']}/content")
    assert "更新后的笔记内容" in r.json()["text"]

    # 7. 重命名 → 下载接口跟随新文件名
    r = client.post(
        f"/api/knowledge-bases/{kb_id}/documents/{doc['id']}/rename",
        json={"new_name": "api-renamed.md"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["filename"] == "api-renamed.md"
    r = client.get(f"/api/knowledge-bases/{kb_id}/documents/{doc['id']}/file")
    assert r.status_code == 200 and "api-renamed.md" in r.headers["content-disposition"]

    # 8. 单文档重索引
    r = client.post(f"/api/knowledge-bases/{kb_id}/documents/{doc['id']}/reindex")
    assert r.status_code == 200
    _wait_ready(client, kb_id, doc["id"])

    # 9. 删除文档 → 404
    assert client.delete(f"/api/knowledge-bases/{kb_id}/documents/{doc['id']}").status_code == 200
    assert client.get(f"/api/knowledge-bases/{kb_id}/documents/{doc['id']}/preview").status_code == 404

    # 10. 删库 → 404
    assert client.delete(f"/api/knowledge-bases/{kb_id}").status_code == 200
    assert client.get(f"/api/knowledge-bases/{kb_id}").status_code == 404


# —— 错误分支 ——


def test_unsupported_type_rejected(client: TestClient) -> None:
    kb = client.post("/api/knowledge-bases", json={"name": "api-test-errors"}).json()
    r = client.post(
        f"/api/knowledge-bases/{kb['id']}/documents",
        files={"file": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
    )
    assert r.status_code == 400  # 不支持的类型


def test_image_rejected_without_ocr(client: TestClient) -> None:
    kb = client.post("/api/knowledge-bases", json={"name": "api-test-ocr"}).json()
    r = client.post(
        f"/api/knowledge-bases/{kb['id']}/documents",
        files={"file": ("scan.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert r.status_code == 400
    assert "OCR" in r.json()["detail"]  # OCR 门禁


def test_unknown_kb_or_doc(client: TestClient) -> None:
    assert client.get("/api/knowledge-bases/nope").status_code == 404
    assert client.get("/api/knowledge-bases/nope/documents").status_code == 404
    assert (
        client.get("/api/knowledge-bases/nope/documents/x/preview").status_code == 404
    )


def test_max_documents_enforced(client: TestClient) -> None:
    kb = client.post(
        "/api/knowledge-bases", json={"name": "api-test-limit", "max_documents": 1}
    ).json()
    ok = client.post(
        f"/api/knowledge-bases/{kb['id']}/documents",
        files={"file": ("a.md", b"# a", "text/markdown")},
    )
    assert ok.status_code == 200
    over = client.post(
        f"/api/knowledge-bases/{kb['id']}/documents",
        files={"file": ("b.md", b"# b", "text/markdown")},
    )
    assert over.status_code == 400  # 每库上限


def test_delete_base_cascades(client: TestClient) -> None:
    """删库级联：knowledge_documents 行全清 + 目录文件删除 + 再访问 404。"""
    kb = client.post("/api/knowledge-bases", json={"name": "api-test-cascade"}).json()
    kb_id = kb["id"]
    md = "# 级联\n\n删除时要连文档记录一起清掉。".encode()
    r = client.post(
        f"/api/knowledge-bases/{kb_id}/documents",
        files={"file": ("docs/cascade.md", md, "text/markdown")},
    )
    assert r.status_code == 200
    _wait_ready(client, kb_id, r.json()["id"])

    from app.infra.knowledge.files import knowledge_base_dir

    kb_dir = knowledge_base_dir(kb_id)
    assert kb_dir.is_dir()  # 删除前目录存在（docs + index.sqlite）
    assert client.delete(f"/api/knowledge-bases/{kb_id}").status_code == 200

    # 文档行级联删除
    from app.storage import db

    with db.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM knowledge_documents WHERE kb_id = ?", (kb_id,)
        ).fetchone()
    assert int(row["c"]) == 0
    # 目录文件删除
    assert not kb_dir.exists()
    assert client.get(f"/api/knowledge-bases/{kb_id}").status_code == 404


def test_base_enable_disable(client: TestClient) -> None:
    """库级启停（对齐插件）：PATCH enabled → GET 反映 → 禁用库显式指定 400。"""
    kb = client.post("/api/knowledge-bases", json={"name": "api-test-toggle"}).json()
    kb_id = kb["id"]
    assert kb["enabled"] is True

    r = client.patch(f"/api/knowledge-bases/{kb_id}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert client.get(f"/api/knowledge-bases/{kb_id}").json()["enabled"] is False

    # 对话显式指定已停用库 → 400（对齐技能白名单「未启用」语义）
    agent = client.get("/api/agents").json()[0]
    aid = agent["agent_id"]
    r = client.post(
        f"/api/agents/{aid}/chat",
        json={"messages": "hi", "thread_id": "kb-disabled-1", "knowledge_base_ids": [kb_id]},
    )
    assert r.status_code == 400
    assert "已停用" in r.json()["detail"]

    # 重新启用 → 可再指定（模型不存在时 400 也行——重点是不再报「已停用」）
    assert client.patch(f"/api/knowledge-bases/{kb_id}", json={"enabled": True}).status_code == 200
    r = client.post(
        f"/api/agents/{aid}/chat",
        json={"messages": "hi", "thread_id": "kb-enabled-1", "knowledge_base_ids": [kb_id]},
    )
    assert r.status_code != 400
    assert "已停用" not in r.text
