#!/usr/bin/env python3
"""端到端验证「写路径 + HITL 人工审批」：

  1) 触发对话让 agent 调用 mes_submit_work_report → 期待 approval_requested 帧
  2) 走审批 API approve 续跑 → 期待 done + 写库落一条记录
  3) 走审批 API reject 续跑 → 期待 done + 写库不落记录
  4) 只读路径回归：问昨日产量 → 正常 done、无审批帧

用法: python3 scripts/e2e_hitl_test.py
"""
import json
import sys
import time
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"
AGENT_ID = "6a3b128b89e9"
OP_DB = "/Users/superman/projects/code/nuomi/connectors/data/mes_operations.db"


def get_token():
    with urllib.request.urlopen(f"{BASE}/api/session-token", timeout=10) as r:
        return json.load(r)["token"]


def post(url, payload, token, timeout=240):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Nuomi-Token": token},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout)


def read_sse(resp):
    """完整读完 SSE 流，返回事件 type 序列、approval 详情、工具调用名列表。"""
    types, approval, calls = [], None, []
    buf = ""
    deadline = time.time() + 240
    while time.time() < deadline:
        chunk = resp.read(4096)
        if not chunk:
            break
        buf += chunk.decode("utf-8", "replace")
        while "\n\n" in buf:
            raw, buf = buf.split("\n\n", 1)
            for line in raw.splitlines():
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                types.append(ev.get("type"))
                if ev.get("type") == "tool_call_chunk" and ev.get("name"):
                    calls.append((ev["name"], ev.get("args", "")))
                if ev.get("type") == "approval_requested":
                    approval = ev
                if ev.get("type") == "done":
                    return types, approval, calls
    return types, approval, calls


def count_work_reports(db=OP_DB):
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        n = con.execute("SELECT COUNT(*) FROM work_reports").fetchone()[0]
        con.close()
        return n
    except Exception as e:
        return f"ERR {e}"


def main():
    token = get_token()
    print(f"[token] ok")

    # ---- 1) 触发写工具 → approval_requested ----
    thread = uuid.uuid4().hex
    print("\n=== 场景1: 报工触发 HITL ===")
    payload = {
        "messages": "请不要再调用任何其他工具，直接执行 mes_submit_work_report(work_order_id='WO-A-2026-0011', quantity=60, operator='陈师傅')。",
        "thread_id": thread,
        "connectors": ["mes"],
    }
    try:
        resp = post(f"{BASE}/api/agents/{AGENT_ID}/chat", payload, token)
    except Exception as e:
        print(f"[FAIL] chat 请求失败: {e}")
        return 1
    types, approval, calls = read_sse(resp)
    print(f"[events] {types[:8]}...({len(types)})")
    print(f"[calls] {calls[:6]}")
    if approval is None:
        print("[FAIL] 未收到 approval_requested —— 写工具未被护栏拦截")
        return 1
    ar = approval.get("request", {}).get("action_requests", [])
    print(f"[approval] request_id={approval.get('request_id')}")
    print(f"[approval] action_requests={json.dumps(ar, ensure_ascii=False)}")
    name = ar[0].get("name") if ar else None
    if name not in ("mes_submit_work_report", "ask_user_question"):
        print(f"[FAIL] 期望写工具或澄清工具触发审批，实际 {name}")
        return 1
    print(f"[approval] 拦截工具: {name}")

    # ---- 2) approve 续跑 → done + 写库 +1 ----
    print("\n=== 场景2: 批准审批 → 写入台账 ===")
    before = count_work_reports()
    print(f"[db] work_reports before={before}")
    resp = post(
        f"{BASE}/api/agents/{AGENT_ID}/chat/approval",
        {"thread_id": thread, "decision": "approve"},
        token,
    )
    types2, _, _ = read_sse(resp)
    print(f"[events] {types2}")
    if "done" not in types2:
        print(f"[FAIL] 批准后未见 done: {types2}")
        return 1
    after = count_work_reports()
    print(f"[db] work_reports after={after}")
    if not (isinstance(before, int) and isinstance(after, int) and after == before + 1):
        print(f"[FAIL] 批准后应落库 +1（{before}→{after}）")
        return 1
    print("[PASS] 批准写入 OK")

    # ---- 3) reject 续跑 → done + 不写 ----
    print("\n=== 场景3: 拒绝审批 → 不写入 ===")
    thread2 = uuid.uuid4().hex
    payload2 = {
        "messages": "请不要再调用任何其他工具，直接执行 mes_submit_work_report(work_order_id='WO-A-2026-0012', quantity=40, operator='王师傅')。",
        "thread_id": thread2,
        "connectors": ["mes"],
    }
    resp = post(f"{BASE}/api/agents/{AGENT_ID}/chat", payload2, token)
    types3, approval3, calls3 = read_sse(resp)
    print(f"[events] {types3}")
    if approval3 is None:
        print("[FAIL] 场景3 未触发审批，无法测拒绝")
        return 1
    before3 = count_work_reports()
    resp = post(
        f"{BASE}/api/agents/{AGENT_ID}/chat/approval",
        {"thread_id": thread2, "decision": "reject", "message": "数量与排产不符，驳回"},
        token,
    )
    types4, _, _ = read_sse(resp)
    print(f"[events] {types4}")
    if "done" not in types4:
        print(f"[FAIL] 拒绝后未见 done: {types4}")
        return 1
    after3 = count_work_reports()
    print(f"[db] work_reports before={before3} after={after3}")
    if before3 != after3:
        print("[FAIL] 拒绝后不应写入")
        return 1
    print("[PASS] 拒绝不写入 OK")

    # ---- 4) 只读路径回归 ----
    print("\n=== 场景4: 只读路径回归 ===")
    thread3 = uuid.uuid4().hex
    payload3 = {
        "messages": "昨天 A 线生产情况怎么样？",
        "thread_id": thread3,
        "connectors": ["mes"],
    }
    resp = post(f"{BASE}/api/agents/{AGENT_ID}/chat", payload3, token)
    types5, approval5, _ = read_sse(resp)
    print(f"[events] {types5}")
    if "done" not in types5:
        print(f"[FAIL] 只读对话未见 done: {types5}")
        return 1
    if any(t == "approval_requested" for t in types5):
        print("[FAIL] 只读路径不应触发审批")
        return 1
    print("[PASS] 只读回归 OK（无审批帧、正常完成）")

    print("\n===== 端到端 HITL 验证全部通过 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
