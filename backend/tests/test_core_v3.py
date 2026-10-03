"""V3 core 内核：5 种事件分发 / fiber 状态机 / 依赖驱动 / composition patch。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from app.core import (
    EventBus,
    Fiber,
    FiberState,
    Registry,
    Scope,
    resolve_profile,
)


def _app():
    return SimpleNamespace(state=SimpleNamespace(settings={}))


# ---------- 事件 5 种分发 ----------


def test_emit_broadcast():
    bus = EventBus()
    got = []
    bus.on("a/x", lambda v: got.append(v))
    bus.on("a/x", lambda v: got.append(v * 2))
    bus.emit("a/x", v=3)
    assert got == [3, 6]


def test_emit_error_isolated():
    bus = EventBus()
    got = []

    def boom(**kw):
        raise RuntimeError("boom")

    bus.on("a/x", boom)
    bus.on("a/x", lambda v: got.append(v))
    bus.emit("a/x", v=1)
    assert got == [1]


def test_parallel():
    bus = EventBus()

    async def slow(**kw):
        await asyncio.sleep(0.01)
        return kw["v"] + 1

    bus.on("a/x", lambda v: v)  # 同步
    bus.on("a/x", slow)  # 异步
    results = asyncio.run(bus.parallel("a/x", v=1))
    assert set(results) == {1, 2}


def test_serial_first_wins():
    bus = EventBus()
    calls = []
    bus.on("a/x", lambda v: calls.append("h1") or None)
    bus.on("a/x", lambda v: calls.append("h2") or "WIN")
    bus.on("a/x", lambda v: calls.append("h3") or "LOSE")
    assert asyncio.run(bus.serial("a/x", v=1)) == "WIN"
    assert calls == ["h1", "h2"]  # 短路：h3 不执行


def test_bail_sync():
    bus = EventBus()
    bus.on("a/x", lambda v: None)
    bus.on("a/x", lambda v: 42)
    assert bus.bail("a/x", v=0) == 42


def test_waterfall_transform_and_shortcircuit():
    bus = EventBus()

    # 监听器1：转换下游结果（大写）
    async def upper(v, nxt):
        return (await nxt()).upper()

    # 监听器2：含 blocked 时短路（不调 next）
    async def guard(v, nxt):
        if "blocked" in v:
            return "** blocked **"
        return await nxt()

    bus.on("a/x", upper)
    bus.on("a/x", guard)

    async def run():
        r1 = await bus.waterfall("a/x", "hello", lambda: "hello")
        r2 = await bus.waterfall("a/x", "blocked words", lambda: "blocked words")
        return r1, r2

    assert asyncio.run(run()) == ("HELLO", "** BLOCKED **")  # upper 也会包装短路值（Harness 语义）


# ---------- Fiber 状态机 + 依赖驱动 ----------


def _write_plugin(root: Path, name: str, body: str):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    (d / "hook.py").write_text(body, encoding="utf-8")
    return d


def test_fiber_pending_until_service_ready(tmp_path):
    app = _app()
    bus = EventBus()
    scope = Scope()
    reg = Registry(app, bus, scope)

    # 插件 B 依赖服务 'greeter'（未注册）→ PENDING
    d = _write_plugin(tmp_path, "b", 'inject = ["greeter"]\ndef apply(ctx): pass\n')
    fb = Fiber("b", "b", d, {}, app, bus, scope)
    reg.add(fb)
    assert fb.load() == FiberState.PENDING
    assert fb.waiting_on == ["greeter"]

    # 服务出现 → reconcile 后 ACTIVE
    scope.register("greeter", object())
    reg.reconcile()
    assert fb.state == FiberState.ACTIVE


def test_fiber_dependency_disappears_unloads(tmp_path):
    app = _app()
    bus = EventBus()
    scope = Scope()
    reg = Registry(app, bus, scope)

    # 提供方 A 注册服务 greeter；消费方 B inject greeter
    a_dir = _write_plugin(tmp_path, "a", "def apply(ctx): ctx.provide('greeter', 'hi')\n")
    b_dir = _write_plugin(tmp_path, "b", 'inject = ["greeter"]\ndef apply(ctx): pass\n')
    fa = Fiber("a", "a", a_dir, {}, app, bus, scope)
    fb = Fiber("b", "b", b_dir, {}, app, bus, scope)
    reg.add(fa)
    reg.add(fb)
    fa.load()
    fb.load()
    assert fb.state == FiberState.ACTIVE
    # A 卸载 → greeter 消失 → reconcile 把 B 打回 PENDING
    fa.dispose()
    reg.reconcile()
    assert fb.state == FiberState.PENDING


def test_fiber_failed_on_apply_error(tmp_path):
    app = _app()
    bus = EventBus()
    scope = Scope()
    reg = Registry(app, bus, scope)
    d = _write_plugin(tmp_path, "bad", "def apply(ctx): raise RuntimeError('boom')\n")
    fb = Fiber("bad", "bad", d, {}, app, bus, scope)
    reg.add(fb)
    assert fb.load() == FiberState.FAILED
    assert "boom" in fb.error


def test_fiber_dispose_cleanup(tmp_path):
    app = _app()
    bus = EventBus()
    scope = Scope()
    reg = Registry(app, bus, scope)
    d = _write_plugin(
        tmp_path,
        "c",
        "def apply(ctx):\n    fired=[]\n    ctx.on('ev', lambda **kw: fired.append(1))\n    ctx.effect(lambda: fired.append('disposed'))\n    ctx.app.state.last=fired\n",
    )
    fb = Fiber("c", "c", d, {}, app, bus, scope)
    reg.add(fb)
    fb.load()
    assert fb.state == FiberState.ACTIVE
    fb.dispose()
    assert fb.state == FiberState.DISPOSED
    bus.emit("ev")  # 监听器已随 dispose 移除


# ---------- Composition patch ----------


def test_resolve_profile_layer_patch():
    profile = {
        "layers": [
            {
                "id": "base",
                "plugins": [
                    {"id": "cap-a", "plugin": "plugin-a", "config": {"k": "v1"}},
                    {"id": "mood", "plugin": "mood", "config": {}},
                ],
            },
            {
                "id": "user",
                "plugins": [
                    {"id": "cap-a", "plugin": "plugin-b", "config": {"k": "v2"}},
                    {"id": "mood", "disabled": True},
                ],
            },
        ]
    }
    entries = {e.id: e for e in resolve_profile(profile)}
    assert entries["cap-a"].plugin == "plugin-b"  # patch 替换提供方
    assert entries["cap-a"].config == {"k": "v2"}  # config 整体替换
    assert entries["mood"].disabled is True  # disabled 覆盖


def test_profile_entry_defaults():
    entries = resolve_profile({"layers": [{"plugins": [{"id": "x", "plugin": "x"}]}]})
    assert entries[0].config == {} and entries[0].disabled is False
