#!/usr/bin/env python3
"""导入 Octop 专家到 nuomi（CLI 入口）。

用法：
    .venv/bin/python scripts/import_octop_expert.py <source_dir> [--name 显示名]

source_dir 示例：
    ~/.octop/agents/1KMDWV/                 # 已安装的 octop 专家 workspace
    $OCTOP_SRC/src/octop/infra/agents/experts/library/ai-coding-coach
                                            # Octop 源码仓库内的专家库（OCTOP_SRC 指向该仓库根，默认同级 ../Octop）

说明：复制 persona 文件（USER/SOUL/AGENTS/MEMORY/BOOTSTRAP/PROACTIVE.md）、
manifest、skills/ 与 agents/（子智能体）到 nuomi 专家 workspace
（数据根 agent-workspaces/<agent_id>/），并注册 DB agent。记忆不复制。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.domain.agents.importer import import_octop_expert  # noqa: E402
from app.domain.agents.service import enrich_agent  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--name=")]
    name = None
    for a in sys.argv[1:]:
        if a.startswith("--name="):
            name = a.split("=", 1)[1]
    if not args:
        print(__doc__)
        sys.exit(1)
    source = args[0]
    try:
        row = import_octop_expert(source, name=name)
    except Exception as e:  # noqa: BLE001
        print(f"导入失败: {e}", file=sys.stderr)
        sys.exit(2)
    enriched = enrich_agent(row)
    print("导入成功：")
    print(f"  agent_id     : {row['agent_id']}")
    print(f"  名称         : {enriched['name']}")
    print(f"  描述         : {enriched['description']}")
    print(f"  workspace    : 数据根/agent-workspaces/{row['agent_id']}/")
    print(f"  welcome      : {enriched.get('welcome_message', '')}")


if __name__ == "__main__":
    main()
