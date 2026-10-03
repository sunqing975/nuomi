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

    # --- 工作区根：用户可见（~/Documents/Nuomi），NUOMI_WORKSPACE 覆盖 ---
    workspace_dir: str = Field(
        default="~/Documents/Nuomi",
        validation_alias=AliasChoices("NUOMI_WORKSPACE", "WORKSPACE_DIR"),
    )

    # --- CORS（桌宠前端 dev） ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

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
        """工作区根（Agent 沙箱锚点；自动创建）。"""
        p = Path(self.workspace_dir).expanduser()
        if not p.is_absolute():
            p = self.data_root / p
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
