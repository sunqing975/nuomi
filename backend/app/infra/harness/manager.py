"""Agent 生命周期：HarnessManager 单例，负责创建/复用/关闭 HarnessAgent。

对齐 Octop 的 HarnessAgentManager 语义（单例 + DB↔runtime 同步），nuomi 最小版
为单 Agent 常驻（个人助理场景），后续多专家时扩展为按 expert_id 管理实例。
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from octop_harness import HarnessAgent

from app.config import settings
from app.infra.harness.config import build_agent_config

if TYPE_CHECKING:
    from pathlib import Path


class HarnessManager:
    """单例：持有当前 Agent 实例，串行化对话（单用户桌面场景足够）。"""

    def __init__(self) -> None:
        self._agent: HarnessAgent | None = None
        self._lock = asyncio.Lock()

    @property
    def workspace(self) -> Path:
        return settings.workspace_path

    def get_agent(self) -> HarnessAgent:
        """懒创建 Agent（工作区按 harness 约定初始化）。"""
        if self._agent is None:
            cfg = build_agent_config(self.workspace)
            self._agent = HarnessAgent(cfg)
        return self._agent

    def close(self) -> None:
        """关闭 Agent（进程退出时调用）。"""
        if self._agent is not None:
            try:
                self._agent.close()
            except Exception:
                pass  # 关闭阶段异常可忽略
            self._agent = None


manager = HarnessManager()
