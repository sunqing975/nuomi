"""知识库 RAG 存储 · 可插拔实现（Phase 2 核心之一）。

接口（KnowledgeStore）：add(content, category) / search(query, top_k) / count
实现：
  - ChromaStore   默认。Chroma + fastembed（BAAI/bge-small-zh-v1.5，512 维）。
                  级3资源按需：Chroma 客户端与 embedding 模型都在**首次调用**时才
                  初始化并缓存（进程单例），启动零开销；模型经 HF_ENDPOINT 镜像下载。
  - LexicalStore  确定性 CJK 二元组词法实现（离线、零依赖），用于测试与无网兜底。

"换 RAG 方案 = 换插件/配置"：入口处按 store_type 工厂分发，上层（工具层）只面对接口。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

# 模型下载走国内镜像（实测直连 huggingface 超时；fastembed 读 HF_ENDPOINT）
from ..config import settings

_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
_BIGRAM_RE = re.compile(r"[\u4e00-\u9fff]{2}")

_embedder = None  # 级3：首次调用时初始化并缓存


def _get_embedder():
    global _embedder
    if _embedder is None:
        os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(model_name=_MODEL_NAME)
    return _embedder


class ChromaStore:
    """向量库实现：Chroma（PersistentClient）+ fastembed。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._client = None
        self._col = None

    # 级3：首次调用才打开向量库
    def _collection(self):
        if self._col is None:
            import chromadb

            self._client = chromadb.PersistentClient(path=str(self.root / "chroma"))
            self._col = self._client.get_or_create_collection(
                "knowledge", metadata={"hnsw:space": "cosine"}
            )
        return self._col

    @staticmethod
    def _chunk_id(content: str) -> str:
        return hashlib.sha1(content.encode("utf-8")).hexdigest()[:16]

    def add(self, content: str, category: str = "fact") -> None:
        content = content.strip()
        if not content:
            return
        emb = list(_get_embedder().embed([content]))[0]
        self._collection().upsert(
            ids=[self._chunk_id(content)],
            documents=[content],
            embeddings=[emb.tolist()],
            metadatas=[{"category": category, "ts": time.time()}],
        )

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        if not self._collection().count():
            return []
        qv = list(_get_embedder().query_embed(query))[0]
        res = self._collection().query(
            query_embeddings=[qv.tolist()], n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        out = []
        for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0]
        ):
            out.append(
                {"content": doc, "category": meta.get("category", ""), "score": 1 - dist}
            )
        return out

    def count(self) -> int:
        return self._collection().count()


class LexicalStore:
    """确定性词法实现：CJK 二元组打分 + JSON 持久化（离线/测试/兜底）。"""

    def __init__(self, root: str | Path):
        self.path = Path(root) / "facts.json"
        self.items: list[dict] = []
        if self.path.exists():
            try:
                self.items = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.items = []

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    @staticmethod
    def _bigrams(text: str) -> set[str]:
        chars = re.sub(r"\s+", "", text)
        grams = {chars[i : i + 2] for i in range(len(chars) - 1)} if chars else set()
        for w in re.findall(r"[a-zA-Z0-9_]{2,}", text):
            grams.add(w.lower())
        return grams

    def add(self, content: str, category: str = "fact") -> None:
        content = content.strip()
        if not content:
            return
        for it in self.items:
            if it["content"] == content or content in it["content"]:
                return
        self.items.append({"content": content, "category": category, "ts": time.time()})
        self._save()

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        qg = self._bigrams(query)
        if not qg:
            return []
        scored = []
        for it in self.items:
            fg = self._bigrams(it["content"])
            overlap = len(qg & fg)
            if query in it["content"]:
                overlap += 2
            if overlap > 0:
                scored.append({"content": it["content"], "category": it["category"], "score": overlap})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self.items)


def build_knowledge_store(store_type: str, root: str | Path) -> object:
    """工厂：换 RAG 方案 = 换 store_type（chroma / lexical），上层接口不变。"""
    if store_type == "lexical":
        return LexicalStore(root)
    return ChromaStore(root)


# ---------- 应用内单例（由 lifespan 注入；知识插件通过 get_store 读取） ----------
_store: object | None = None


def set_store(store: object):
    global _store
    _store = store


def get_store():
    if _store is None:
        raise RuntimeError("知识库尚未初始化（需在 lifespan 中 set_store）")
    return _store
