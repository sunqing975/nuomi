"""伙伴人设：加载与 system prompt 组装顺序。"""
from __future__ import annotations

from pathlib import Path

from app.partner import assemble_system_prompt, load_partner

REPO_ROOT = Path(__file__).resolve().parents[2]
PARTNERS_DIR = REPO_ROOT / "partners"


def test_load_nuomi_partner():
    p = load_partner(PARTNERS_DIR, "nuomi")
    assert p.name == "nuomi"
    assert p.display_name == "糯米"
    for key in ("IDENTITY", "SOUL", "AGENTS", "USER"):
        assert p.sections.get(key), f"缺少 {key}.md"
    assert "小猫" in p.sections["SOUL"]


def test_list_partners():
    from app.partner import list_partners

    names = list_partners(PARTNERS_DIR)
    assert "nuomi" in names


def test_assemble_order_rules_first():
    p = load_partner(PARTNERS_DIR, "nuomi")
    prompt = assemble_system_prompt(
        p,
        instructions=["当用户询问时间时必须调用 get_current_time 工具"],
        memory_facts=[],
    )
    # 规则在最前（本地 2B 实测依赖）
    assert prompt.index("工具使用规则") < prompt.index("你是谁")
    assert "get_current_time" in prompt


def test_assemble_includes_memory_and_profile():
    p = load_partner(PARTNERS_DIR, "nuomi")
    from app.memory import MemoryFact

    f = MemoryFact(id="x", content="用户喜欢美式咖啡", category="preference")
    prompt = assemble_system_prompt(p, [], memory_facts=[f])
    assert "美式咖啡" in prompt
    assert "用户档案" in prompt  # USER.md 注入
    assert "嘉兴" in prompt
