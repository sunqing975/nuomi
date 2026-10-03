"""NuomiMiddleware 端到端：每轮注入人设+记忆；长对话自动摘要（模型输入有界）。"""

from __future__ import annotations

import re
from pathlib import Path

from app.main import build_app
from fastapi.testclient import TestClient

from .fake_llm import FakeChatModel

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_app(tmp_path, max_msgs: int = 6, keep_recent: int | None = None):
    return build_app(
        llm=FakeChatModel(),
        db_path=str(tmp_path / "test.sqlite"),
        plugins_dir=str(REPO_ROOT / "plugins"),
        memory_file=str(tmp_path / "mem" / "facts.json"),
        summarize_max_messages=max_msgs,
        summarize_keep_recent=keep_recent,
    )


def _spy_model(monkeypatch):
    """包一层 _astream（class 级，覆盖 bind_tools 复制出的实例），记录模型输入。"""
    captured: list[list[tuple[str, str]]] = []
    orig = FakeChatModel._astream

    async def wrapped(self, messages, stop=None, **kw):
        captured.append([(m.type, str(m.content)) for m in messages])
        async for ch in orig(self, messages, stop=stop, **kw):
            yield ch

    monkeypatch.setattr(FakeChatModel, "_astream", wrapped)
    return captured


def test_memory_facts_loaded_and_searchable(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/plugins/team/toggle")  # 单 Agent 测试：关闭团队路由
        app.state.memory.add("用户喜欢美式咖啡", category="preference")
        assert app.state.memory.search("咖啡")[0].content == "用户喜欢美式咖啡"
        body = client.get("/health").json()
        assert body["memory_facts"] == 1
        assert body["partner"] == "糯米"


def test_middleware_injects_persona_prompt(tmp_path, monkeypatch):
    captured = _spy_model(monkeypatch)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/plugins/team/toggle")  # 单 Agent 测试：关闭团队路由
        r = client.post("/api/chat", json={"message": "你好呀"})
        assert r.status_code == 200
        # 模型输入第一个消息应为注入的 system 提示，含人设与插件规则
        assert captured, "假模型应被调用"
        sys_msgs = [c for t, c in captured[0] if t == "system"]
        assert sys_msgs and "糯米" in sys_msgs[0], "应注入含人设的 system 提示"
        assert "工具使用规则" in sys_msgs[0], "插件规则应前置"


def test_memory_facts_injected_from_store(tmp_path, monkeypatch):
    captured = _spy_model(monkeypatch)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/plugins/team/toggle")  # 单 Agent 测试：关闭团队路由
        app.state.memory.add("用户喜欢美式咖啡", category="preference")
        client.post("/api/chat", json={"message": "我今天喝了咖啡"})
        sys_text = next(c for t, c in captured[0] if t == "system")
        assert "美式咖啡" in sys_text, "记忆事实应注入 system 提示"


def test_summarization_bounds_model_input(tmp_path, monkeypatch):
    captured = _spy_model(monkeypatch)
    app = _make_app(tmp_path, max_msgs=4, keep_recent=2)
    with TestClient(app) as client:
        client.post("/api/plugins/team/toggle")  # 单 Agent 测试：关闭团队路由
        r1 = client.post("/api/chat", json={"message": "第一轮"})
        tid = re.search(r'"thread_id": "([^"]+)"', r1.text).group(1)
        for i in range(2, 7):  # 再发 5 轮，历史远超阈值
            client.post("/api/chat", json={"message": f"第{i}轮", "thread_id": tid})

    # 过滤掉摘要内部调用（单条 human 的调用），只看发给 agent 模型的输入
    agent_calls = [s for s in captured if len(s) > 1]
    last = agent_calls[-1]
    assert len(last) <= 5, f"模型输入应有界，实际 {len(last)} 条"
    texts = [c for _, c in last]
    assert any("历史摘要" in t for t in texts), "压缩后模型输入应含历史摘要"
    assert any("第6轮" in t for t in texts), "最近一轮应保留原文"


def _last_system_text(captured) -> str:
    """最近一次含 system 的模型调用中的 system 文本（跳过 title 等单条调用）。"""
    for msgs in reversed(captured):
        syss = [c for t, c in msgs if t == "system"]
        if syss:
            return syss[0]
    return ""


def test_frozen_snapshot_unchanged_within_session(tmp_path, monkeypatch):
    """记忆 v2（Hermes 式）：冻结快照——同 thread 会话内不变，新 thread 反映新写入。"""
    captured = _spy_model(monkeypatch)
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/plugins/team/toggle")  # 单 Agent 测试
        app.state.memory.add("用户喜欢美式咖啡", category="preference")
        r1 = client.post("/api/chat", json={"message": "第一轮"})
        tid = re.search(r'"thread_id": "([^"]+)"', r1.text).group(1)
        sys1 = _last_system_text(captured)
        assert "美式咖啡" in sys1, "快照应注入既有记忆"
        assert "记忆快照" in sys1, "system 提示应含记忆快照块"

        # 会话内新写入：快照冻结，不在本会话出现（下个会话才反映）
        app.state.memory.add("用户喜欢喝乌龙茶")
        client.post("/api/chat", json={"message": "第二轮", "thread_id": tid})
        sys2 = _last_system_text(captured)
        assert sys2 == sys1, "同 thread 会话内快照应冻结不变"
        assert "乌龙茶" not in sys2, "会话内新写入不应出现在当前会话快照"

        # 新 thread：快照反映新写入
        client.post("/api/chat", json={"message": "第三轮"})
        sys3 = _last_system_text(captured)
        assert "乌龙茶" in sys3 and "美式咖啡" in sys3
