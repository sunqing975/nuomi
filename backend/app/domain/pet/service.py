"""桌宠模型资产管理（表现层资产，由后端统一管理）。

- 模型目录：工作区 models/2D/<model_id>/<xxx>.model3.json（2026-10-04 起，资产迁出壳仓库）
- 内置种子：仓库 assets/models/2D/<id>/（可分发内置模型；扫描时幂等播种到工作区）
- 元数据：读 model3.json 的 FileReferences.Motions/Expressions 提取动作与表情名
- 切换：更新壳 config.json 的 ui.model / ui.model_path（壳 watch 后自动重载）
- 会话状态：nuomi.* 已迁出壳 config → 工作区 nuomi-state.json（见 chat.service）
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from app.config import REPO_ROOT, settings

logger = logging.getLogger(__name__)

MODEL_DIR = settings.workspace_path / "models" / "2D"
MODEL_DIR_3D = settings.workspace_path / "models" / "3D"
SEED_MODEL_DIR = REPO_ROOT / "assets" / "models" / "2D"
SHELL_CONFIG = REPO_ROOT / "shells" / "myspy" / "config.json"
STATE_FILE = settings.workspace_path / "nuomi-state.json"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _seed_builtin_models() -> None:
    """幂等播种内置模型（仓库 assets/models/2D → 工作区 models/2D）。

    仅复制工作区中缺失的模型目录；内置模型保证至少一个桌宠可用。
    """
    if not SEED_MODEL_DIR.is_dir():
        return
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for seed_dir in sorted(SEED_MODEL_DIR.iterdir()):
        if not seed_dir.is_dir():
            continue
        target = MODEL_DIR / seed_dir.name
        if not target.exists():
            shutil.copytree(seed_dir, target)
            logger.info("播种内置模型: %s", seed_dir.name)


def _group_has_files(model_dir: Path, meta: dict, group: str) -> bool:
    """动作组引用的文件至少一个真实存在于磁盘（避免资产不完整导致的假能力）。"""
    items = ((meta.get("FileReferences") or {}).get("Motions") or {}).get(group) or []
    return any(
        (model_dir / str(it.get("File", ""))).is_file() for it in items if isinstance(it, dict)
    )


def _expression_has_file(model_dir: Path, expr: dict) -> bool:
    """表情引用文件真实存在于磁盘。"""
    file = str(expr.get("File", ""))
    return bool(file) and (model_dir / file).is_file()


def _load_actions_manifest(model_dir: Path) -> dict:
    """读模型目录的 actions.json（语义动作清单）。

    格式：{"actions": {"wave": {"motion": "main_1", "expressions": [], "label_zh": "挥手"}, ...}}
    没有文件时返回空 dict（fallback 到按 motion group 名注册工具）。
    """
    p = model_dir / "actions.json"
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("actions") or {}
    except (OSError, json.JSONDecodeError):
        return {}


def list_models() -> list[dict]:
    """扫描模型目录，返回 [{id, path, type, motions, expressions, actions}]。

    2D: models/2D/<id>/<xxx>.model3.json
    3D: models/3D/<xxx>.vrm（单个文件）
    """
    _seed_builtin_models()
    models: list[dict] = []

    # 2D Live2D 模型
    if MODEL_DIR.is_dir():
        for char_dir in sorted(MODEL_DIR.iterdir()):
            if not char_dir.is_dir():
                continue
            model_files = sorted(char_dir.glob("*.model3.json"))
            if not model_files:
                continue
            meta = _load_json(model_files[0])
            fr = meta.get("FileReferences") or {}
            motions = sorted(
                g for g in (fr.get("Motions") or {}) if _group_has_files(char_dir, meta, g)
            )
            expressions = [
                (
                    e.get("Name")
                    if isinstance(e, dict) and e.get("Name")
                    else Path(e.get("File", "")).stem
                )
                for e in (fr.get("Expressions") or [])
                if isinstance(e, dict) and _expression_has_file(char_dir, e)
            ]
            models.append(
                {
                    "id": char_dir.name,
                    "path": str(char_dir / model_files[0].name),
                    "type": "live2d",
                    "motions": motions,
                    "expressions": expressions,
                    "actions": _load_actions_manifest(char_dir),
                    "builtin": (SEED_MODEL_DIR / char_dir.name).is_dir(),
                }
            )

    # 3D VRM 模型（单个 .vrm 文件）
    if MODEL_DIR_3D.is_dir():
        for vrm_file in sorted(MODEL_DIR_3D.glob("*.vrm")):
            models.append(
                {
                    "id": vrm_file.stem,
                    "path": str(vrm_file),
                    "type": "vrm",
                    "motions": [],
                    "expressions": [],
                    "actions": {},
                    "builtin": False,
                }
            )

    return models


def get_active_model() -> str | None:
    cfg = _load_json(SHELL_CONFIG)
    return (cfg.get("ui") or {}).get("model")


def get_pet_enabled() -> bool:
    """读取桌宠开关（壳 config.json ui.pet_enabled，缺省开）。

    壳 main.js 启动时据此决定是否创建桌宠窗口；watch config 变化时
    据其创建/销毁窗口。控制台「模型」页的开关读写此字段。
    """
    cfg = _load_json(SHELL_CONFIG)
    return (cfg.get("ui") or {}).get("pet_enabled", True)


def set_pet_enabled(enabled: bool) -> bool:
    """写桌宠开关到壳 config.json（壳 watch 后创建/销毁桌宠窗口）。"""
    cfg = _load_json(SHELL_CONFIG)
    ui = cfg.setdefault("ui", {})
    ui["pet_enabled"] = bool(enabled)
    SHELL_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return ui["pet_enabled"]


def get_shell_agent_id() -> str | None:
    """桌宠对话绑定的 agent（工作区 nuomi-state.json 的 agent_id），用于联动插件激活。"""
    cfg = _load_json(STATE_FILE)
    return cfg.get("agent_id")


def switch_model(model_id: str) -> dict:
    """切换桌宠模型：更新壳 config.json 的 ui.model / ui.model_path。

    2026-10-04 起**不换会话**：桌宠=纯表现层，切换仅影响形象与插件工具集，
    当前对话线程保持不变。
    """
    target = next((m for m in list_models() if m["id"] == model_id), None)
    if target is None:
        raise KeyError(f"模型不存在: {model_id}")

    cfg = _load_json(SHELL_CONFIG)
    ui = cfg.setdefault("ui", {})
    ui["model"] = target["id"]
    ui["model_path"] = target["path"]
    ui["model_type"] = target.get("type", "live2d")
    SHELL_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def delete_model(model_id: str) -> dict:
    """删除桌宠模型（级联）：模型插件 → 资产目录 → config 联动。

    级联顺序：
    1. 删模型插件（DB 记录 + agent 绑定 + 插件目录）
    2. 删模型资产目录（工作区 models/2D/<id>/）
    3. 若删的是当前激活模型：自动切到剩余第一个模型（联动插件互斥；会话不变）；
       无剩余模型 → ui.model 置空（壳 watch 变化，加载兜底）。
    非激活模型：config 不动（会话与模型解耦，属对话历史）。
    """
    target = next((m for m in list_models() if m["id"] == model_id), None)
    if target is None:
        raise KeyError(f"模型不存在: {model_id}")

    # 1. 级联删模型插件（source of truth = workspace plugins/<id>/）
    from app.domain.plugins.service import plugin_service

    plugin_service.delete(model_id)

    # 2. 删资产目录
    model_dir = MODEL_DIR / model_id
    if model_dir.is_dir():
        import shutil

        shutil.rmtree(model_dir, ignore_errors=True)

    # 3. config 联动
    cfg = _load_json(SHELL_CONFIG)
    ui = cfg.setdefault("ui", {})
    was_active = ui.get("model") == model_id
    if was_active:
        remaining = [m for m in list_models() if m["id"] != model_id]
        if remaining:
            nxt = sorted(remaining, key=lambda m: m["id"])[0]
            ui["model"] = nxt["id"]
            ui["model_path"] = nxt["path"]
            ui["model_type"] = "live2d"
            SHELL_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
            # 插件互斥：只启用新模型插件（删掉插件后 model_plugin_ids 已更新）
            for pid in plugin_service.model_plugin_ids():
                plugin_service.set_enabled(pid, pid == nxt["id"])
        else:
            ui.pop("model", None)
            ui.pop("model_path", None)
            ui.pop("model_type", None)
            SHELL_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": model_id, "was_active": was_active}


# ---------- 模型插件生成（插件名=模型名，工具名=动作/表情名） ----------

_MOTION_ZH: dict[str, str] = {
    "idle": "待机",
    "tap": "点击",
    "tap_body": "摸身体",
    "touch_body": "摸身体",
    "touch_head": "摸头",
    "touch_special": "特殊互动",
    "main_1": "主页动作一",
    "main_2": "主页动作二",
    "main_3": "主页动作三",
    "home": "回家动作",
    "login": "登录动作",
    "mail": "看邮件",
    "mission": "任务动作",
    "mission_complete": "任务完成",
    "complete": "完成动作",
    "wedding": "婚礼动作",
    "flick": "轻弹",
    "flickup": "向上轻弹",
    "flickdown": "向下轻弹",
    "idle1": "待机一",
    "idle2": "待机二",
    "tap_left": "摸左边",
    "tap_right": "摸右边",
}

_EXPRESSION_ZH: dict[str, str] = {
    "happy": "开心",
    "sad": "难过",
    "angry": "生气",
    "surprise": "惊讶",
    "shy": "害羞",
    "playful": "俏皮",
    "sleepy": "困倦",
    "normal": "平常",
}


def _zh_label(kind: str, name: str) -> str:
    # 动作/表情名规范化：驼峰转下划线小写（TapBody→tap_body），兼容两种命名
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    zh = (_MOTION_ZH if kind == "motion" else _EXPRESSION_ZH).get(snake, "")
    return f"{zh}（{name}）" if zh else name


def generate_model_plugin(model: dict) -> Path | None:
    """为单个模型生成插件（工作区 plugins/<model_id>/）。

    两种模式：
    1. 有 actions.json（语义清单）：工具名 = 语义名（wave/dance/nod...），
       工具一次返回 motion + expressions 组合，LLM 看到的是"挥手"不是 main_1。
    2. 无 manifest：fallback 到每个 motion group / expression 名一个工具（旧行为）。
    """
    model_id = model["id"]
    actions = model.get("actions") or {}
    motions = model.get("motions") or []
    expressions = model.get("expressions") or []
    if actions:
        return _generate_semantic_plugin(model_id, actions)
    if not motions and not expressions:
        return None

    plugin_dir = settings.workspace_path / "plugins" / model_id
    plugin_dir.mkdir(parents=True, exist_ok=True)

    yaml = (
        f"id: {model_id}\n"
        f"version: 1.0.0\n"
        f"name: 桌宠模型-{model_id}\n"
        f"kind: tool\n"
        f"description: 模型 {model_id} 的表情动作工具集：{len(motions)} 个动作"
        + (f"、{len(expressions)} 个表情" if expressions else "")
        + "\n"
        "entry: main.py\n"
    )
    (plugin_dir / "plugin.yaml").write_text(yaml, encoding="utf-8")

    lines = [
        '"""模型插件（自动生成）：工具名 = 模型真实动作/表情名，壳按返回字段播放。"""',
        "from __future__ import annotations",
        "",
        "import json",
        "",
        "",
    ]
    tool_regs: list[str] = []
    for name in motions:
        tool_regs.append(
            f"    ctx.tool(\n"
            f'        "{name}",\n'
            f'        _make_motion_player("{name}"),\n'
            f'        description="让桌宠执行动作「{_zh_label("motion", name)}」。调用后向用户确认已执行。",\n'
            f"    )"
        )
    for name in expressions:
        tool_regs.append(
            f"    ctx.tool(\n"
            f'        "{name}",\n'
            f'        _make_expression_player("{name}"),\n'
            f'        description="让桌宠做出表情「{_zh_label("expression", name)}」。调用后向用户确认已展示。",\n'
            f"    )"
        )
    lines += [
        "def _make_motion_player(name: str):",
        '    """闭包绑定动作名：无论 LLM 传什么参数，都播放工具名对应的真实动作。"""',
        "    def _play(*args, **kwargs) -> str:",
        '        return json.dumps({"motion": name}, ensure_ascii=False)',
        "    return _play",
        "",
        "",
        "def _make_expression_player(name: str):",
        '    """闭包绑定表情名：无论 LLM 传什么参数，都展示工具名对应的真实表情。"""',
        "    def _play(*args, **kwargs) -> str:",
        '        return json.dumps({"expression": name}, ensure_ascii=False)',
        "    return _play",
        "",
        "",
        "def setup(ctx) -> None:",
        '    """注册工具：模型每个动作/表情一个工具（octop 插件支持多工具）。"""',
        *tool_regs,
        "",
    ]
    (plugin_dir / "main.py").write_text("\n".join(lines), encoding="utf-8")
    return plugin_dir


def _generate_semantic_plugin(model_id: str, actions: dict) -> Path:
    """有 actions.json 时：按语义名生成工具，一次绑定 motion+expressions。"""
    plugin_dir = settings.workspace_path / "plugins" / model_id
    plugin_dir.mkdir(parents=True, exist_ok=True)

    yaml = (
        f"id: {model_id}\n"
        f"version: 1.0.0\n"
        f"name: 桌宠动作-{model_id}\n"
        f"kind: tool\n"
        f"description: 桌宠「{model_id}」的动作工具集。"
        f"根据对话情绪和场景选择合适的动作，让桌宠生动地回应。"
        f"共 {len(actions)} 个动作。\n"
        "entry: main.py\n"
    )
    (plugin_dir / "plugin.yaml").write_text(yaml, encoding="utf-8")

    # 生成 instructions.md：自动拼动作清单，注入到 system_prompt
    action_lines = []
    for name, spec in actions.items():
        label = spec.get("label_zh", name)
        action_lines.append(f"- {name}：{label}")
    instructions = (
        "你有一个 Live2D 形象身体，对话时要主动调用动作工具让自己动起来，"
        "不要只靠文字和 emoji。\n\n"
        "可用动作工具：\n"
        + "\n".join(action_lines)
        + "\n\n"
        "使用原则：\n"
        "- 用户让你打招呼、做动作、表达情绪时，调用对应动作工具让身体做出来，不要用 emoji 代替\n"
        "- 动作要自然：打招呼用 wave，思考用 think，完成任务用 celebrate，同意用 nod\n"
        "- 调用动作后简短回应即可，不要长篇大论\n"
    )
    (plugin_dir / "instructions.md").write_text(instructions, encoding="utf-8")

    tool_regs: list[str] = []
    for semantic_name, spec in actions.items():
        motion = spec.get("motion", "")
        exprs = spec.get("expressions", []) or []
        label = spec.get("label_zh", semantic_name)
        expr_desc = f"，同时呈现表情：{ '、'.join(exprs) }" if exprs else ""
        tool_regs.append(
            f"    ctx.tool(\n"
            f'        "{semantic_name}",\n'
            f'        _make_action_player({json.dumps(motion)}, {json.dumps(exprs)}, {json.dumps(label, ensure_ascii=False)}),\n'
            f'        description="让桌宠做出「{label}」动作{expr_desc}。",\n'
            f"    )"
        )

    lines = [
        '"""模型插件（自动生成）：工具名 = 语义动作名，一次绑定 motion+expressions。"""',
        "from __future__ import annotations",
        "",
        "import json",
        "",
        "",
        "def _make_action_player(motion: str, expressions: list, label: str):",
        '    """闭包绑定：LLM 调用语义工具时，返回 motion+expressions 组合 payload。"""',
        "    def _play(*args, **kwargs) -> str:",
        '        return json.dumps({"motion": motion, "expressions": expressions, "label": label}, ensure_ascii=False)',
        "    return _play",
        "",
        "",
        "def setup(ctx) -> None:",
        '    """注册工具：每个语义动作一个工具。"""',
        *tool_regs,
        "",
    ]
    (plugin_dir / "main.py").write_text("\n".join(lines), encoding="utf-8")
    return plugin_dir


def generate_all_model_plugins() -> list[dict]:
    """为所有有动作/表情的模型生成插件，返回生成结果。"""
    results: list[dict] = []
    for model in list_models():
        plugin_dir = generate_model_plugin(model)
        results.append(
            {
                "model": model["id"],
                "generated": plugin_dir is not None,
                "path": str(plugin_dir) if plugin_dir else None,
            }
        )
    return results


def load_pet_instructions() -> str:
    """读当前激活模型插件的 instructions.md（身体使用说明）。

    拼到 system_prompt 后面，让 LLM 知道"你有身体要主动做动作"。
    插件未启用 / 无 instructions.md 时返回空字符串。
    """
    active = get_active_model()
    if not active:
        return ""
    # 检查插件是否启用
    from app.storage import db

    with db.connect() as conn:
        row = conn.execute(
            "SELECT enabled FROM plugins WHERE plugin_id=?", (active,)
        ).fetchone()
    if not row or not row["enabled"]:
        return ""
    instructions_path = settings.workspace_path / "plugins" / active / "instructions.md"
    if not instructions_path.is_file():
        return ""
    try:
        return instructions_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ---------- AI 自动分析模型 → 生成 actions.json + instructions.md ----------

def _summarize_expression_file(path: Path) -> dict:
    """读单个 .exp3.json，提取非零参数变化（AI 据此判断情绪）。"""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        p["Id"]: p["Value"]
        for p in d.get("Parameters", [])
        if abs(p.get("Value", 0)) > 0.1
    }


def _summarize_motion_file(path: Path) -> dict:
    """读单个 .motion3.json，提取关键曲线摘要（哪些参数变化大）。"""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    meta = d.get("Meta", {})
    notable = []
    for c in d.get("Curves", []):
        pid = c.get("Id", "")
        segs = c.get("Segments", [])
        if len(segs) < 2:
            continue
        try:
            vals = [
                segs[i]
                for i in range(1, len(segs), 2)
                if isinstance(segs[i], (int, float))
            ]
            if vals:
                rng = max(vals) - min(vals)
                if rng > 1.0:
                    notable.append(f"{pid}(range={rng:.1f})")
        except (IndexError, TypeError):
            pass
    return {
        "duration_s": round(meta.get("Duration", 0), 1),
        "loop": meta.get("Loop", False),
        "active_params": notable[:8],
    }


def enrich_model(model_id: str) -> dict:
    """分析模型，生成 actions.json + instructions.md + 插件。

    Live2D：AI 分析 motions/expressions 目录生成语义动作映射。
    VRM：直接生成通用动作工具集（表情 + 预设骨骼动作），不需要 AI。
    """
    # --- VRM 3D 模型：直接生成通用动作工具 ---
    model_path = None
    for vrm_file in sorted(MODEL_DIR_3D.glob("*.vrm")):
        if vrm_file.stem == model_id:
            model_path = vrm_file
            break
    if model_path:
        return _enrich_vrm(model_id, model_path)

    model_dir = MODEL_DIR / model_id
    model_files = sorted(model_dir.glob("*.model3.json"))
    if not model_files:
        return {"ok": False, "error": "model3.json not found"}
    meta = _load_json(model_files[0])
    fr = meta.get("FileReferences") or {}

    motions = fr.get("Motions") or {}
    expressions_list = fr.get("Expressions") or []
    if not motions and not expressions_list:
        logger.info("enrich_model %s skipped: no motions/expressions", model_id)
        return {"ok": True, "skipped": "no motions/expressions"}

    # 1. 表情摘要
    expressions: dict[str, dict] = {}
    for e in expressions_list:
        if not isinstance(e, dict):
            continue
        name = e.get("Name") or Path(e.get("File", "")).stem
        exp_path = model_dir / e.get("File", "")
        if exp_path.is_file():
            expressions[name] = _summarize_expression_file(exp_path)

    # 2. motion 摘要
    motion_groups: dict[str, list[str]] = {}
    motion_details: dict[str, dict] = {}
    for group, files in (fr.get("Motions") or {}).items():
        motion_groups[group] = []
        for f in files:
            fname = f.get("File", "") if isinstance(f, dict) else ""
            if not fname:
                continue
            motion_groups[group].append(Path(fname).stem)
            mpath = model_dir / fname
            if mpath.is_file():
                motion_details[Path(fname).stem] = _summarize_motion_file(mpath)

    # 3. 调 LLM
    from openai import OpenAI

    providers_data = json.loads(
        (settings.workspace_path / "providers.json").read_text(encoding="utf-8")
    )
    providers = providers_data.get("providers") or []
    if not providers:
        return {"ok": False, "error": "no LLM provider configured"}
    p = providers[0]
    client = OpenAI(api_key=p["api_key"], base_url=p["base_url"])
    model_name = p["models"][0]["id"] if p.get("models") else p.get("model", "deepseek-chat")

    prompt = f"""你是 Live2D 模型动作分析专家。根据以下表情参数和动作曲线摘要，生成语义动作映射。

