"""专家（Expert）：加载与 system prompt 组装顺序。"""

from __future__ import annotations

from pathlib import Path

from app.domain.experts.expert import assemble_system_prompt, load_expert

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERTS_DIR = REPO_ROOT / "experts"


def test_load_default_expert():
    e = load_expert(EXPERTS_DIR, "nuomi")
    assert e.name == "nuomi"
    assert e.display_name == "糯米"
    assert e.default is True
    for key in ("IDENTITY", "SOUL", "AGENTS", "USER"):
        assert e.sections.get(key), f"缺少 {key}.md"
    assert "小猫" in e.sections["SOUL"]


def test_list_experts():
    from app.domain.experts.expert import list_experts

    names = list_experts(EXPERTS_DIR)
    assert "nuomi" in names


def test_assemble_order_rules_first():
    e = load_expert(EXPERTS_DIR, "nuomi")
    prompt = assemble_system_prompt(
        e,
        instructions=["当用户询问时间时必须调用 get_current_time 工具"],
        memory_facts=[],
    )
    # 规则在最前（本地 2B 实测依赖）
    assert prompt.index("工具使用规则") < prompt.index("你是谁")
    assert "get_current_time" in prompt


def test_assemble_includes_memory_and_profile():
    e = load_expert(EXPERTS_DIR, "nuomi")
    from app.storage.memory import MemoryFact

    f = MemoryFact(id="x", content="用户喜欢美式咖啡", category="preference")
    prompt = assemble_system_prompt(e, [], memory_facts=[f])
    assert "美式咖啡" in prompt
    assert "用户档案" in prompt  # USER.md 注入
    assert "嘉兴" in prompt
