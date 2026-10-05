"""Agent 运行时参数映射：agents.config_json → harness ChatRequest（对齐 Octop runtime_limits）。

Octop 语义（src/octop/infra/agents/settings/runtime_limits.py）：
- ``max_iters``            → 顶层 ``recursion_limit``（LangGraph 递归上限）
- ``temperature/top_p/max_tokens`` → ``configurable["model_settings"]``
                             → harness 默认挂载的 ModelSettingsMiddleware
                             → ``model.bind(...)``（LLM 请求体）
- ``max_input_length``     → ``configurable["max_input_tokens"]``（上下文窗口上限覆盖）

nuomi 只做「存于 agents.config_json → 注入 ChatRequest」的映射，不动 octop-harness。
"""

from __future__ import annotations

from typing import Any

from octop_harness.middleware.model_settings import (
    CONFIGURABLE_MAX_INPUT_TOKENS,
    CONFIGURABLE_MODEL_SETTINGS,
)

# agents.config_json 中识别为「运行时参数」的键（与 Octop AGENT_RUNTIME_CONFIG_KEYS 一致）
AGENT_RUNTIME_CONFIG_KEYS = (
    "max_iters",
    "max_input_length",
    "temperature",
    "top_p",
    "max_tokens",
)


def _positive_int(value: Any) -> int | None:
    """仅接受 >0 的整数（bool 不算）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, float) and value.is_integer():
        iv = int(value)
        return iv if iv > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        iv = int(value.strip())
        return iv if iv > 0 else None
    return None


def _unit_float(value: Any, *, min_val: float, max_val: float) -> float | None:
    """仅接受闭区间内的数值（bool 不算）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        parsed = float(value)
        return parsed if min_val <= parsed <= max_val else None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = float(stripped)
        except ValueError:
            return None
        return parsed if min_val <= parsed <= max_val else None
    return None


def agent_recursion_limit(cfg: dict[str, Any]) -> int | None:
    """LangGraph recursion_limit（来自 max_iters）。"""
    return _positive_int(cfg.get("max_iters"))


def agent_max_input_tokens(cfg: dict[str, Any]) -> int | None:
    """上下文窗口上限覆盖（来自 max_input_length）。"""
    return _positive_int(cfg.get("max_input_length"))


def agent_model_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    """LangChain ``model.bind(...)`` kwargs（temperature/top_p/max_tokens）。"""
    settings: dict[str, Any] = {}
    temperature = _unit_float(cfg.get("temperature"), min_val=0.0, max_val=2.0)
    if temperature is not None:
        settings["temperature"] = temperature
    top_p = _unit_float(cfg.get("top_p"), min_val=0.0, max_val=1.0)
    if top_p is not None:
        settings["top_p"] = top_p
    max_tokens = _positive_int(cfg.get("max_tokens"))
    if max_tokens is not None:
        settings["max_tokens"] = max_tokens
    return settings


def apply_agent_runtime_to_stream_request(
    req: dict[str, Any],
    agent_cfg: dict[str, Any],
) -> dict[str, Any]:
    """把 agent 运行时参数合并进 harness ``stream`` 请求 dict（对齐 Octop 同名函数）。

    req 中已显式指定的值优先（per-turn 覆盖 agent 默认）；configurable 增量合并。
    """
    out = dict(req)

    recursion_limit = agent_recursion_limit(agent_cfg)
    if recursion_limit is not None and out.get("recursion_limit") is None:
        out["recursion_limit"] = recursion_limit

    configurable_updates: dict[str, Any] = {}
    model_settings = agent_model_settings(agent_cfg)
    if model_settings:
        existing_cfg = out.get("configurable")
        existing_settings = (
            existing_cfg.get(CONFIGURABLE_MODEL_SETTINGS)
            if isinstance(existing_cfg, dict)
            else None
        )
        merged_settings = dict(existing_settings) if isinstance(existing_settings, dict) else {}
        merged_settings.update(model_settings)
        configurable_updates[CONFIGURABLE_MODEL_SETTINGS] = merged_settings

    max_input_tokens = agent_max_input_tokens(agent_cfg)
    if max_input_tokens is not None:
        configurable_updates[CONFIGURABLE_MAX_INPUT_TOKENS] = max_input_tokens

    if configurable_updates:
        configurable = dict(out.get("configurable") or {})
        configurable.update(configurable_updates)
        out["configurable"] = configurable

    return out
