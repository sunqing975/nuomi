"""LLM Provider 配置存储：{workspace}/providers.json（单根工作区）。

- 运行时配置为权威（控制台「设置 → 大模型」可改）；.env 的 LLM_* 仅作启动种子/回退
- 保存后由调用方释放 agent 实例（下次对话生效）
- 模型不绑专家（2026-10-04）：对话时由请求 model 字段 per-turn 选择，本模块只提供
  合法模型集合（model_refs）供校验
- 安全：api_key 明文存工作区（仓库外，不进 git）；对外接口层负责脱敏（GET 时隐藏）
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import settings

PROVIDERS_FILE_NAME = "providers.json"


def _seed_provider() -> dict:
    """.env LLM_* 种子 provider（未配置 providers.json 时的回退）。"""
    return {
        "id": "llm",
        "name": "默认",
        "base_url": settings.llm_base_url,
        "api_key": settings.llm_api_key,
        "protocol": "openai",
        "models": [{"id": settings.llm_model, "name": settings.llm_model}],
    }


def path() -> Path:
    return settings.workspace_path / PROVIDERS_FILE_NAME


def load() -> list[dict]:
    """读 providers.json；缺失/损坏回退 .env 种子单 provider。"""
    p = path()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = None
        if isinstance(data, dict) and isinstance(data.get("providers"), list):
            provs = [
                d for d in data["providers"]
                if isinstance(d, dict) and d.get("id") and d.get("base_url")
            ]
            if provs:
                return provs
    return [_seed_provider()]


def save(providers: list[dict]) -> list[dict]:
    path().write_text(
        json.dumps({"providers": providers}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return providers


def model_refs() -> set[str]:
    """全部合法模型复合串（校验对话请求 model 用）。"""
    return {
        f"{p['id']}/{m['id']}"
        for p in load()
        for m in (p.get("models") or [])
        if m.get("id")
    }


def mask_key(key: str) -> str:
    """api_key 脱敏：首 4 + *** + 尾 4（短 key 全 ***）。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "******"
    return f"{key[:4]}***{key[-4:]}"
