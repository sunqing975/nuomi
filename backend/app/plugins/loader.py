"""统一扩展体系 · 加载器 v0.7.1（对齐 Octop：插件 / 技能 / 模块三区分离）。

v0.7 核心变化（回应"插件概念模糊"）：
- **插件（plugins/）**= 分发单元，给 LLM 注册工具（Octop 插件语义）。
- **技能（skills/）**= 独立文档资产：skills/<name>/SKILL.md，不随插件目录走。
- **模块（backend/app/modules/）**= 内核组成部分（service-*、preset、hook 类），
  概念上不再是"可选用能力"，但加载机制与插件一致（apply(ctx) 声明贡献）。
- 三种概念三种清单（v0.7.1，格式随概念分离）：
  插件 → plugins/<name>/plugin.json（能力导向：entry/load/robust/approval/system_instruction）
  模块 → modules/<name>/module.json（内核导向：provides[]/hooks[] 声明式 + entry）
  技能 → skills/<name>/SKILL.md（frontmatter 即清单）
- 启停 = 配置组合：启用 apply(ctx) 重新贡献，停用 dispose 后重建。

三级加载（对齐 Harness ctx.skills）：
  级1 元数据常驻：启动只读清单 + skills/*/SKILL.md 的 name/description 建目录（注入 system prompt）
  级2 指令触发：模型通过 skill 工具按需读取 SKILL.md 全文（正文不进常驻上下文）
  级3 资源按需：重资源在首次工具调用时初始化并缓存（MCP 连接 / embedding / Chroma）
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool

SKILL_MD_NAME = "SKILL.md"


@dataclass
class PluginDescriptor:
    """一个插件/模块目录的元数据 + 贡献收集结果（apply(ctx) 后填充）。"""

    name: str
    version: str
    description: str
    path: Path | None = None
    meta: dict = field(default_factory=dict)
    error: str | None = None
    category: str = "plugin"  # plugin（可选用能力）| module（内核组成部分）
    # 声明式元数据（v0.7.1，manifest 驱动）：module.json 的 provides[] / hooks[]
    provides: list[str] = field(default_factory=list)  # 声明提供的 ctx 服务
    hooks: list[str] = field(default_factory=list)  # 声明订阅的事件
    # apply(ctx) 之后由 ctx 收集的运行时贡献：
    tools: list[BaseTool] = field(default_factory=list)
    skill_body: str = ""  # SKILL.md 正文
    skill_when_to_use: str = ""
    services: list[str] = field(default_factory=list)  # 注册的服务名（声明 ∪ 运行时）
    events: list[str] = field(default_factory=list)  # 订阅的事件名（声明 ∪ 运行时）

    @property
    def is_program(self) -> bool:
        """v0.6 兼容遗留：type 字段已废弃，不再用任何类型硬区分加载路径。"""
        return False

    def has_tools(self) -> bool:
        return bool(self.tools)

    def has_skill(self) -> bool:
        return bool(self.skill_body)


@dataclass
class SkillDescriptor:
    """技能区（skills/）里一个 SKILL.md 的元数据 + 正文（三级加载级2 按需读取）。"""

    name: str
    description: str
    body: str = ""
    when_to_use: str = ""
    path: Path | None = None


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
    except Exception:
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


# 概念→清单格式（v0.7.1 对齐 Octop 声明式领域）：
# 插件（可选用能力）→ plugin.json（能力导向：entry/load/robust/approval/system_instruction）
# 模块（内核组成部分）→ module.json（内核导向：provides[]/hooks[] 声明式 + entry）
# 技能（文档资产）→ skills/<name>/SKILL.md（frontmatter 即清单）
MANIFEST_NAMES = {"plugin": "plugin.json", "module": "module.json"}


def scan_plugins(plugins_dir: str | Path, category: str = "plugin") -> list[PluginDescriptor]:
    """级1：扫 <dir>/*/<manifest> 建元数据注册表（不 import 任何入口代码）。

    category="plugin" → 读 plugin.json（能力导向 manifest）
    category="module" → 读 module.json（内核导向 manifest：provides/hooks 声明式）
    对齐 Harness：目录携带 name+description 建注册表，apply 在启用时执行。
    """
    root = Path(plugins_dir)
    if not root.is_dir():
        return []
    manifest_name = MANIFEST_NAMES.get(category, "plugin.json")
    loaded: list[PluginDescriptor] = []
    for manifest in sorted(root.glob(f"*/{manifest_name}")):
        plugin_dir = manifest.parent
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception as e:
            loaded.append(
                PluginDescriptor(
                    plugin_dir.name, "", "", path=plugin_dir, error=f"{manifest_name} 解析失败: {e}"
                )
            )
            continue

        body = ""
        when = ""
        skill_md = plugin_dir / SKILL_MD_NAME
        if skill_md.exists():
            body = skill_md.read_text(encoding="utf-8")
            body, fm = _parse_frontmatter(body)
            when = fm.get("when_to_use", "") or fm.get("when-to-use", "")

        # 模块：声明式 provides/hooks（元数据常驻，扫描期即可见；apply 后与运行时合并）
        provides: list[str] = []
        hooks: list[str] = []
        if category == "module":
            provides = [str(s) for s in meta.get("provides", []) if s]
            hooks = [str(h) for h in meta.get("hooks", []) if h]

        loaded.append(
            PluginDescriptor(
                name=str(meta.get("name", plugin_dir.name)),
                version=str(meta.get("version", "")),
                description=str(meta.get("description", "")),
                path=plugin_dir,
                meta=meta,
                category=category,
                provides=provides,
                hooks=hooks,
                skill_body=body,
                skill_when_to_use=when,
            )
        )
    return loaded


