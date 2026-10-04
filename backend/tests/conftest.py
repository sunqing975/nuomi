"""pytest 根配置：知识库 API 测试使用隔离数据根（NUOMI_HOME → 临时目录）。

真实模型缓存通过 symlink 复用（测试内不做 103MB 下载）；symlink 指向
/Users/superman/Nuomi/models/ai/embedding（本机已下载 bge-small-zh-v1.5）。
注意：模块顶层先于任何 app import 执行（pytest 先加载 conftest 再收集测试）。
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path

_HOME = Path(tempfile.mkdtemp(prefix="nuomi-test-home-"))
os.environ["NUOMI_HOME"] = str(_HOME)

_REAL_MODELS = Path("/Users/superman/Nuomi/models/ai/embedding")
if _REAL_MODELS.is_dir():
    target = _HOME / "models" / "ai" / "embedding"
    target.parent.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        target.symlink_to(_REAL_MODELS, target_is_directory=True)  # 已存在/无权限则跳过

atexit.register(shutil.rmtree, _HOME, ignore_errors=True)


import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient（触发 lifespan：建库 + 种子糯米 + 恢复索引任务）。"""
    from app.main import app

    with TestClient(app) as c:
        yield c
