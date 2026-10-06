"""pytest 根配置：隔离数据根（NUOMI_HOME → 临时目录）+ 内建 Provider/Token fixture。

- **Provider fixture**：``build_providers()`` 在没有 ``providers.json`` 时会回退 `.env`
  种子，而干净检出（尤其 CI）没有可用的 ``LLM_API_KEY`` → ``ProviderConfig`` 构造
  抛 ``api_key is required``。这里直接写一份测试用 providers.json，测试不再依赖
  本机 `.env` 或真实密钥（真实 LLM 调用本来也不该出现在单元测试里）。
- **API token**：写操作要带 ``X-Nuomi-Token``（``app/infra/local_guard.py``）。固定成
  已知值并由 TestClient 默认带上，用例无需关心。
- **真实模型缓存**：通过 symlink 复用本机已下载的 embedding 缓存（避免 103MB 下载）。
  路径可用 ``NUOMI_REAL_MODELS`` 覆盖，默认取 NUOMI_HOME 惯例位置，不写死个人路径。
- 注意：模块顶层先于任何 app import 执行（pytest 先加载 conftest 再收集测试）。
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path

TEST_TOKEN = "nuomi-test-token"

_HOME = Path(tempfile.mkdtemp(prefix="nuomi-test-home-"))
os.environ["NUOMI_HOME"] = str(_HOME)
os.environ["NUOMI_API_TOKEN"] = TEST_TOKEN

# 内建 Provider：不需要真实密钥（测试不发起真实 LLM 请求）
(_HOME / "providers.json").write_text(
    json.dumps(
        {
            "providers": [
                {
                    "id": "test",
                    "name": "测试 Provider",
                    "base_url": "http://127.0.0.1:9/v1",
                    "api_key": "test-key",
                    "protocol": "openai",
                    "models": [{"id": "test-model", "name": "test-model"}],
                }
            ]
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)

_DEFAULT_REAL_MODELS = Path.home() / "Nuomi" / "models" / "ai" / "embedding"
_REAL_MODELS = Path(os.environ.get("NUOMI_REAL_MODELS") or _DEFAULT_REAL_MODELS)
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
    """FastAPI TestClient（触发 lifespan：建库 + 种子糯米 + 恢复索引任务）。

    base_url 用回环地址（``Host`` 白名单要求）；默认带 API token（写操作需要）。
    """
    from app.main import app

    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        headers={"X-Nuomi-Token": TEST_TOKEN},
    ) as c:
        yield c


@pytest.fixture
def stub_llm(monkeypatch):
    """把对话链路的 LLM 事件流换成固定帧（路由级用例不该真的打模型）。

    背景：``test_chat_route_*`` 只断言状态码/Content-Type（用例自述"不校验推理内容"），
    但真实链路会去打 provider —— 没有密钥时报 ``api_key is required``，有密钥时
    真花钱，连到不通的端点还会触发 SDK 重试（实测每个用例 30s+）。
    这里只替换 nuomi 自己的边界（两个 transport 模块里的 ``stream_chat`` 名），
    不侵入 harness 内部实现。
    """

    async def fake_stream(*_args, **_kwargs):
        yield {"type": "token", "content": "stub"}
        yield {"type": "done", "answer": "stub"}

    import app.transport.api as api_mod
    import app.transport.openai_compat as compat_mod

    monkeypatch.setattr(api_mod, "stream_chat", fake_stream)
    monkeypatch.setattr(compat_mod, "stream_chat", fake_stream)
    return fake_stream
