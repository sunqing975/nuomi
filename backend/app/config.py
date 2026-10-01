"""全局配置：从环境变量 / 仓库根 .env 读取，LLM 提供商可切换（DeepSeek / 豆包 / 任意 OpenAI 兼容）。"""
from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> parents: [app, backend, nuomi(仓库根)]
REPO_ROOT = Path(__file__).resolve().parents[2]


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

    # --- 存储 ---
    # 相对路径以 backend/ 为基准（由下方 to_absolute 解析）
    db_path: str = "data/nuomi.sqlite"

    # --- 统一插件根目录（一个插件 = 一个目录 + plugin.json，type 区分能力/程序） ---
    plugins_dir: str = str(REPO_ROOT / "plugins")

    # --- 伙伴与记忆（Phase 1） ---
    partner_name: str = "nuomi"
    partners_dir: str = str(REPO_ROOT / "partners")
    memory_dir: str = "data/memories"  # 相对 backend/
    summarize_max_messages: int = 24  # 历史超过此条数触发摘要
    summarize_keep_recent: int = 8  # 摘要时保留最近 N 条原文

    # --- 知识库 RAG（Phase 2） ---
    # knowledge_store: chroma(默认，fastembed+bge-small-zh) / lexical(确定性词法实现，离线/测试用)
    knowledge_store: str = "chroma"
    knowledge_dir: str = "data/knowledge"  # 相对 backend/
    # 模型下载走国内镜像（实测直连 huggingface 超时）；可通过环境变量覆盖
    hf_endpoint: str = "https://hf-mirror.com"

    # --- 可观测 + 人机回环（Phase 3） ---
    trace_file: str = "data/logs/trace.jsonl"  # 相对 backend/
    auto_approve: bool = False  # True=高风险工具直接执行（测试/演示用），False=进审批门

    # --- 全能化执行能力（Phase 5） ---
    # shell/fs 工具的沙箱工作区根（相对 backend/；shell 默认 cwd、fs 路径边界都锚定这里）
    workspace_dir: str = "data/workspace"
    # shell 默认沙箱模式：read-only / workspace-write / full-access
    shell_default_mode: str = "workspace-write"
    # shell 命令默认超时（秒）与输出上限（字符）
    shell_timeout: float = 30.0
    shell_max_output: int = 8000

    # --- 多用户（Phase 4a） ---
    # checkpointer: sqlite（开发默认）/ postgres（多用户，PostgresSaver）
    checkpointer: str = "sqlite"
    pg_dsn: str = "postgresql://localhost:5432/nuomi"  # 本机 brew PG，trust 认证
    auth_enabled: bool = False  # True=登录+JWT，/api/chat 需 Bearer token
    jwt_secret: str = "nuomi-dev-secret-change-in-prod"
    jwt_expire_days: int = 7
    users_file: str = "data/users.json"  # 相对 backend/

    # --- CORS ---
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else Path(__file__).resolve().parents[1] / p

    @property
    def db_file(self) -> Path:
        return self.resolve(self.db_path)

    @property
    def memory_file(self) -> Path:
        return self.resolve(self.memory_dir) / self.partner_name / "facts.json"

    @property
    def knowledge_path(self) -> Path:
        return self.resolve(self.knowledge_dir) / self.partner_name

    @property
    def trace_path(self) -> Path:
        return self.resolve(self.trace_file)

    @property
    def users_path(self) -> Path:
        return self.resolve(self.users_file)

    @property
    def workspace_path(self) -> Path:
        """shell/fs 工具的工作区根（自动创建）。"""
        p = self.resolve(self.workspace_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
