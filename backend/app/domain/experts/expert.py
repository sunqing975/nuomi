"""专家（Expert）模型与专家库加载：experts/<name>/ → 系统提示词组装（对齐 Octop Expert）。

专家库设计 = 多目录（多专家）：experts/<name>/manifest.json + 人格文档（IDENTITY/SOUL/AGENTS/USER）。
"多专家 = 加配置文件"；引擎与能力全复用（面试亮点：预置糯米/调研专家只是加目录）。
组装顺序（实测：小模型工具调用依赖规则前置）：
  1. 插件使用规则（最高优先级，来自各插件 system_instruction）
  2. 专家身份（IDENTITY / SOUL / AGENTS，manifest prompt_files 声明）
  3. 用户画像（USER.md，人工可编辑）
  4. 记忆事实（MemoryStore 检索/最近，每轮动态注入由中间件负责）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Expert:
    """一个专家模板（对齐 Octop Expert：manifest + 人格文档，路径即资产）。"""

    id: str
    name: str
    display_name: str
    description: str
    avatar: str = ""
    icon_name: str = ""
    color: str = ""
    welcome_message: str = ""
    default: bool = False
    prompt_files: list[str] = field(default_factory=list)
    quick_prompts: list[dict] = field(default_factory=list)
    dir: Path | None = None
    sections: dict[str, str] = field(default_factory=dict)  # IDENTITY/SOUL/AGENTS/USER

    @property
    def user_profile_lines(self) -> list[str]:
        return [
            line.strip("- ").strip()
            for line in self.sections.get("USER", "").splitlines()
            if line.strip()
        ]


def load_expert(experts_dir: str | Path, name: str) -> Expert:
    root = Path(experts_dir)
    edir = root / name
    meta_path = edir / "manifest.json"
    import json

    meta = {}
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))

    sections = {}
    for key in ("IDENTITY", "SOUL", "AGENTS", "USER"):
        f = edir / f"{key}.md"
        if f.exists():
            sections[key] = f.read_text(encoding="utf-8").strip()

    return Expert(
        id=str(meta.get("id", name)),
        name=name,
        display_name=str(meta.get("display_name", meta.get("label", name))),
        description=str(meta.get("description", "")),
        avatar=str(meta.get("avatar", "")),
        icon_name=str(meta.get("icon_name", "")),
        color=str(meta.get("color", "")),
        welcome_message=str(meta.get("welcome_message", "")),
        default=bool(meta.get("default", False)),
        prompt_files=[str(f) for f in meta.get("prompt_files", [])],
        quick_prompts=list(meta.get("quick_prompts", [])),
        dir=edir,
        sections=sections,
    )


def list_experts(experts_dir: str | Path) -> list[str]:
    root = Path(experts_dir)
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "manifest.json").exists())


def clone_expert(experts_dir: str | Path, src_name: str, display_name: str) -> str:
    """从专家模板创建自定义专家（对齐 Octop create-from-template）：
    复制目录（manifest + 人格文档）→ 改写 manifest（新 id/name、display_name、default=False）。
    返回新专家 name。"""
    import json
    import re
    from datetime import datetime

    root = Path(experts_dir)
    src = root / src_name
    if not (src / "manifest.json").exists():
        raise ValueError(f"专家模板不存在：{src_name}")

    base = re.sub(r"[^0-9A-Za-z一-鿿]", "", display_name).strip() or "custom"
    slug = f"custom-{base}"
    target = root / slug
    n = 2
    while target.exists():
        target = root / f"{slug}-{n}"
        n += 1

    target.mkdir(parents=True, exist_ok=False)
    for item in src.iterdir():
        if item.is_file():
            (target / item.name).write_bytes(item.read_bytes())

    meta_path = target / "manifest.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["id"] = target.name
    meta["name"] = target.name
    meta["display_name"] = display_name
    meta["default"] = False
    meta.setdefault("description", "")
    if not meta["description"]:
        meta["description"] = f"由 {src_name} 模板创建（{datetime.now():%Y-%m-%d}）"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return target.name


def delete_expert(experts_dir: str | Path, name: str) -> bool:
    """删除自定义专家（内置 default 专家禁止删除）。返回是否删除成功。"""
    import shutil

    root = Path(experts_dir)
    edir = root / name
    if not (edir / "manifest.json").exists():
        return False
    meta = edir / "manifest.json"
    import json

    if bool(json.loads(meta.read_text(encoding="utf-8")).get("default", False)):
        raise ValueError("内置默认专家不可删除")
    shutil.rmtree(edir)
    return True


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
        "并直接引用；只有在记忆里确实没有时才说不知道。\n" + "\n".join(lines)
    )


def assemble_system_prompt(
    expert: Expert,
    instructions: list[str],
    memory_facts: list | None = None,
    user_profile_extra: list[str] | None = None,
    skill_catalog: str | None = None,
) -> str:
    """组装完整 system prompt（不含中间件的动态检索部分）。"""
    parts: list[str] = []

    if instructions:
        parts.append(
            "工具使用规则（最高优先级，必须遵守）：\n" + "\n".join(f"- {i}" for i in instructions)
        )

    # 技能目录（对齐 Harness 会话目录：只含 name+description，正文经 skill_doc 工具按需读）
    if skill_catalog:
        parts.append(
            "可用技能目录（想用某技能时，用 skill_doc 工具读取它的完整说明书）：\n" + skill_catalog
        )

    persona = []
    for key, title in (("IDENTITY", "你是谁"), ("SOUL", "你的性格"), ("AGENTS", "行为准则")):
        if expert.sections.get(key):
            persona.append(f"## {title}\n{expert.sections[key]}")
    if persona:
        parts.append("\n\n".join(persona))

    # 用户画像：USER.md（人工档案）+ 记忆事实
    user_knowledge: list[str] = []
    if expert.sections.get("USER"):
        user_knowledge.append("【用户档案】（人工维护）：\n" + expert.sections["USER"])
    if memory_facts:
        user_knowledge.append(format_memory_facts(memory_facts))
    if user_knowledge:
        parts.append("\n\n".join(user_knowledge))

    return "\n\n".join(parts)
