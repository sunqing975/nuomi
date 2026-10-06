"""应用环境变量存储（对齐 octop 应用设置：技能/连接器需要 API key 时在此配置）。

- 存储：{workspace}/env.json（单根工作区，与 connectors.json 平级）
- 启动时注入 os.environ（main lifespan 调用 apply）
- 保存后即时更新进程 env 并释放 agent 实例（下次对话生效）

安全：env.json 里是用户主动配置的密钥，不进入 git（工作区本身在仓库外）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from app.config import settings
from app.infra.secret_file import tighten, write_json

ENV_FILE_NAME = "env.json"

# 疑似密钥的键名（对外展示时脱敏）。**必须锚定词边界**：不锚定的话 MONKEY、
# KEYWORD_X、TOKENIZER_PATH 都会被误判成密钥 → 被脱敏显示、且值含 *** 时被还原。
_SECRET_KEY_RE = re.compile(
    r"(^|_)(KEY|TOKEN|SECRET|PASSWORD|PASSWD|PWD|CREDENTIAL|APIKEY)(_|$)", re.IGNORECASE
)


def env_path() -> Path:
    return settings.workspace_path / ENV_FILE_NAME


def is_secret_key(name: str) -> bool:
    return bool(_SECRET_KEY_RE.search(name or ""))


def mask_value(value: str) -> str:
    """脱敏：短值全星号，长值保留首尾各 4 位（前端据此显示"已配置"）。"""
    if not value:
        return ""
    if len(value) <= 8:
        return "******"
    return f"{value[:4]}***{value[-4:]}"


def mask_all(values: dict[str, str]) -> dict[str, str]:
    """按键名判决敏（非密钥键原样返回，避免影响普通配置的可见性）。"""
    return {k: (mask_value(v) if is_secret_key(k) else v) for k, v in values.items()}


def is_masked_sentinel(value: str, current: str) -> bool:
    """``value`` 是否正好是 ``current`` 的脱敏形态（= 前端没有改动这个键）。

    不能用「值里含 ``***``」当判据：用户完全可能想把密钥改成含 ``***`` 的新值，
    那样会被静默还原成旧值（无任何提示）。这里要求**精确等于** ``mask_value(current)``，
    误判需要用户手打的字符串逐字节等于我们生成的掩码，实际不可能。
    """
    if not current:
        return False
    return bool(value) and value == mask_value(current)


def load() -> dict[str, str]:
    """读 env.json（缺失/损坏返回空）。"""
    p = env_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and str(v)}


def apply() -> None:
    """启动时把 env.json 注入 os.environ（应用设置为权威，覆盖同名进程变量）。

    同时对旧文件补一次 0600（历史版本写出来是 0644）。
    """
    tighten(env_path())
    for name, value in load().items():
        os.environ[name] = value


def save(values: dict[str, str], *, keep_masked: bool = True) -> dict[str, str]:
    """整体保存 env.json 并即时同步 os.environ（原子写 + 0600）。

    - 值为脱敏串（``***``）时视为「保持原值」——前端拿到的是脱敏值，回写不能覆盖真 key；
    - 新增/更新的键写入进程 env；被删除的键从进程 env 移除（不动系统变量）。
    """
    old = load()
    clean: dict[str, str] = {}
    for raw_key, raw_value in values.items():
        key = str(raw_key).strip()
        if not key or raw_value is None:
            continue
        value = str(raw_value)
        # 「保持原值」只在两个条件同时成立时生效：疑似密钥键 + 值精确等于旧值的脱敏形态。
        # 键名限定避免普通配置（MY_CITY）被误判；精确相等避免真实修改被静默丢弃。
        if keep_masked and is_secret_key(key) and is_masked_sentinel(value, old.get(key, "")):
            value = old[key]
        clean[key] = value

    write_json(env_path(), clean)
    for name, value in clean.items():
        os.environ[name] = value
    for name in old.keys() - clean.keys():
        os.environ.pop(name, None)
    return clean
