"""octop-harness 最小验证（smoke test）：DeepSeek Agent + Octop 插件加载。

验证目标：
1. octop-harness 在 nuomi venv 可独立运行（不依赖 Octop 本体）
2. DeepSeek（OpenAI 兼容协议）通道可对话（流式 + 用量）
3. Octop 插件目录（plugin.yaml + main.py）直接加载、工具注册

用法：backend/ 下 `.venv/bin/python probe_harness.py`
     （第 3 项需要一个 Octop 源码 checkout 提供示例插件；用 OCTOP_SRC 指定，
       默认取 nuomi 仓库的同级目录 ../Octop，找不到则跳过该项并打印 [skip]）
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from pathlib import Path

# 仓库根（backend/probe_harness.py -> parents: [backend, nuomi]）
REPO_ROOT = Path(__file__).resolve().parents[1]

# 载入 nuomi 的 .env（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL）
ENV_PATH = REPO_ROOT / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# 下面的 E402 是刻意的：必须先加载 .env 再 import harness（harness 在 import 期读环境变量），
# 与 backend/scripts/import_octop_expert.py 的 sys.path 注入同理。
from octop_harness import (  # noqa: E402
    ChatRequest,
    HarnessAgent,
    HarnessAgentConfig,
    init_workspace,
)
from octop_harness.config import ModelConfig, ProviderConfig  # noqa: E402
from octop_harness.plugins.loader import load_all  # noqa: E402
from octop_harness.plugins.registry import PluginRegistry  # noqa: E402


async def main() -> None:
    base_url = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
    model_id = os.environ.get("LLM_MODEL", "deepseek-chat")
    assert api_key, "LLM_API_KEY / DEEPSEEK_API_KEY 未设置"

    ws = Path(tempfile.mkdtemp(prefix="nuomi-harness-"))
    init_workspace(ws, language="zh", include_md_files=False, include_skills=False)

    # 1) 拷贝 Octop 内置插件 what-to-eat 到插件目录
    # Octop 源码位置：优先 OCTOP_SRC 环境变量，默认取 nuomi 仓库的同级目录 ../Octop
    # （本机开发常见布局是 projects/code/{nuomi,Octop} 并排 clone，故默认值不写死个人路径；
    #   没有 Octop checkout 的机器跳过第 3 项验证，不影响 harness 对话验证）
    plugins_root = ws / "plugins"
    plugins_root.mkdir(parents=True, exist_ok=True)
    octop_repo = Path(os.environ.get("OCTOP_SRC") or REPO_ROOT.parent / "Octop").expanduser()
    src_plugin = octop_repo / "src/octop/infra/agents/plugins/bundled/what-to-eat"

    if src_plugin.is_dir():
        shutil.copytree(src_plugin, plugins_root / "what-to-eat", dirs_exist_ok=True)

        # 2) 加载插件（harness 全局 PluginRegistry）
        loaded = load_all(plugins_root, install_deps=False)
        tool_names = [t.name for t in PluginRegistry().all_tools()]
        assert [p.manifest.id for p in loaded] == ["what-to-eat"], "插件加载失败"
        assert tool_names == ["what_to_eat"], f"工具注册异常: {tool_names}"
        print(f"[ok] 插件加载: {[p.manifest.id for p in loaded]}")
        print(f"[ok] 注册工具: {tool_names}")
    else:
        print(f"[skip] 未找到 Octop 内置插件目录：{src_plugin}")
        print("       （该目录来自 Octop 源码 checkout，可用 OCTOP_SRC=/path/to/Octop 指定）")
        print("       跳过「Octop 插件直接加载」验证，继续验证 harness 对话链路")

    # 3) 构造 Agent（DeepSeek OpenAI 兼容）
    provider = ProviderConfig(
        id="deepseek",
        base_url=base_url,
        api_key=api_key,
        protocol="openai",
        models=[ModelConfig(id=model_id, name=model_id)],
    )
    cfg = HarnessAgentConfig(
        name="nuomi-probe",
        workspace_dir=ws,
        providers=[provider],
        default_model=f"deepseek/{model_id}",
    )
    agent = HarnessAgent(cfg)

    # 4) 对话：流式输出
    request = ChatRequest(messages="你好，用一句话回复", thread_id="probe-1")
    text_parts: list[str] = []
    usage: dict = {}
    async for event in agent.stream(request):
        ev = event.get("type")
        ev_name = getattr(ev, "value", ev)
        if ev_name == "token" and event.get("content"):
            text_parts.append(event["content"])
        elif ev_name == "usage":
            usage = event.get("usage") or {}

    agent.close()
    answer = "".join(text_parts).strip()
    assert answer, "模型无输出"
    print(f"[ok] 对话: {answer[:80]}")
    print(f"[ok] 用量: input={usage.get('input_tokens')} output={usage.get('output_tokens')}")
    plugin_part = "、Octop 插件可直接加载" if src_plugin.is_dir() else "（Octop 插件环节已跳过）"
    print(f"[ok] 验证通过 —— harness 可独立运行、DeepSeek 可对话{plugin_part}")


if __name__ == "__main__":
    asyncio.run(main())