def scan_skills(skills_dir: str | Path) -> list[SkillDescriptor]:
    """级1：扫 skills/*/SKILL.md 建技能注册表（独立技能区，正文按需读取）。

    技能是独立概念（对齐 Octop skill）：与插件解耦，目录只给 name+description。
    """
    root = Path(skills_dir)
    if not root.is_dir():
        return []
    out: list[SkillDescriptor] = []
    for skill_md in sorted(root.glob(f"*/{SKILL_MD_NAME}")):
        try:
            body = skill_md.read_text(encoding="utf-8")
        except Exception:
            continue
        body, fm = _parse_frontmatter(body)
        out.append(
            SkillDescriptor(
                name=str(fm.get("name", skill_md.parent.name)),
                description=str(fm.get("description", "")),
                body=body,
                when_to_use=str(fm.get("when_to_use", "") or fm.get("when-to-use", "")),
                path=skill_md.parent,
            )
        )
    return out


def collect_tools(
    plugins: list[PluginDescriptor], enabled: set[str] | None = None
) -> list[BaseTool]:
    """汇总全部插件贡献的工具（v0.6：来自 apply(ctx) 后的 ctx.tools，无类型过滤）。

    统一健壮层：按清单的 robust 配置包装（重试/超时/fallback）；
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
    """插件自述"什么时候该用我"（清单的 system_instruction 字段），注入 system prompt。"""
    return [
        str(p.meta.get("system_instruction", ""))
        for p in plugins
        if not p.error and p.meta.get("system_instruction")
    ]


def collect_skill_catalog(skills: list[SkillDescriptor], enabled: set[str] | None = None) -> str:
    """对齐 Harness 会话目录：只含 name + description（转义），不含正文/路径。

    作为 `<available_skills>` 注入 system prompt，模型据此决定何时用 skill 工具读正文。
    技能是独立概念，默认全量可见；enabled 参数保留用于将来按所属能力过滤。
    """
    lines = []
    for s in skills:
        if not s.body:
            continue
        if enabled is not None and s.name not in enabled:
            continue
        desc = s.description.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        line = f'<skill name="{s.name}"> {desc}'
        if s.when_to_use:
            line += f" 何时用：{s.when_to_use}"
        lines.append(line + "</skill>")
    return "\n".join(lines)
