"""core/composition.py · Profile 组合配置（对齐 Cordis profile + patch 分层）。

**应用 = 插件树**，由 nuomi.json 定义；layers 按序叠加，后层按 `id` 定位并覆盖前层
（config 整体替换，与 Harness patch 语义一致）。换能力/换模型提供方 = 改配置行，不写代码。

profile 结构：
{
  "layers": [
    { "id": "base", "plugins": [
        {"id": "llm", "plugin": "llm-deepseek", "config": {...}},
        {"id": "runtime-mood", "plugin": "runtime-mood"}
    ]},
    { "id": "user", "plugins": [
        {"id": "llm", "plugin": "llm-doubao", "config": {...}}   // patch：按 id 覆盖
    ]}
  ]
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProfileEntry:
    id: str
    plugin: str  # plugins/ 下的目录名
    config: dict[str, Any] = field(default_factory=dict)
    disabled: bool = False
    layer: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plugin": self.plugin,
            "config": self.config,
            "disabled": self.disabled,
            "layer": self.layer,
        }


def resolve_profile(profile: dict | None) -> list[ProfileEntry]:
    """layers 按序叠加：后层按 id 覆盖前层（config 整体替换、plugin 可换、disabled 覆盖）。"""
    merged: dict[str, ProfileEntry] = {}
    layers = (profile or {}).get("layers", [])
    for layer in layers:
        layer_id = layer.get("id", "")
        for row in layer.get("plugins", []):
            row_id = str(row.get("id", row.get("plugin")))
            entry = ProfileEntry(
                id=row_id,
                plugin=str(row.get("plugin", "")),
                config=dict(row.get("config", {})),
                disabled=bool(row.get("disabled", False)),
                layer=layer_id,
            )
            prev = merged.get(row_id)
            if prev is not None:
                # patch 语义：后层整个替换 config（不合并），plugin 可换，disabled 可覆盖
                entry.plugin = entry.plugin or prev.plugin
                entry.config = (
                    dict(row.get("config", prev.config)) if "config" in row else prev.config
                )
            merged[row_id] = entry
    return list(merged.values())


def load_profile(path: str | Path) -> list[ProfileEntry]:
    p = Path(path)
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return resolve_profile(data)


def default_profile() -> dict:
    """V3 默认组合：核心服务 + 模型提供方 + agent preset + 现有能力/运行时插件。"""
    return {
        "layers": [
            {
                "id": "base",
                "plugins": [
                    # LLM 是核心服务（models.py + /api/models/activate），不由供应商插件提供
                    {"id": "service-tools", "plugin": "service-tools", "config": {}},
                    {"id": "service-sessions", "plugin": "service-sessions", "config": {}},
                    {
                        "id": "service-system-prompt",
                        "plugin": "service-system-prompt",
                        "config": {},
                    },
                    {"id": "service-agent-loop", "plugin": "service-agent-loop", "config": {}},
                    {"id": "service-memory", "plugin": "service-memory", "config": {}},
                    {"id": "service-settings", "plugin": "service-settings", "config": {}},
                    {"id": "agent-companion", "plugin": "agent-companion", "config": {}},
                    {"id": "agent-researcher", "plugin": "agent-researcher", "config": {}},
                    {"id": "runtime-team", "plugin": "team", "config": {}},
                ],
            },
            {
                "id": "capabilities",
                "plugins": [
                    {"id": "cap-datetime", "plugin": "datetime", "config": {}},
                    {"id": "cap-memory", "plugin": "memory", "config": {}},
                    {"id": "cap-knowledge", "plugin": "knowledge", "config": {}},
                    {"id": "cap-mcp-notes", "plugin": "mcp-notes", "config": {}},
                    {"id": "cap-pyfunc", "plugin": "pyfunc", "config": {}},
                    {"id": "cap-voice", "plugin": "voice", "config": {}},
                    {"id": "cap-web", "plugin": "web", "config": {}},
                    {"id": "cap-shell", "plugin": "shell", "config": {}},
                    {"id": "cap-fs", "plugin": "fs", "config": {}},
                ],
            },
            {
                "id": "runtime",
                "plugins": [
                    {"id": "runtime-voice-input", "plugin": "voice-input", "config": {}},
                    {"id": "runtime-mood", "plugin": "mood", "config": {}},
                    {"id": "runtime-robot", "plugin": "robot", "config": {}},
                ],
            },
        ]
    }
