"""Agent 实例领域单测：create/start/stop/update/delete + current_expert_name 解析。"""

from __future__ import annotations

import json

import pytest
from app.domain.agents.agent import (
    agents_path,
    create_agent,
    current_agent_id,
    current_expert_name,
    delete_agent,
    get_agent,
    list_agents,
    set_current,
    update_agent,
)


@pytest.fixture
def ag(tmp_path):
    return agents_path(tmp_path)


def test_create_and_list(ag, tmp_path):
    a = create_agent(ag, "nuomi", "测试助手", description="desc", icon_name="cat", color="#f59e0b")
    assert a.id == "agent-测试助手"
    assert a.expert == "nuomi"
    assert a.status == "stopped"
    assert get_agent(ag, a.id).display_name == "测试助手"
    assert len(list_agents(ag)) == 1
    # 重名自动加后缀
    a2 = create_agent(ag, "nuomi", "测试助手")
    assert a2.id == "agent-测试助手-2"


def test_lifecycle(ag):
    a = create_agent(ag, "nuomi", "小助手")
    set_current(ag, a.id)
    assert current_agent_id(ag) == a.id
    assert get_agent(ag, a.id).status == "running"
    set_current(ag, None)
    assert current_agent_id(ag) is None
    assert get_agent(ag, a.id).status == "stopped"


def test_update_and_delete(ag, tmp_path):
    a = create_agent(ag, "nuomi", "旧名")
    updated = update_agent(ag, a.id, display_name="新名", description="新描述")
    assert updated.display_name == "新名"
    assert updated.description == "新描述"
    assert delete_agent(ag, a.id) is True
    assert delete_agent(ag, a.id) is False
    assert list_agents(ag) == []


def test_current_expert_name(ag, tmp_path):
    # 无 agents → 默认
    assert current_expert_name(tmp_path, "nuomi") == "nuomi"
    a = create_agent(ag, "调研专家", "调研员")
    set_current(ag, a.id)
    assert current_expert_name(tmp_path, "nuomi") == "调研专家"
    # 旧版 experts.json 兼容
    delete_agent(ag, a.id)
    (tmp_path / "experts.json").write_text(json.dumps({"expert_name": "nuomi"}), encoding="utf-8")
    assert current_expert_name(tmp_path, "调研专家") == "nuomi"
