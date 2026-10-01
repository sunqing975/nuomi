"""统一插件体系 · 加载器 v0.6（完整对齐 DeepSeek Harness / Cordis）。

v0.6 核心变化（回应架构问题）：
- **不再区分"能力型/程序型"**——一切皆插件，apply(ctx) 声明贡献（工具/技能/服务/事件）。
  区别只在于注册了什么，加载路径只有一条。
- 插件形态：plugins/<name>/plugin.json（元数据）+ hook.py（入口 apply(ctx)）
  + SKILL.md（可选：技能说明书，目录只给 name+description，正文按需）
- 启停 = 配置组合：启用 apply(ctx) 重新贡献，停用 dispose 后重建。

三级加载（对齐 Harness ctx.skills）：
  级1 元数据常驻：启动只读 plugin.json + SKILL.md 的 name/description 建目录（注入 system prompt）
  级2 指令触发：模型通过 skill 工具按需读取 SKILL.md 全文（正文不进常驻上下文）
  级3 资源按需：重资源在首次工具调用时初始化并缓存（MCP 连接 / embedding / Chroma）
"""
from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool, tool

SKILL_MD_NAME = "SKILL.md"


@dataclass
class PluginDescriptor:
    """一个插件目录的元数据 + 贡献收集结果（apply(ctx) 后填充）。"""

    name: str
    version: str
    description: str
    path: Path | None = None
    meta: dict = field(default_factory=dict)
    error: str | None = None
    # apply(ctx) 之后由 ctx 收集的贡献：
    tools: list[BaseTool] = field(default_factory=list)
    skill_body: str = ""  # SKILL.md 正文
    skill_when_to_use: str = ""
    services: list[str] = field(default_factory=list)  # 注册的服务名
    events: list[str] = field(default_factory=list)  # 订阅的事件名

    @property
    def is_program(self) -> bool:
        """v0.6 兼容遗留：type 字段已废弃，不再用任何类型硬区分加载路径。"""
        return False

    def has_tools(self) -> bool:
        return bool(self.tools)

    def has_skill(self) -> bool:
        return bool(self.skill_body)


def _load_module(plugin_dir: Path, entry: str):
    """按路径加载插件入口模块（每次新建，避免命名冲突）。"""
    mod_path = plugin_dir / entry
    if not mod_path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f"nuomi_plugin_{plugin_dir.name}", mod_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        return None
    return module


def _parse_frontmatter(body: str) -> tuple[str, dict]:
    """解析 SKILL.md 的 YAML frontmatter（--- ... --- 块）。返回 (剩余正文, 元数据)。"""
    text = body.lstrip("\ufeff")
    if not text.startswith("---"):
        return body, {}
    end = text.find("\n---", 3)
    if end == -1:
        return body, {}
    fm_text = text[3:end].strip()
    rest = text[end + 4 :].lstrip("\n")
    meta: dict = {}
    for line in fm_text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return rest, meta


def scan_plugins(plugins_dir: str | Path) -> list[PluginDescriptor]:
    """级1：扫 plugins/*/plugin.json 建元数据注册表（不 import 任何入口代码）。

    对齐 Harness：目录携带 name+description 建注册表，apply 在启用时执行。
    """
    root = Path(plugins_dir)
    if not root.is_dir():
        return []
    loaded: list[PluginDescriptor] = []
    for plugin_json in sorted(root.glob("*/plugin.json")):
        plugin_dir = plugin_json.parent
        try:
            meta = json.loads(plugin_json.read_text(encoding="utf-8"))
        except Exception as e:
            loaded.append(
                PluginDescriptor(plugin_dir.name, "", "", path=plugin_dir, error=f"plugin.json 解析失败: {e}")
            )
            continue

        body = ""
        when = ""
        skill_md = plugin_dir / SKILL_MD_NAME
        if skill_md.exists():
            body = skill_md.read_text(encoding="utf-8")
            body, fm = _parse_frontmatter(body)
            when = fm.get("when_to_use", "") or fm.get("when-to-use", "")

        loaded.append(
            PluginDescriptor(
                name=str(meta.get("name", plugin_dir.name)),
                version=str(meta.get("version", "")),
                description=str(meta.get("description", "")),
                path=plugin_dir,
                meta=meta,
                skill_body=body,
                skill_when_to_use=when,
            )
        )
    return loaded


def collect_tools(
    plugins: list[PluginDescriptor], enabled: set[str] | None = None
) -> list[BaseTool]:
    """汇总全部插件贡献的工具（v0.6：来自 apply(ctx) 后的 ctx.tools，无类型过滤）。

    统一健壮层：按 plugin.json 的 robust 配置包装（重试/超时/fallback）；
    按 approval 列表把高风险工具包进审批门（human-in-the-loop）。
    """
    from .approval import get_gate
    from .robust import apply_robust

    out: list[BaseTool] = []
    for p in plugins:
        if enabled is not None and p.name not in enabled:
            continue
        if p.error:
            continue
        robust_cfg = p.meta.get("robust") or {}
        approval_names = set(p.meta.get("approval") or [])
        gate = get_gate()
        for t in p.tools:
            wrapped = apply_robust(t, robust_cfg)
            if t.name in approval_names:
                gate.register_tools([wrapped])  # 审批通过后执行"未包审批门"的版本
                wrapped = gate.wrap(wrapped)
            out.append(wrapped)
    return out


def collect_instructions(plugins: list[PluginDescriptor]) -> list[str]:
    """插件自述"什么时候该用我"（plugin.json 的 system_instruction 字段），注入 system prompt。"""
    return [
        str(p.meta.get("system_instruction", ""))
        for p in plugins
        if not p.error and p.meta.get("system_instruction")
    ]


def collect_skill_catalog(plugins: list[PluginDescriptor], enabled: set[str] | None = None) -> str:
    """对齐 Harness 会话目录：只含 name + description（转义），不含正文/路径。

    作为 `<available_skills>` 注入 system prompt，模型据此决定何时用 skill 工具读正文。
    """
    lines = []
    for p in plugins:
        if p.error or not p.skill_body:
            continue
        if enabled is not None and p.name not in enabled:
            continue
        desc = p.description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        line = f"<skill name=\"{p.name}\"> {desc}"
        if p.skill_when_to_use:
            line += f" 何时用：{p.skill_when_to_use}"
        lines.append(line + "</skill>")
    return "\n".join(lines)
