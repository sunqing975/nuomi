"""全局配置：从环境变量 / 仓库根 .env 读取，LLM 提供商可切换（DeepSeek / 豆包 / 任意 OpenAI 兼容）。

单一数据根（决策 5，见 docs/desktop-data-architecture.md）：
- 所有运行时数据锚定 NUOMI_HOME（默认 ~/Library/Application Support/Nuomi / ~/.nuomi），
  开发、打包、桌面端同源，不做 dev/packaged 双 profile。
- 资源目录（plugins/partners）源码运行默认仓库路径，打包形态由 sidecar 用
  PLUGINS_DIR / PARTNERS_DIR 覆盖（指向 PyInstaller 只读资源区）。
- 工作区默认 ~/Documents/Nuomi（用户可见），可用 NUOMI_WORKSPACE 覆盖。
"""
from __future__ import annotations

import os
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

    # --- LLM（OpenAI 兼容） ---
    # 默认 DeepSeek：base_url=https://api.deepseek.com，model=deepseek-chat
    # 换豆包(火山方舟)：base_url=https://ark.cn-beijing.volces.com/api/v3，model=你的接入点ID
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY", "ARK_API_KEY"),
    )
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.7

    # --- 单一数据根（NUOMI_HOME；不设置则用默认用户应用数据目录） ---
    nuomi_home: str | None = None

    # --- 统一插件根目录（源码默认仓库 plugins/；打包 sidecar 用 PLUGINS_DIR 覆盖） ---
    plugins_dir: str = str(REPO_ROOT / "plugins")
    # --- 伙伴目录（同理，PARTNERS_DIR 覆盖） ---
    partners_dir: str = str(REPO_ROOT / "partners")

    # --- 伙伴与记忆 ---
    partner_name: str = "nuomi"
    summarize_max_messages: int = 24  # 历史超过此条数触发摘要
    summarize_keep_recent: int = 8  # 摘要时保留最近 N 条原文

    # --- 知识库 RAG（Phase 2） ---
    # knowledge_store: chroma(默认，fastembed+bge-small-zh) / lexical(确定性词法实现，离线/测试用)
    knowledge_store: str = "chroma"
    # 模型下载走国内镜像（实测直连 huggingface 超时）；可通过环境变量覆盖
    hf_endpoint: str = "https://hf-mirror.com"

    # --- 可观测 + 人机回环（Phase 3） ---
    auto_approve: bool = False  # True=高风险工具直接执行（测试/演示用），False=进审批门

    # --- 全能化执行能力（Phase 5） ---
    # 工作区根：用户可见、可改（~/Documents/Nuomi）；NUOMI_WORKSPACE / WORKSPACE_DIR 覆盖
    workspace_dir: str = Field(
        default="~/Documents/Nuomi",
        validation_alias=AliasChoices("NUOMI_WORKSPACE", "WORKSPACE_DIR"),
    )
    # shell 默认沙箱模式：read-only / workspace-write / full-access
    shell_default_mode: str = "workspace-write"
    # shell 命令默认超时（秒）与输出上限（字符）
    shell_timeout: float = 30.0
    shell_max_output: int = 8000

    # --- 存储（默认全部派生自 NUOMI_HOME；仍可用 DB_PATH / TRACE_FILE 覆盖） ---
    db_path: str | None = None  # 统一 SQLite（checkpointer + 项目/会话 + 记忆 + 设置）
    trace_file: str | None = None

    # --- 桌面 sidecar 本地 token（阶段 C） ---
    # 显式设置 NUOMI_TOKEN 强制启用校验；未设置且打包（frozen）时后端自动生成/复用
    # NUOMI_HOME/.api-token 并启用；dev（源码运行）默认不校验，不影响 vite 代理。
    api_token: str | None = None

    # --- CORS ---
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # ---------- 路径解析（单一数据根） ----------

    @property
    def data_root(self) -> Path:
        if self.nuomi_home:
            return Path(self.nuomi_home).expanduser()
        return default_data_root()

    def resolve(self, rel: str) -> Path:
        """相对路径一律锚定数据根；绝对路径（含 ~）原样使用。"""
        p = Path(rel).expanduser()
        return p if p.is_absolute() else self.data_root / p

    @property
    def db_file(self) -> Path:
        return self.resolve(self.db_path or "nuomi.db")

    @property
    def memory_file(self) -> Path:
        """记忆落统一库（facts 表）——兼容旧名，实为 db_file。"""
        return self.db_file

    @property
    def knowledge_path(self) -> Path:
        return self.resolve("knowledge") / self.partner_name

    @property
    def trace_path(self) -> Path:
        return self.resolve(self.trace_file or "logs/trace.jsonl")

    @property
    def profile_path(self) -> Path:
        """V3 插件组合配置（composer 读写）。"""
        return self.data_root / "nuomi.json"

    @property
    def workspace_path(self) -> Path:
        """工作区根（shell/fs 工具沙箱锚点；自动创建）。

        优先级：NUOMI_WORKSPACE / WORKSPACE_DIR 环境变量（部署/打包覆盖）
        > settings.global.workspace_dir（首启向导保存，运行时注入 _workspace_override）
        > 默认 ~/Documents/Nuomi。
        """
        env_set = "NUOMI_WORKSPACE" in os.environ or "WORKSPACE_DIR" in os.environ
        raw = self.workspace_dir if env_set else getattr(self, "_workspace_override", None) or self.workspace_dir
        p = Path(raw).expanduser()
        if not p.is_absolute():
            p = self.data_root / p
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
