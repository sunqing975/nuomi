"""对话 SSE 的终止契约与阻塞隔离测试。

锁两件事：
1. **流中途异常必须补发 error 终止帧**——前端只解析 SSE，看不到 done/error 就
   会一直转圈（原实现只有 try/finally，异常直接把流截断）。
2. **长阻塞操作不能占住事件循环**——git 导入 / FBX 转换 / 知识库文件 IO 都走
   ``asyncio.to_thread``；在慢操作进行中 /api/health 必须照常秒回。
"""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient


def _first_agent(client: TestClient) -> str:
    return client.get("/api/agents").json()[0]["agent_id"]


def test_stream_failure_emits_error_frame(client: TestClient, monkeypatch) -> None:
    """流中途抛异常 → 客户端收到 type=error 帧并正常收流（不是静默截断）。"""
    import app.transport.chat_api as api_mod

    async def _boom(*_args, **_kwargs):
        yield 'data: {"type": "token", "content": "部分输出"}\n\n'
        raise RuntimeError("模拟流中途爆炸")

    monkeypatch.setattr(api_mod, "stream_octop_sse", _boom)
    aid = _first_agent(client)
    r = client.post(f"/api/agents/{aid}/chat", json={"messages": "hi", "thread_id": "boom-1"})

    assert r.status_code == 200
    assert "部分输出" in r.text  # 已产出的内容保留
    assert '"type": "error"' in r.text  # 明确的终止信号
    assert "模拟流中途爆炸" in r.text
    assert r.text.rstrip().endswith("}")  # 流已收尾，没有半截帧


def test_stream_error_frame_keeps_thread_id(client: TestClient, monkeypatch) -> None:
    import app.transport.chat_api as api_mod

    async def _boom(*_args, **_kwargs):
        raise ValueError("x")
        yield  # pragma: no cover  (让它成为 async generator)

    monkeypatch.setattr(api_mod, "stream_octop_sse", _boom)
    aid = _first_agent(client)
    r = client.post(f"/api/agents/{aid}/chat", json={"messages": "hi", "thread_id": "boom-2"})
    assert '"thread_id": "boom-2"' in r.text


def test_friendly_stream_error_maps_recursion_limit() -> None:
    """撞 LangGraph 递归上限 → 中文可执行提示；其它异常原样透出（便于排查）。"""
    from app.infra.harness.chat import friendly_stream_error

    class GraphRecursionError(RuntimeError):
        """模拟 langgraph.errors.GraphRecursionError（按类名识别，不引入依赖）。"""

    raw = "Recursion limit of 60 reached without hitting a stop condition."
    mapped = friendly_stream_error(GraphRecursionError(raw))
    assert "步数达到上限" in mapped
    assert "Recursion limit" not in mapped

    # 类名不同但消息特征在（例如被包装过）同样映射
    assert "步数达到上限" in friendly_stream_error(RuntimeError(raw))
    # 未知异常不许被吞成通用文案
    assert friendly_stream_error(ValueError("别的问题")) == "别的问题"
    assert friendly_stream_error(ValueError()) == "ValueError"


def test_recursion_limit_error_frame_is_chinese(client: TestClient, monkeypatch) -> None:
    """端到端：撞递归上限时客户端收到的是中文提示，而不是英文异常原文。"""
    import app.transport.chat_api as api_mod

    class GraphRecursionError(RuntimeError):
        pass

    async def _boom(*_args, **_kwargs):
        raise GraphRecursionError("Recursion limit of 60 reached without hitting a stop condition.")
        yield  # pragma: no cover  (让它成为 async generator)

    monkeypatch.setattr(api_mod, "stream_octop_sse", _boom)
    aid = _first_agent(client)
    r = client.post(f"/api/agents/{aid}/chat", json={"messages": "hi", "thread_id": "boom-3"})

    assert r.status_code == 200
    assert '"type": "error"' in r.text
    assert "步数达到上限" in r.text
    assert "Recursion limit" not in r.text
    assert '"thread_id": "boom-3"' in r.text


def test_slow_endpoint_does_not_block_health(client: TestClient, monkeypatch) -> None:
    """慢操作（git 导入）在别的线程跑：期间 /api/health 必须立即返回。

    这是 ``asyncio.to_thread`` 的行为断言——如果哪天改回同步直调，这里会超时失败。
    """
    import app.infra.importers as importer

    started = threading.Event()

    def _slow_import(url: str):
        started.set()
        time.sleep(1.5)  # 模拟 git clone / FBX 转换这类秒级阻塞
        raise ValueError("测试用：克隆失败")

    monkeypatch.setattr(importer, "import_plugin_git", _slow_import)
    errors: list = []

    def _call() -> None:
        try:
            client.post("/api/plugins/import-git", json={"url": "https://example.com/x.git"})
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    worker = threading.Thread(target=_call)
    worker.start()
    assert started.wait(timeout=5), "导入没有开始"

    # 阻塞操作进行中：健康检查必须快（远小于 1.5s）
    t0 = time.perf_counter()
    assert client.get("/api/health").status_code == 200
    elapsed = time.perf_counter() - t0
    worker.join(timeout=10)

    assert elapsed < 0.8, f"慢操作占住了事件循环：health 用了 {elapsed:.2f}s"
    assert not errors
