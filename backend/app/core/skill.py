"""core/skill.py · 技能贡献（对齐 Harness SkillSummary/Definition：摘要常驻、正文按需）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SkillContribution:
    name: str
    description: str
    when_to_use: str = ""
    body: str = ""


@dataclass
class SkillDefinition(SkillContribution):
    """完整定义（ctx.skills.get() 返回）：目录只给 name+description，正文按需加载。"""
