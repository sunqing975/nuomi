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
    return any((model_dir / str(it.get("File", ""))).is_file() for it in items if isinstance(it, dict))


def _expression_has_file(model_dir: Path, expr: dict) -> bool:
    """表情引用文件真实存在于磁盘。"""
    file = str(expr.get("File", ""))
    return bool(file) and (model_dir / file).is_file()


def list_models() -> list[dict]:
    """扫描模型目录，返回 [{id, path, motions, expressions}]。

    motions/expressions 只列文件真实存在的（资产不完整的模型如实显示为空）。
    """
    _seed_builtin_models()
    models: list[dict] = []
    if not MODEL_DIR.is_dir():
        return models
    for char_dir in sorted(MODEL_DIR.iterdir()):
        if not char_dir.is_dir():
            continue
        model_files = sorted(char_dir.glob("*.model3.json"))
        if not model_files:
            continue
        meta = _load_json(model_files[0])
        fr = meta.get("FileReferences") or {}
        motions = sorted(
            g for g in (fr.get("Motions") or {})
            if _group_has_files(char_dir, meta, g)
        )
        expressions = [
            (e.get("Name") if isinstance(e, dict) and e.get("Name") else Path(e.get("File", "")).stem)
            for e in (fr.get("Expressions") or [])
            if isinstance(e, dict) and _expression_has_file(char_dir, e)
        ]
        models.append(
            {
                "id": char_dir.name,
                # 绝对路径（资产在工作区）；壳侧转 file:// URL 加载
                "path": str(char_dir / model_files[0].name),
                "motions": motions,
                "expressions": expressions,
                # 种子机制分发的内置模型（仓库 assets/models/2D/<id>），
                # 删除后启动播种会复原，故页面上不可删除
                "builtin": (SEED_MODEL_DIR / char_dir.name).is_dir(),
            }
        )
    return models


def get_active_model() -> str | None:
    cfg = _load_json(SHELL_CONFIG)
    return (cfg.get("ui") or {}).get("model")


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
    ui["model_type"] = "live2d"
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
    "idle": "待机", "tap": "点击", "tap_body": "摸身体", "touch_body": "摸身体",
    "touch_head": "摸头", "touch_special": "特殊互动", "main_1": "主页动作一",
    "main_2": "主页动作二", "main_3": "主页动作三", "home": "回家动作",
    "login": "登录动作", "mail": "看邮件", "mission": "任务动作",
    "mission_complete": "任务完成", "complete": "完成动作", "wedding": "婚礼动作",
    "flick": "轻弹", "flickup": "向上轻弹", "flickdown": "向下轻弹",
    "idle1": "待机一", "idle2": "待机二",
    "tap_left": "摸左边", "tap_right": "摸右边",
}

_EXPRESSION_ZH: dict[str, str] = {
    "happy": "开心", "sad": "难过", "angry": "生气", "surprise": "惊讶",
    "shy": "害羞", "playful": "俏皮", "sleepy": "困倦", "normal": "平常",
}


def _zh_label(kind: str, name: str) -> str:
    # 动作/表情名规范化：驼峰转下划线小写（TapBody→tap_body），兼容两种命名
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    zh = (_MOTION_ZH if kind == "motion" else _EXPRESSION_ZH).get(snake, "")
    return f"{zh}（{name}）" if zh else name


def generate_model_plugin(model: dict) -> Path | None:
    """为单个模型生成插件（工作区 plugins/<model_id>/）。

    工具名 = 动作/表情名（模型真实能力），一次可注册多个工具（octop 支持）。
    工具返回 {"motion"/"expression": 名称, "display": 中文语义}，壳播放器按字段直接播放。
    """
    model_id = model["id"]
    motions = model.get("motions") or []
    expressions = model.get("expressions") or []
    if not motions and not expressions:
        return None  # 无动作无表情的模型不生成插件

    plugin_dir = settings.workspace_path / "plugins" / model_id
    plugin_dir.mkdir(parents=True, exist_ok=True)

    # plugin.yaml
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

    # main.py：每个动作/表情注册一个 ctx.tool
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
            f'    ctx.tool(\n'
            f'        "{name}",\n'
            f'        _make_motion_player("{name}"),\n'
            f'        description="让桌宠执行动作「{_zh_label("motion", name)}」。调用后向用户确认已执行。",\n'
            f'    )'
        )
    for name in expressions:
        tool_regs.append(
            f'    ctx.tool(\n'
            f'        "{name}",\n'
            f'        _make_expression_player("{name}"),\n'
            f'        description="让桌宠做出表情「{_zh_label("expression", name)}」。调用后向用户确认已展示。",\n'
            f'    )'
        )
    lines += [
        'def _make_motion_player(name: str):',
        '    """闭包绑定动作名：无论 LLM 传什么参数，都播放工具名对应的真实动作。"""',
        '    def _play(*args, **kwargs) -> str:',
        '        return json.dumps({"motion": name}, ensure_ascii=False)',
        '    return _play',
        "",
        "",
        'def _make_expression_player(name: str):',
        '    """闭包绑定表情名：无论 LLM 传什么参数，都展示工具名对应的真实表情。"""',
        '    def _play(*args, **kwargs) -> str:',
        '        return json.dumps({"expression": name}, ensure_ascii=False)',
        '    return _play',
        "",
        "",
        "def setup(ctx) -> None:",
        "    \"\"\"注册工具：模型每个动作/表情一个工具（octop 插件支持多工具）。\"\"\"",
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
            {"model": model["id"], "generated": plugin_dir is not None,
             "path": str(plugin_dir) if plugin_dir else None}
        )
    return results
