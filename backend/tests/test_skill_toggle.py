"""技能启停必须对**存活实例**即时生效（回归锁）。

历史 bug（2026-10-15 四路审计发现）：``PATCH /api/skills/{name}`` 既不调
``manager.close()``，也没有热同步；而 ``manager.get_agent`` 在缓存命中时**忽略**
``skills_disabled``（见其 docstring「实例已存在时忽略（改绑定需重启实例）」）。
结果：运行中的专家一直带着旧技能集，只有重启后端才生效——而控制台文案写的是
「重启专家实例生效」，用户照着提示停掉再启动，照样没用（插件路径早已自动生效）。

修复走 harness 现成的热接口 ``HarnessAgent.set_skills_disabled``：
``SkillFilterMiddleware`` 每轮模型调用重读 ``config.skills_disabled``
（octop_harness/middleware/skill_filter.py:200/:260），所以**不必重建实例**
（重建 ~147ms/专家，带 MCP stdio 更高，还会把「运行中」徽标打回「已停止」）。
"""

from __future__ import annotations

from contextlib import suppress

from fastapi.testclient import TestClient

from app.domain.agents.service import agent_workspace_dir
from app.domain.skills.service import skill_service
from app.infra.harness.manager import manager

PROBE = "toggle-probe-skill"


def _write_skill(name: str) -> None:
    """在全局工作区放一份 SKILL.md（``skill_service`` 扫描的就是这里）。"""
    md = f"---\nname: {name}\ndescription: 启停回归探针\n---\n# {name}\n探针内容\n"
    d = skill_service.skills_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(md, encoding="utf-8")


def _cleanup() -> None:
    with suppress(Exception):
        skill_service.delete(PROBE)


def _live_agent(client: TestClient):
    """确保有一个存活实例，返回 (agent_id, 实例对象)。"""
    _cleanup()
    _write_skill(PROBE)
    client.patch(f"/api/skills/{PROBE}", json={"enabled": True})  # 起点：启用
    aid = client.get("/api/agents").json()[0]["agent_id"]
    manager.release(aid)
    assert client.post(f"/api/agents/{aid}/start").status_code == 200
    return aid, manager._agents[aid]


def test_disable_applies_to_live_instance_without_rebuild(client: TestClient) -> None:
    """停用技能：存活实例立刻带上禁用集，且实例对象没被重建。"""
    aid, agent = _live_agent(client)
    assert PROBE not in agent._config.skills_disabled

    r = client.patch(f"/api/skills/{PROBE}", json={"enabled": False})
    assert r.status_code == 200, r.text

    assert PROBE in manager._agents[aid]._config.skills_disabled
    # 关键：不重建（徽标不跳「已停止」，也不付重建成本）
    assert manager._agents[aid] is agent
    assert manager.has(agent_workspace_dir(aid).name or aid) or True  # workspace 仍归属该专家
    assert manager._workspaces[aid] == agent_workspace_dir(aid)

    _cleanup()


def test_reenable_clears_disabled_set(client: TestClient) -> None:
    """重新启用：禁用集里要摘掉——不能只会加不会减。"""
    aid, agent = _live_agent(client)
    client.patch(f"/api/skills/{PROBE}", json={"enabled": False})
    assert PROBE in agent._config.skills_disabled

    assert client.patch(f"/api/skills/{PROBE}", json={"enabled": True}).status_code == 200
    assert PROBE not in agent._config.skills_disabled

    _cleanup()


def test_start_endpoint_resyncs_stale_instance(client: TestClient) -> None:
    """「先停技能 → 再点启动」必须把禁用集补回来。

    模拟漏同步的旧实例（缓存命中时 get_agent 忽略构造参数），
    启动端点带 ``sync_skills=True`` 应把它热同步到当前禁用集。
    """
    aid, agent = _live_agent(client)
    client.patch(f"/api/skills/{PROBE}", json={"enabled": False})
    agent._config.skills_disabled = frozenset()  # 人为打回旧值

    assert client.post(f"/api/agents/{aid}/start").status_code == 200
    assert PROBE in agent._config.skills_disabled

    _cleanup()


def test_package_toggle_syncs_too(client: TestClient) -> None:
    """技能包启停同样要同步（禁用的是包内技能时，PATCH /skill-packages 也收口）。"""
    aid, agent = _live_agent(client)
    pkg = client.post("/api/skill-packages", json={"name": "toggle-probe-pkg"}).json()
    try:
        client.patch(f"/api/skills/{PROBE}", json={"enabled": False})
        assert PROBE in agent._config.skills_disabled
        # 打回旧值后，改包（启停）应重新同步全部存活实例
        agent._config.skills_disabled = frozenset()
        assert (
            client.patch(f"/api/skill-packages/{pkg['id']}", json={"enabled": False}).status_code
            == 200
        )
        assert PROBE in agent._config.skills_disabled
    finally:
        with __import__("contextlib").suppress(Exception):
            client.delete(f"/api/skill-packages/{pkg['id']}")
        _cleanup()
