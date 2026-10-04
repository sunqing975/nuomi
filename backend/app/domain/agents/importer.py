"""Octop 专家导入：把 octop 专家目录（~/.octop/agents/<id>/ 或 Octop library/<id>/）
复制为 nuomi 专家 workspace，并注册 DB agent 记录。

对齐 octop 布局：persona 文件（USER/SOUL/AGENTS/MEMORY/BOOTSTRAP/PROACTIVE.md）
放 workspace 根，manifest 落 .octop/manifest.json，skills/ 与 agents/（子智能体）
一并复制。记忆（.octop/memory.sqlite）不复制——新专家从零记忆。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.domain.agents.service import (
    PERSONA_FILES,
    agent_service,
    agent_workspace_dir,
)
from app.storage import db

# 导入时随 persona 一并复制的可选文件
EXTRA_PERSONA_FILES = ("BOOTSTRAP.md", "PROACTIVE.md")
# 随导入复制的子目录（技能、子智能体）：兼容两种源布局——
# library 模板在根级 skills/；已装实例（~/.octop/agents/<id>/）在 .octop/skills/、.octop/_builtin_skills/、.octop/agents/
COPY_DIRS = ("skills", "_builtin_skills", "agents")
MANIFEST_RELS = (".octop/manifest.json", "manifest.json")


def _read_manifest(src: Path) -> dict:
    for rel in MANIFEST_RELS:
        p = src / rel
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError):
                return {}
    return {}


def _locale(d: object, lang: str = "zh") -> str:
    if isinstance(d, dict):
        v = d.get(lang) or d.get("en")
        return str(v) if v else ""
    return str(d) if d else ""


def import_octop_expert(source_dir: str | Path, name: str | None = None) -> dict:
    """从 octop 专家目录导入并注册。返回 enrich 后的 agent 记录。

    source_dir：octop 专家 workspace（~/.octop/agents/<id>/）或模板目录
    （Octop 源码 experts/library/<id>/）。name 缺省用 manifest label.zh。
    """
    src = Path(source_dir).expanduser().resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"源目录不存在: {src}")
    manifest = _read_manifest(src)
    if not manifest:
        raise ValueError(f"目录中找不到 manifest.json（.octop/manifest.json 或根 manifest.json）: {src}")

    label = manifest.get("label") or {}
    display = name or _locale(label) or src.name
    desc = _locale(manifest.get("description"))
    welcome = _locale(manifest.get("welcome_message"))
    icon = manifest.get("icon_name") or "bot"
    color = manifest.get("color") or "#6366f1"

    agent_id = db.gen_agent_id()
    ws = agent_workspace_dir(agent_id)
    ws.mkdir(parents=True, exist_ok=True)

    # persona 文件（根 md）
    for f in PERSONA_FILES + EXTRA_PERSONA_FILES:
        s = src / f
        if s.is_file():
            shutil.copy2(s, ws / f)
    # manifest prompt_files 声明的其余 md（如 IDENTITY.md / HEARTBEAT.md）一并复制
    for f in manifest.get("prompt_files") or []:
        if isinstance(f, str) and f.endswith(".md"):
            s = src / f
            if s.is_file():
                shutil.copy2(s, ws / f)
    # manifest → .octop/manifest.json
    (ws / ".octop").mkdir(exist_ok=True)
    src_manifest = next((src / r for r in MANIFEST_RELS if (src / r).is_file()), None)
    if src_manifest is not None:
        shutil.copy2(src_manifest, ws / ".octop" / "manifest.json")
    else:
        (ws / ".octop" / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    # skills / agents 子目录：源根级与源 .octop/ 下都检查（两种布局兼容），统一落到目标根级
    for d in COPY_DIRS:
        for s in (src / d, src / ".octop" / d):
            if s.is_dir():
                shutil.copytree(s, ws / d, dirs_exist_ok=True)
                break

    row = agent_service.create(
        {
            "agent_id": agent_id,
            "name": display,
            "description": desc or "人工智能助手",
            "system_prompt": f"你是{display}，住在用户电脑里的人工智能助手。中文回答，简洁友好。",
            "icon_name": icon,
            "color": color,
            "welcome_message": welcome or f"你好，我是{display}。",
            "kind": "expert",
        }
    )
    return row
