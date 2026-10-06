"""结构性保证（P0-5）：锁定「StreamingResponse 的 generator 内不能抛 HTTPException」。

背景：FastAPI 只在「响应对象返回前」能把 HTTPException 转成错误响应；一旦进入
StreamingResponse 的 async generator，异常只会中断连接，调用方看到"流断了"。

本测试扫描 transport 层源码，强制两条规则：
  1. transport 层禁止**裸构造** ``StreamingResponse(...)`` —— 统一走
     ``transport/streaming.stream_response``（校验在 gen 之前执行，HTTPException 才能正常转 400/404）；
  2. 任何 ``async def gen`` 函数体内禁止 ``raise HTTPException`` —— 校验必须放 gen 之前。
     （对 gen 内部调用其它会抛 HTTPException 的函数（如 ensure_agent_runtime），规则 1 的
     stream_response 出口配合 code review 兜底；本测试锁死的是「直接在 gen 里 raise」这一形状。）

这不是"假测试"：直接检查源码 AST/文本，新端点只要绕开 helper 裸构造 StreamingResponse，
或把校验搬进 gen，测试立刻红。
"""

from __future__ import annotations

import ast
from pathlib import Path

TRANSPORT_DIR = Path(__file__).resolve().parents[1] / "app" / "transport"


def _transport_files() -> list[Path]:
    return sorted(TRANSPORT_DIR.glob("*.py"))


def test_no_raw_streaming_response_outside_helper() -> None:
    """规则 1：StreamingResponse(...) 构造只允许出现在 streaming.py（helper 内部）。"""
    violations: list[str] = []
    for f in _transport_files():
        if f.name == "streaming.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            # 裸构造特征：StreamingResponse( 出现，且不是 stream_response( 调用
            if "StreamingResponse(" in line and "stream_response(" not in line:
                # 类型标注 `-> StreamingResponse:` / import 行不算构造
                if "-> StreamingResponse" in stripped or stripped.startswith(("from ", "import ")):
                    continue
                violations.append(f"{f.name}:{i}: {stripped}")
    assert not violations, (
        "存在裸 StreamingResponse 构造（必须走 streaming.stream_response，"
        "否则校验放 gen 内时 HTTPException 不会转 400）：\n" + "\n".join(violations)
    )


def test_no_http_exception_raised_inside_gen() -> None:
    """规则 2：所有 async def gen 函数体内禁止 raise HTTPException。"""
    violations: list[str] = []
    for f in _transport_files():
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef) or node.name != "gen":
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Raise) or sub.exc is None:
                    continue
                func = sub.exc.func if isinstance(sub.exc, ast.Call) else None
                if func is None:
                    continue
                name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else "")
                if name == "HTTPException":
                    violations.append(f"{f.name}:{sub.lineno}")
    assert not violations, (
        "async def gen 内存在 raise HTTPException（校验必须放 gen 之前、端点函数体内）：\n"
        + "\n".join(violations)
    )
