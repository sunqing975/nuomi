"""插件规范 v0.5（Harness 移植）· 事件总线 / PluginContext / mood / skill_doc / 技能目录。"""

from __future__ import annotations

from pathlib import Path

from app.infrastructure.engine.runtime import RESPONSE_DONE, EventBus, PluginContext
from app.main import build_app
from fastapi.testclient import TestClient

from .fake_llm import FakeChatModel

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_app(tmp_path):
    return build_app(
        llm=FakeChatModel(),
        db_path=str(tmp_path / "t.sqlite"),
        plugins_dir=str(REPO_ROOT / "plugins"),
        memory_file=str(tmp_path / "mem" / "nuomi" / "facts.json"),
        knowledge_store_type="lexical",
        knowledge_dir=str(tmp_path / "kb"),
    )


# --- EventBus / PluginContext ---


def test_event_bus_publish_subscribe(tmp_path):
    bus = EventBus()
    got = []
    bus.subscribe("e", lambda p: got.append(p))
    bus.publish("e", {"a": 1})
    assert got == [{"a": 1}]
    bus.publish("other", {})  # 无关事件不触发
    assert len(got) == 1


def test_event_bus_handler_error_isolated():
    bus = EventBus()
    calls = []

    def boom(_p):
        raise RuntimeError("boom")

    def ok(p):
        calls.append(p)

    bus.subscribe("e", boom)
    bus.subscribe("e", ok)
    bus.publish("e", {"x": 1})  # boom 不影响 ok
    assert calls == [{"x": 1}]


def test_plugin_context_provide_on_dispose(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        app.state.event_bus = EventBus()
        app.state.services = {}
        ctx = PluginContext(client.app)
        ctx.provide("svc", {"n": 1})
        assert app.state.services["svc"] == {"n": 1}
        fired = []
        ctx.on("ev", lambda p: fired.append(p))
        app.state.event_bus.publish("ev", {"k": 2})
        assert fired == [{"k": 2}]
        ctx.dispose()
        app.state.event_bus.publish("ev", {"k": 3})
        assert len(fired) == 1  # 卸载后不再收到


# --- mood 程序插件 ---


def test_mood_plugin_rules(tmp_path):
    import importlib.util
    import sys

    hook_path = REPO_ROOT / "backend" / "app" / "domain" / "behavior" / "mood" / "mood.py"
    spec = importlib.util.spec_from_file_location("nuomi_mood_hook", hook_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nuomi_mood_hook"] = mod
    spec.loader.exec_module(mod)
    analyze_emotion = mod.analyze_emotion

    assert analyze_emotion("太棒了！搞定！") == "excited"
    assert analyze_emotion("哈哈 真开心") == "happy"
    assert analyze_emotion("你觉得呢？") == "curious"
    assert analyze_emotion("哇 居然是这样！") == "surprised"
    assert analyze_emotion("") == "neutral"
    assert analyze_emotion("普通陈述句") == "neutral"


def test_mood_plugin_done_event_sets_emotion(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app):
        assert app.state.last_emotion == "neutral"
        # 直接发布 RESPONSE_DONE（等效于 chat 完成），mood 插件订阅后写入
        app.state.event_bus.publish(RESPONSE_DONE, {"reply": "哈哈 那你可找对人了"})
        assert app.state.last_emotion in ("happy", "proud")


def test_mood_plugin_toggle_stops_analysis(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        client.post("/api/plugins/mood/toggle")
        assert "mood" not in app.state.enabled_plugins
        app.state.event_bus.publish(RESPONSE_DONE, {"reply": "太棒了！！"})
        # 插件已卸载：不再更新（保持旧值或未变）
        assert app.state.last_emotion != "excited"


# --- skill_doc 工具（按需读 SKILL.md 正文） ---


def test_skill_doc_reads_body(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        tools = {t.name: t for t in app.state.tools}
        assert "skill_doc" in tools
        result = tools["skill_doc"].invoke({"name": "memory"})
        assert '<skill_content name="memory">' in result
        assert "memory_write" in result  # 正文含工具名
        # 未知技能 → 明确报错
        assert "未知技能" in tools["skill_doc"].invoke({"name": "nope"})
        # 技能独立概念：mood 不在技能区 → 未知技能（不再有"程序型"分支）
        assert "未知技能" in tools["skill_doc"].invoke({"name": "mood"})
        # 技能独立：停用 memory 插件不影响读技能正文（技能区全量可用）
        client.post("/api/plugins/memory/toggle")
        tools2 = {t.name: t for t in app.state.tools}
        assert "memory_write" in tools2["skill_doc"].invoke({"name": "memory"})


def test_skill_catalog_only_metadata(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        from app.infrastructure.engine.loader import collect_skill_catalog

        catalog = collect_skill_catalog(app.state.skills)
        assert "memory_write" not in catalog  # 正文不进常驻目录
        assert 'skill name="memory"' in catalog
        assert 'skill name="mood"' not in catalog  # 不在技能区
        # 技能独立：停用插件不影响技能目录（全量注入）
        client.post("/api/plugins/datetime/toggle")
        catalog2 = collect_skill_catalog(app.state.skills)
        assert 'skill name="datetime"' in catalog2


# --- 程序插件事件驱动（voice-input 设置随 toggle） ---


def test_voice_input_settings_event_driven(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        assert app.state.plugin_settings["voice_input"]["enabled"] is True
        client.post("/api/plugins/voice-input/toggle")
        assert app.state.plugin_settings["voice_input"]["enabled"] is False
        client.post("/api/plugins/voice-input/toggle")
        assert app.state.plugin_settings["voice_input"]["enabled"] is True
