#!/usr/bin/env python3
"""端到端验证 HITL「刷新恢复 + 台账留痕」：

  1) 触发写工具 → 收到 approval_requested 后**立刻断开**（模拟用户刷新/关页面）
  2) GET /api/agents/{id}/approvals?status=pending → 台账里找得回这条待审
  3) 用台账里的 request_id 提交 approve（模拟刷新后卡片重新提交）→ done + 状态转 resolved
  4) 同一个 request_id 重复提交 → 409（防卡片复活导致重复放行写工具）

用法: python3 scripts/e2e_hitl_recovery.py

默认临时建一个全新专家跑、跑完删掉（含工作区），理由同 e2e_hitl_test.py：真机专家
带记忆时可能先反问你「这单是不是重复报工」，压根不调用写工具，护栏没机会响。
要针对已有专家跑：NUOMI_E2E_AGENT_ID=<agent_id> python3 scripts/e2e_hitl_recovery.py
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"
AGENT_ID = os.environ.get("NUOMI_E2E_AGENT_ID", "")


def get_token():
    with urllib.request.urlopen(f"{BASE}/api/session-token", timeout=10) as r:
        return json.load(r)["token"]


def request(method, url, payload, token, timeout=240):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json", "X-Nuomi-Token": token},
        method=method,
    )
    return urllib.request.urlopen(req, timeout=timeout)


def post(url, payload, token, timeout=240):
    return request("POST", url, payload, token, timeout)


def get(url, token, timeout=30):
    return request("GET", url, None, token, timeout)


def create_probe_agent(token):
    payload = {
        "name": f"e2e-hitl-recovery-{uuid.uuid4().hex[:6]}",
        "description": "HITL 恢复验证用临时专家（脚本结束即删）",
    }
    with post(f"{BASE}/api/agents", payload, token, timeout=30) as r:
        return json.load(r)["agent_id"]


def delete_probe_agent(agent_id, token):
    try:
        with request("DELETE", f"{BASE}/api/agents/{agent_id}", None, token, timeout=30):
            print(f"[cleanup] 已删除临时专家 {agent_id}")
    except Exception as e:  # 清理失败不影响判定，但要让人看得见
        print(f"[cleanup] 删除临时专家失败（请手工清理 {agent_id}）: {e}")


def read_sse(resp, stop_at_approval=False):
    """读完 SSE（或收到审批帧就停），返回 (types, approval_event, done_seen)。"""
    types, approval = [], None
    buf = ""
    deadline = time.time() + 240
    try:
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
                    if ev.get("type") == "approval_requested":
                        approval = ev
                        if stop_at_approval:
                            return types, approval, False
                    if ev.get("type") == "done":
                        return types, approval, True
    finally:
        resp.close()
    return types, approval, "done" in types


def pending(token, agent_id, thread_id):
    resp = get(
        f"{BASE}/api/agents/{agent_id}/approvals?status=pending&thread_id={thread_id}&limit=5",
        token,
    )
    with resp:
        return json.load(resp).get("approvals", [])


def run_scenarios(token, agent_id):
    thread = uuid.uuid4().hex

    # ---- 1) 触发审批后立刻断开 ----
    print("\n=== 场景1: 触发审批后断开连接（模拟刷新）===")
    payload = {
        "messages": "请不要再调用任何其他工具，直接执行 mes_submit_work_report(work_order_id='WO-A-2026-0013', quantity=30, operator='李师傅')。",
        "thread_id": thread,
        "connectors": ["mes"],
    }
    try:
        resp = post(f"{BASE}/api/agents/{agent_id}/chat", payload, token)
    except Exception as e:
        print(f"[FAIL] chat 请求失败: {e}")
        return 1
    types, approval, _ = read_sse(resp, stop_at_approval=True)
    print(f"[events] {types[:8]}...({len(types)})")
    if approval is None:
        print("[FAIL] 未收到 approval_requested")
        return 1
    request_id = approval.get("request_id")
    print(f"[approval] request_id={request_id} thread={thread}")

    # ---- 2) 刷新后从台账找回待审 ----
    print("\n=== 场景2: 刷新后从台账找回待审卡片 ===")
    rows = pending(token, agent_id, thread)
    print(f"[ledger] pending={len(rows)}")
    if not rows:
        print("[FAIL] 刷新后台账里找不到这条待审（恢复路径断）")
        return 1
    row = rows[0]
    if row.get("request_id") != request_id or row.get("thread_id") != thread:
        print(f"[FAIL] 台账返回的是另一条: {row.get('request_id')}")
        return 1
    if row.get("status") != "pending":
        print(f"[FAIL] 状态应为 pending，实际 {row.get('status')}")
        return 1
    names = [a.get("name") for a in row.get("actions") or []]
    print(f"[ledger] actions={names} allowed={[a.get('allowed_decisions') for a in row.get('actions') or []]}")
    if "request" in row:
        print("[FAIL] 台账不应把原始 HITLRequest 外泄给前端")
        return 1
    if not names:
        print("[FAIL] 台账缺动作明细，刷新后卡片画不出来")
        return 1
    print("[PASS] 刷新找回 OK")

    # ---- 3) 用找回的 request_id 提交 approve ----
    print("\n=== 场景3: 从台账恢复后提交批准 ===")
    resp = post(
        f"{BASE}/api/agents/{agent_id}/chat/approval",
        {
            "thread_id": thread,
            "request_id": request_id,
            "decisions": [{"type": "approve"}],
        },
        token,
    )
    types3, _, done3 = read_sse(resp)
    print(f"[events] {types3}")
    if not done3:
        print(f"[FAIL] 批准后未见 done: {types3}")
        return 1
    rows = pending(token, agent_id, thread)
    print(f"[ledger] pending after approve={len(rows)}")
    if rows:
        print("[FAIL] 批准后台账仍是 pending")
        return 1
    print("[PASS] 恢复提交 OK（台账已转 resolved）")

    # ---- 4) 重复提交同一个 request_id → 409 ----
    print("\n=== 场景4: 重复提交同一审批 → 409 ===")
    try:
        resp = post(
            f"{BASE}/api/agents/{agent_id}/chat/approval",
            {"thread_id": thread, "request_id": request_id, "decision": "approve"},
            token,
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"[http] {e.code} {body[:120]}")
        if e.code != 409:
            print(f"[FAIL] 期望 409，实际 {e.code}")
            return 1
        print("[PASS] 重复提交被 409 挡住 OK")
        print("\n===== HITL 恢复/台账验证全部通过 =====")
        return 0
    with resp:
        print(f"[FAIL] 重复提交竟未被拒绝（{resp.status}）")
    return 1


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