模型：{model_id}

表情列表（参数变化大的才列出）：
{json.dumps(expressions, ensure_ascii=False, indent=2)}

动作分组：
{json.dumps(motion_groups, ensure_ascii=False, indent=2)}

动作曲线摘要：
{json.dumps(motion_details, ensure_ascii=False, indent=2)}

请输出严格 JSON：
{{
  "actions": {{
    "snake_case动作名": {{
      "motion": "motion组名",
      "expressions": ["表情名"],
      "label_zh": "中文标签"
    }}
  }},
  "instructions": "一段给 AI 角色的身体使用说明（100字内），列出可用动作，告诉它什么时候用，不要用 emoji 代替动作"
}}

要求：
- motion 必须是上面分组里的 group 名
- expressions 必须从上面表情列表选
- 覆盖日常对话：打招呼/思考/惊讶/开心/生气/害羞/放松/被摸
- instructions 要自然，不要八股"""

    try:
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        raw = (resp.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)
    except Exception as e:
        logger.warning("enrich_model %s failed: %s", model_id, e)
        return {"ok": False, "error": str(e)}

    # 4. 写 actions.json
    actions_path = model_dir / "actions.json"
    actions_path.write_text(
        json.dumps({"actions": result["actions"]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 5. 写 instructions.md（AI 生成，覆盖模板）
    plugin_dir = settings.workspace_path / "plugins" / model_id
    instructions_path = plugin_dir / "instructions.md"
    if instructions_path.parent.is_dir():
        instructions_path.write_text(
            result.get("instructions", "").strip(), encoding="utf-8"
        )

    # 6. 重新生成插件
    model_info = next((m for m in list_models() if m["id"] == model_id), None)
    if model_info:
        generate_model_plugin(model_info)

    logger.info("enrich_model %s done: %d actions", model_id, len(result["actions"]))
    return {"ok": True, "actions": len(result["actions"])}


def _enrich_vrm(model_id: str, vrm_path: Path) -> dict:
    """VRM 模型：直接生成通用动作工具集（表情 + 预设骨骼动作），不需要 AI。

    VRM 没有 motions/expressions 目录——表情是 blend shape 权重，动作是运行时骨骼旋转。
    这里生成一套通用工具，壳里 VRM 模式下映射到 expressionManager + humanoid bone。
    """
    # 通用表情（blend shape，所有 VRM 模型基本都有）
    expressions = {
        "happy":    {"label_zh": "开心微笑", "emotions": ["happy", "greeting", "praise"]},
        "angry":    {"label_zh": "生气", "emotions": ["angry", "displeased"]},
        "sad":      {"label_zh": "难过", "emotions": ["sad", "disappointed"]},
        "relaxed":  {"label_zh": "放松", "emotions": ["calm", "thinking", "listening"]},
        "surprised":{"label_zh": "惊讶张嘴", "emotions": ["surprised", "thinking", "question"]},
        "blink":    {"label_zh": "眨眼", "emotions": ["neutral"]},
        "neutral":  {"label_zh": "中性表情", "emotions": ["idle", "neutral"]},
    }
    # 预设动作（壳里用骨骼旋转实现）
    actions = {
        "wave_hand":       {"label_zh": "挥手打招呼", "motion": "wave_hand", "emotions": ["greeting", "happy", "bye"]},
        "nod":             {"label_zh": "点头同意", "motion": "nod", "emotions": ["agree", "yes", "understanding"]},
        "shake_head":      {"label_zh": "摇头拒绝", "motion": "shake_head", "emotions": ["deny", "no", "disagree"]},
        "tilt_head":       {"label_zh": "歪头好奇", "motion": "tilt_head", "emotions": ["curious", "thinking", "question"]},
        "raise_right_hand":{"label_zh": "举起右手指向", "motion": "raise_right_hand", "emotions": ["point", "show", "explain"]},
        "raise_left_hand": {"label_zh": "举起左手指向", "motion": "raise_left_hand", "emotions": ["point", "show", "explain"]},
        "look_left":       {"label_zh": "看向左边", "motion": "look_left", "emotions": ["thinking", "shy"]},
        "look_right":      {"label_zh": "看向右边", "motion": "look_right", "emotions": ["thinking", "shy"]},
        "look_up":         {"label_zh": "抬头看", "motion": "look_up", "emotions": ["thinking", "surprised"]},
        "look_down":       {"label_zh": "低头思考", "motion": "look_down", "emotions": ["shy", "sad", "thoughtful"]},
        "hands_on_hips":   {"label_zh": "叉腰", "motion": "hands_on_hips", "emotions": ["confident", "angry", "explain"]},
        "shrug":           {"label_zh": "耸肩无奈", "motion": "shrug", "emotions": ["helpless", "don't_know", "casual"]},
        "dance":           {"label_zh": "跳舞", "motion": "dance", "emotions": ["happy", "celebrate", "energetic"]},
        "jump":            {"label_zh": "跳一下", "motion": "jump", "emotions": ["happy", "excited", "celebrate"]},
        "spin":            {"label_zh": "转一圈", "motion": "spin", "emotions": ["happy", "excited", "dizzy"]},
        "stretch":         {"label_zh": "伸懒腰", "motion": "stretch", "emotions": ["tired", "relaxed", "casual"]},
        "elbow_punch":     {"label_zh": "肘击攻击", "motion": "elbow_punch", "emotions": ["fight", "excited", "playful", "action"]},
        "sitting_laughing":{"label_zh": "坐着大笑", "motion": "sitting_laughing", "emotions": ["laugh", "happy", "amused", "joy"]},
    }

    actions_json: dict = {
        "model_type": "vrm",
        "expressions": expressions,
        "actions": actions,
    }

    # 写 actions.json 到 VRM 旁边的目录
    plugin_dir = settings.workspace_path / "plugins" / model_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "actions.json").write_text(
        json.dumps(actions_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # instructions.md：告诉 LLM 这是 3D 模型，可以直接控制表情和身体
    instructions = f"""# {model_id}（VRM 3D 桌宠）

