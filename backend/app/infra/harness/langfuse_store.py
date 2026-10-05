"""Langfuse 观测配置存储：{workspace}/langfuse.json（单根工作区）。

- 运行时配置为权威（控制台「设置 → Langfuse」可改）；不设 env 种子
- 保存后热更新 harness 的 LangfuseTracer（即时生效，无需重启实例）
- 安全：secret_key 明文存工作区（仓库外，不进 git）；对外接口层负责脱敏
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config import settings

LANGFUSE_FILE_NAME = "langfuse.json"

DEFAULT_HOST = "https://cloud.langfuse.com"


def path() -> Path:
    return settings.workspace_path / LANGFUSE_FILE_NAME


def load() -> dict:
    """读 langfuse.json；缺失/损坏返回空配置（未启用）。"""
    p = path()
    if not p.is_file():
        return {
            "enabled": False,
            "public_key": "",
            "host": DEFAULT_HOST,
            "secret_key": "",
        }
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "enabled": bool(data.get("enabled", False)),
        "public_key": str(data.get("public_key") or "").strip(),
        "host": str(data.get("host") or "").strip() or DEFAULT_HOST,
        "secret_key": str(data.get("secret_key") or "").strip(),
    }


def save(config: dict) -> dict:
    path().write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config


def mask_secret(secret: str) -> str:
    """secret_key 脱敏：首 4 + *** + 尾 4（短 key 全 ***）。"""
    if not secret:
        return ""
    if len(secret) <= 8:
        return "******"
    return f"{secret[:4]}***{secret[-4:]}"
