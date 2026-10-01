"""伙伴人设组装：partners/<name>/ 配置 → system prompt。

多伙伴设计 = 多目录；引擎和技能全复用（面试亮点："预置可爱/御姐伙伴只是加配置文件"）。
组装顺序（实测：小模型工具调用依赖规则前置）：
  1. 插件使用规则（最高优先级，来自各插件 system_instruction）
  2. 伙伴身份（IDENTITY / SOUL / AGENTS）
  3. 用户画像（USER.md，人工可编辑）
  4. 记忆事实（MemoryStore 检索/最近，每轮动态注入由中间件负责）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import REPO_ROOT


@dataclass
class Partner:
    name: str
    display_name: str
    description: str
    avatar: str
    dir: Path
    sections: dict[str, str] = field(default_factory=dict)  # IDENTITY/SOUL/AGENTS/USER

    @property
    def user_profile_lines(self) -> list[str]:
        return [l.strip("- ").strip() for l in self.sections.get("USER", "").splitlines() if l.strip()]


def load_partner(partners_dir: str | Path, name: str) -> Partner:
    root = Path(partners_dir)
    pdir = root / name
    meta_path = pdir / "partner.json"
    import json

    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    sections = {}
    for key in ("IDENTITY", "SOUL", "AGENTS", "USER"):
        f = pdir / f"{key}.md"
        if f.exists():
            sections[key] = f.read_text(encoding="utf-8").strip()

    return Partner(
        name=name,
        display_name=str(meta.get("display_name", name)),
        description=str(meta.get("description", "")),
        avatar=str(meta.get("avatar", "")),
        dir=pdir,
        sections=sections,
    )


def list_partners(partners_dir: str | Path) -> list[str]:
    root = Path(partners_dir)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "partner.json").exists())


def format_memory_facts(facts) -> str:
    """把记忆事实列表格式化为提示词片段。facts 元素需有 content/category/created_at。"""
    if not facts:
        return ""
    from datetime import datetime

    lines = []
    for f in facts:
        day = datetime.fromtimestamp(f.created_at).strftime("%m-%d")
        lines.append(f"- [{day}][{f.category}] {f.content}")
    return (
        "【你记得的关于用户的事】（长期记忆，下面每一条都来自真实记录，不是猜测）：\n"
        "当用户问起自己的事、或让你回忆说过的话/偏好/习惯时，必须优先从下面的记忆里找答案，"
        "并直接引用；只有在记忆里确实没有时才说不知道。\n"
        + "\n".join(lines)
    )


def assemble_system_prompt(
    partner: Partner,
    instructions: list[str],
    memory_facts: list | None = None,
    user_profile_extra: list[str] | None = None,
    skill_catalog: str | None = None,
) -> str:
    """组装完整 system prompt（不含中间件的动态检索部分）。"""
    parts: list[str] = []

    if instructions:
        parts.append("工具使用规则（最高优先级，必须遵守）：\n" + "\n".join(f"- {i}" for i in instructions))

    # 技能目录（对齐 Harness 会话目录：只含 name+description，正文经 skill_doc 工具按需读）
    if skill_catalog:
        parts.append(
            "可用技能目录（想用某技能时，用 skill_doc 工具读取它的完整说明书）：\n" + skill_catalog
        )

    persona = []
    for key, title in (("IDENTITY", "你是谁"), ("SOUL", "你的性格"), ("AGENTS", "行为准则")):
        if partner.sections.get(key):
            persona.append(f"## {title}\n{partner.sections[key]}")
    if persona:
        parts.append("\n\n".join(persona))

    # 用户画像：USER.md（人工档案）+ 记忆事实
    user_knowledge: list[str] = []
    if partner.sections.get("USER"):
        user_knowledge.append("【用户档案】（人工维护）：\n" + partner.sections["USER"])
    if memory_facts:
        user_knowledge.append(format_memory_facts(memory_facts))
    if user_knowledge:
        parts.append("\n\n".join(user_knowledge))

    return "\n\n".join(parts)