这是一个 3D VRM 模型。你可以通过工具直接控制 ta 的表情和身体动作。

## 可用表情（调 set_expression 工具，weight 0~1）
{chr(10).join(f'- **{k}**：{v["label_zh"]}' for k, v in expressions.items())}

## 可用动作（调 do_action 工具）
{chr(10).join(f'- **{k}**：{v["label_zh"]}' for k, v in actions.items())}

## 使用建议
- 对话时根据情绪自动切换表情（开心→happy，思考→relaxed，惊讶→surprised）
- 打招呼时 wave_hand，同意时 nod，不同意时 shake_head
- 表情和动作可以组合（笑 + 挥手）
- 不要同时用矛盾的表情（happy 和 angry）
"""
    (plugin_dir / "instructions.md").write_text(instructions, encoding="utf-8")

    # 生成插件（直接传 actions，不走 list_models）
    _generate_semantic_plugin(model_id, actions_json["actions"])

    # _generate_semantic_plugin 会覆盖 instructions.md，这里重写成 VRM 专用
    instructions = f"""# {model_id}（VRM 3D 桌宠）

这是一个 3D VRM 模型。你可以通过工具直接控制 ta 的表情和身体动作。

## 可用动作工具
{chr(10).join(f'- **{k}**：{v["label_zh"]}' for k, v in actions.items())}

## 使用建议
- 对话时根据情绪主动调用动作工具让身体动起来，不要只靠文字和 emoji
- 打招呼用 wave_hand，同意用 nod，不同意用 shake_head，好奇时 tilt_head
- 思考时 look_left/look_right，开心时配合 wave_hand
- 调用动作后简短回应即可，不要长篇大论
"""
    (plugin_dir / "instructions.md").write_text(instructions, encoding="utf-8")

    logger.info("enrich_vrm %s done: %d expressions, %d actions",
                model_id, len(expressions), len(actions))
    return {"ok": True, "actions": len(actions)}
