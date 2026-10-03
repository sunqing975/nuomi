"""Eval 评测（Phase 3）：对运行中的糯米跑评分集，产出报告。

用法（后端已在 127.0.0.1:8000 运行）：
  cd backend && uv run python scripts/eval.py [--base http://127.0.0.1:8000]

流程：每个场景开新 thread 发消息 → 收集回复 → 从 /logs 拿工具调用 →
按 rubric（contains / not_contains / regex / tool_used）逐项打分 →
输出控制台表格 + data/logs/eval_report_<ts>.json。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
SCENARIOS = Path(__file__).resolve().parent / "eval_scenarios.json"
REPORT_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"


def chat_once(base: str, message: str, thread_id: str) -> str:
    with httpx.stream(
        "POST", f"{base}/api/chat", json={"message": message, "thread_id": thread_id}, timeout=120
    ) as r:
        reply = []
        for line in r.iter_lines():
            if line.startswith("data: "):
                try:
                    d = json.loads(line[6:])
                    reply.append(d.get("content", ""))
                except json.JSONDecodeError:
                    continue
        # 去重：done 事件会带完整回复，token 已拼接；只取 token 拼接结果（长度>0 且不重复）
        joined = "".join(reply)
        return joined


def tools_for_thread(base: str, thread_id: str) -> list[str]:
    try:
        r = httpx.get(f"{base}/logs?n=30", timeout=10).json()
        for e in reversed(r.get("entries", [])):
            if e.get("thread_id") == thread_id:
                return e.get("tools_called") or []
    except Exception:
        pass
    return []


def check_pass(check: dict, reply: str, tools: list[str]) -> bool:
    t = check["type"]
    if t == "contains":
        return check["value"] in reply
    if t == "not_contains":
        return check["value"] not in reply
    if t == "regex":
        return re.search(check["value"], reply) is not None
    if t == "tool_used":
        return check["value"] in tools
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    args = ap.parse_args()
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))

    report = {"generated_at": time.time(), "scenarios": []}
    print(f"{'场景':<16}{'得分':<8}{'通过/权重':<12}回复摘要")
    for sc in scenarios:
        tid = f"eval-{sc['id']}-{uuid.uuid4().hex[:6]}"
        reply = chat_once(args.base, sc["input"], tid)
        tools = tools_for_thread(args.base, tid)
        total_w = sum(c["weight"] for c in sc["checks"])
        got_w = sum(c["weight"] for c in sc["checks"] if check_pass(c, reply, tools))
        ratio = got_w / total_w if total_w else 0.0
        record = {
            "id": sc["id"],
            "name": sc["name"],
            "score": round(ratio, 2),
            "reply": reply[:160],
            "tools": tools,
        }
        report["scenarios"].append(record)
        summary = reply[:40].replace("\n", " ")
        print(f"{sc['name']:<16}{ratio * 100:>5.0f}%  {got_w}/{total_w:<10}{summary}")

    report["overall"] = round(
        sum(s["score"] for s in report["scenarios"]) / len(report["scenarios"]), 2
    )
    print(f"\n总体得分：{report['overall'] * 100:.0f}%  ({len(report['scenarios'])} 个场景)")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORT_DIR / f"eval_report_{int(time.time())}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"报告已写入 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
