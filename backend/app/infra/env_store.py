"""应用环境变量存储（对齐 octop 应用设置：技能/连接器需要 API key 时在此配置）。

- 存储：{workspace}/env.json（单根工作区，与 connectors.json 平级）
- 启动时注入 os.environ（main lifespan 调用 apply）
- 保存后即时更新进程 env 并释放 agent 实例（下次对话生效）

安全：env.json 里是用户主动配置的密钥，不进入 git（工作区本身在仓库外）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config import settings

ENV_FILE_NAME = "env.json"


def env_path() -> Path:
    return settings.workspace_path / ENV_FILE_NAME


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
    """启动时把 env.json 注入 os.environ（应用设置为权威，覆盖同名进程变量）。"""
    for name, value in load().items():
        os.environ[name] = value


def save(values: dict[str, str]) -> dict[str, str]:
    """整体保存 env.json 并即时同步 os.environ。

    新增/更新的键写入进程 env；被删除的键（旧有而新值不含）从进程 env 移除；
    不影响 env.json 之外的系统变量（PATH、ARK_API_KEY 等）。
    """
    clean = {str(k).strip(): str(v) for k, v in values.items() if str(k).strip() and v is not None}
    old = load()
    p = env_path()
    p.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, value in clean.items():
        os.environ[name] = value
    for name in old.keys() - clean.keys():
        os.environ.pop(name, None)
    return clean
