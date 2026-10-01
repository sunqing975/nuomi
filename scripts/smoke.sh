#!/usr/bin/env bash
# 糯米 V2 · Phase 0 冒烟测试：健康检查 + SSE 流式 + 会话记忆（需后端已在 8000 端口运行）
set -euo pipefail
BASE="${1:-http://127.0.0.1:8000}"

echo "== 1) /health =="
curl -s "$BASE/health" | python3 -m json.tool

echo
echo "== 2) SSE 流式对话（问时间 → 应触发 datetime 插件，且流中无工具原始输出）=="
curl -s -N -X POST "$BASE/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"现在几点了？"}'

echo
echo "== 3) 会话记忆（同 thread 两轮）=="
TID=$(curl -s -N -X POST "$BASE/api/chat" \
  -H "Content-Type: application/json" \
  -d '{"message":"记下这个数字：42"}' \
  | sed -n 's/.*"thread_id": "\([^"]*\)".*/\1/p' | head -1)
echo "thread_id=$TID"
curl -s -N -X POST "$BASE/api/chat" \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"我刚才让你记下什么数字？\",\"thread_id\":\"$TID\"}" \
  | grep '^event: done' -A1 | sed -n 's/^data: //p' \
  | python3 -c "import sys,json; print(json.loads(sys.stdin.read())['content'])"
echo "== 完成 =="
