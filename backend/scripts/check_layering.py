#!/usr/bin/env python3
"""层间依赖检查（对齐 Octop AGENTS.md 四层依赖规则：依赖只允许向内）。

分层（backend/app/）：
    transport/     —— 接入层（HTTP/WS/入口模块）：只做协议
    domain/        —— 领域核心（experts/memory/behavior/capabilities）：业务唯一所在地
    infrastructure/engine    —— 机制基础库（纯机制，不依赖任何业务层）
    infrastructure/engine/services —— 内核服务模块（薄服务，允许消费领域）
    storage/       —— 存储 repos（只做 SQL/持久化）
    main.py        —— 装配根（只组装，不写业务）；config.py / sse.py 为横切

硬规则：
    1. transport  禁止 import app.main
    2. domain     禁止 import app.transport
    3. engine 机制库（engine/ 顶层）禁止 import app.domain / app.transport / app.storage
    4. storage    禁止 import app.domain / app.transport / app.infrastructure
    5. 除 main.py 外，任何文件禁止 import app.main

用法：python scripts/check_layering.py（exit 0=通过；违规打印并 exit 1）
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

ENGINE_TOP = {
    "composition",
    "context",
    "events",
    "fiber",
    "scope",
    "skill",
    "loader",
    "lifecycle",
    "composer",
    "runtime",
    "approval",
    "robust",
}


def layer_of(rel: str) -> str:
    """由 app/ 内相对路径判层。"""
    parts = rel.split("/")
    if parts[0] == "main.py":
        return "main"
    if parts[0] == "transport":
        return "transport"
    if parts[0] == "domain":
        return "domain"
    if parts[0] == "storage":
        return "storage"
    if parts[0] == "infrastructure":
        if len(parts) >= 3 and parts[1] == "engine" and parts[2] == "services":
            return "engine_services"
        return "engine"  # engine 机制库（顶层文件）
    return "other"  # config.py / sse.py / __init__ 等横切


def module_of(path: Path) -> str:
    """模块名：app.transport.api 等。"""
    return "app." + ".".join(path.relative_to(APP).with_suffix("").parts)


def check() -> list[str]:
    violations: list[str] = []
    for p in sorted(APP.rglob("*.py")):
        rel = str(p.relative_to(APP))
        layer = layer_of(rel)
        mod = module_of(p)
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app."):
                target = node.module
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("app."):
                        target = a.name
                        break
                else:
                    continue
            else:
                continue
            # 目标层的包前缀
            t_parts = target.split(".")
            if len(t_parts) < 2:
                continue

            def bad(rule: str, tgt: str, src: str) -> None:
                violations.append(f"{src} -> {tgt}  [违反 {rule}]")

            if layer == "transport" and t_parts[1] == "main":
                bad("transport 禁止 import 装配根 main", target, mod)
            if layer == "domain" and t_parts[1] == "transport":
                bad("domain 禁止 import transport（领域不反向依赖入口）", target, mod)
            if layer == "engine" and t_parts[1] in ("domain", "transport", "storage"):
                bad("engine 机制库禁止 import 业务层（domain/transport/storage）", target, mod)
            if layer == "storage" and t_parts[1] in ("domain", "transport", "infrastructure"):
                bad("storage 禁止 import 上层（repos 只做 SQL）", target, mod)
            if layer != "main" and t_parts[1] == "main":
                bad("只有装配根 main.py 可被 import；其他层禁止 import main", target, mod)
    return violations


if __name__ == "__main__":
    v = check()
    if v:
        print("层间依赖违规：")
        for line in v:
            print("  " + line)
        sys.exit(1)
    print("层间依赖检查通过（transport → domain → infrastructure/storage，只允许向内）")
