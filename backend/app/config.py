"""全局配置：从仓库根 .env 读取（LLM 提供商、数据根、工作区）。

v0.13 起配置大幅精简：自研 engine 已删除，LLM 提供商交给 octop-harness
（ProviderConfig/ModelConfig 映射见 infra/harness/config.py）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents: [app, backend, nuomi(仓库根)]
REPO_ROOT = Path(__file__).resolve().parents[2]


def default_data_root() -> Path:
    """NUOMI_HOME 未设置时的默认值（macOS 惯例 Application Support）。"""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Nuomi"
    return Path.home() / ".nuomi"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM（OpenAI 兼容；DeepSeek 默认，可换豆包火山方舟/任意兼容端点） ---
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY", "ARK_API_KEY"),
    )
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.7

    # --- 单一数据根（NUOMI_HOME；不设置则用默认用户应用数据目录） ---
    nuomi_home: str | None = None

    # --- CORS（默认**空**：不给任何跨源页面回显 ACAO）---
    # 为什么留空：生产面板由后端同源挂载（main.py 的 /console），dev 走 vite proxy
    # （frontend/vite.config.ts 把 /api 转发到 127.0.0.1:8000），两条路都不是跨源请求。
    # 之前默认放行 5173 的实际后果（2026-10-15 实测）：带 Origin: http://localhost:5173
    # 请求 GET /api/session-token 会回显 access-control-allow-origin —— 任何占住本机
    # 5173 的页面都能跨源读走写操作 token，再 POST /api/plugins/import 即本机代码执行。
    # 真需要跨源调试时显式开（无 env_prefix，list 型要写 JSON）：
    #   CORS_ORIGINS=["http://localhost:5173"]
    # 注意 local_guard.origin_allowed 仍按主机名放行本机任意端口 → dev 写操作不受影响。
    cors_origins: list[str] = Field(default_factory=list)

    # --- 连接器（MCP 协议，langchain-mcp-adapters 连接格式；JSON env NUOMI_CONNECTORS） ---
    mcp_servers: dict[str, dict] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("NUOMI_CONNECTORS", "NUOMI_MCP_SERVERS"),
    )

    # --- SkillHub 技能市场（默认腾讯市场，可用 SKILLHUB_HOST 覆盖） ---
    skillhub_host: str = ""

    @property
    def data_root(self) -> Path:
        if self.nuomi_home:
            return Path(self.nuomi_home).expanduser()
        return default_data_root()

    def resolve(self, rel: str) -> Path:
        p = Path(rel).expanduser()
        return p if p.is_absolute() else self.data_root / p

    @property
    def workspace_path(self) -> Path:
        """工作区根（Agent 沙箱锚点；单根设计 = 数据根本身，2026-10-04 起）。"""
        p = self.data_root
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
