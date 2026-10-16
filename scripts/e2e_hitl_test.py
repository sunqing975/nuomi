#!/usr/bin/env python3
"""端到端验证「写路径 + HITL 人工审批」：

  1) 触发对话让 agent 调用 mes_submit_work_report → 期待 approval_requested 帧
  2) 走审批 API approve 续跑 → 期待 done + 写库落一条记录
  3) 走审批 API reject 续跑 → 期待 done + 写库不落记录
  4) 只读路径回归：问最近报工记录 → 正常 done、无审批帧

用法: python3 scripts/e2e_hitl_test.py

默认会临时创建一个全新专家跑完整流程、结束时删掉（含工作区）：
真机专家带记忆时场景1会假失败——实测 2026-10-16 真机专家的 MEMORY.md 里学到
「重复报工先问再做」后，它直接拒绝调用写工具，护栏根本没机会响。全新工作区没有
这条记忆，护栏是唯一变量；顺带不污染真机专家的记忆和工作区。
要针对已有专家跑：NUOMI_E2E_AGENT_ID=<agent_id> python3 scripts/e2e_hitl_test.py
"""
import json
import os
import sys
import time
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"
AGENT_ID = os.environ.get("NUOMI_E2E_AGENT_ID", "")
OP_DB = "/Users/superman/projects/code/nuomi/connectors/data/mes_operations.db"


def get_token():
    with urllib.request.urlopen(f"{BASE}/api/session-token", timeout=10) as r:
        return json.load(r)["token"]


def create_probe_agent(token):
    payload = {
        "name": f"e2e-hitl-probe-{uuid.uuid4().hex[:6]}",
        "description": "HITL 端到端测试用临时专家（脚本结束即删）",
    }
    with post(f"{BASE}/api/agents", payload, token, timeout=30) as r:
        row = json.load(r)
    return row["agent_id"]


def delete_probe_agent(agent_id, token):
    req = urllib.request.Request(
        f"{BASE}/api/agents/{agent_id}",
        headers={"X-Nuomi-Token": token},
        method="DELETE",
    )
    try:
        urllib.request.urlopen(req, timeout=30).close()
        print(f"[cleanup] 已删除临时专家 {agent_id}")
    except Exception as e:  # 清理失败不影响判定，但要让人看得见
        print(f"[cleanup] 删除临时专家失败（请手工清理 {agent_id}）: {e}")



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


def run_scenarios(token, agent_id):
    # ---- 1) 触发写工具 → approval_requested ----
    thread = uuid.uuid4().hex
    print("\n=== 场景1: 报工触发 HITL ===")
    payload = {
        "messages": "请不要再调用任何其他工具，直接执行 mes_submit_work_report(work_order_id='WO-A-2026-0011', quantity=60, operator='陈师傅')。",
        "thread_id": thread,
        "connectors": ["mes"],
    }
    try:
        resp = post(f"{BASE}/api/agents/{agent_id}/chat", payload, token)
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
        f"{BASE}/api/agents/{agent_id}/chat/approval",
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
    resp = post(f"{BASE}/api/agents/{agent_id}/chat", payload2, token)
    types3, approval3, calls3 = read_sse(resp)
    print(f"[events] {types3}")
    if approval3 is None:
        print("[FAIL] 场景3 未触发审批，无法测拒绝")
        return 1
    before3 = count_work_reports()
    resp = post(
        f"{BASE}/api/agents/{agent_id}/chat/approval",
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
    # 问「最近的报工记录」（list_work_reports，演示库有数据）而不是「昨天 A 线生产
    # 情况」：后者在演示库里最近几天全是 0 行，模型会一路换日期/换工具试到 60 步
    # 递归上限（见 9f64bda 的 friendly_stream_error）。这里要验的是「只读问答不触发
    # 审批」，不该顺带考演示数据的完备性。
    payload3 = {
        "messages": "帮我看看最近的报工记录都有哪些？",
        "thread_id": thread3,
        "connectors": ["mes"],
    }
    resp = post(f"{BASE}/api/agents/{agent_id}/chat", payload3, token)
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


def main():
    token = get_token()
    print("[token] ok")
    agent_id = AGENT_ID or create_probe_agent(token)
    probe_created = not AGENT_ID
    if probe_created:
        print(f"[setup] 临时专家 {agent_id}（跑完删除）")
    try:
        return run_scenarios(token, agent_id)
    finally:
        if probe_created:
            delete_probe_agent(agent_id, token)


if __name__ == "__main__":
    sys.exit(main())
