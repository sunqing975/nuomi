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
import shutil
from pathlib import Path

from app.config import REPO_ROOT, settings

logger = logging.getLogger(__name__)

MODEL_DIR_3D = settings.workspace_path / "models" / "3D"
SHELL_CONFIG = REPO_ROOT / "shells" / "myspy" / "config.json"
STATE_FILE = settings.workspace_path / "nuomi-state.json"


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def list_models() -> list[dict]:
    """扫描模型目录，返回 [{id, path, type, motions, expressions, actions}]。

    3D: models/3D/<xxx>.vrm（单个文件）；2D Live2D 已下线（2026-10-04）。
    """
    models: list[dict] = []
    if MODEL_DIR_3D.is_dir():
        for vrm_file in sorted(MODEL_DIR_3D.glob("*.vrm")):
            models.append(
                {
                    "id": vrm_file.stem,
                    "path": str(vrm_file),
                    "type": "vrm",
                    "motions": [],
                    "expressions": list_vrm_expressions(vrm_file),
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
    ui["model_type"] = target.get("type", "vrm")
    SHELL_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


# ==================== 方案B：共享 VRM 动态工具元数据 ====================

VRM_PET_PLUGIN_ID = "vrm-pet"
SHELL_ANIM_DIR = REPO_ROOT / "shells" / "myspy" / "assets" / "animations"

# VRM 标准表情 preset 中文标签（动态 enum 的 label 来源；模型实际拥有的由 GLB 枚举）
EXPRESSION_LABELS: dict[str, str] = {
    "neutral": "中性表情",
    "happy": "开心微笑",
    "angry": "生气",
    "sad": "难过",
    "relaxed": "放松",
    "surprised": "惊讶张嘴",
    "aa": "张嘴",
    "ih": "微笑",
    "ou": "嘟嘴",
    "ee": "眯眼",
    "oh": "哦",
    "blink": "眨眼",
    "blinkLeft": "左眼眨",
    "blinkRight": "右眼眨",
    "lookUp": "向上看",
    "lookDown": "向下看",
    "lookLeft": "向左看",
    "lookRight": "向右看",
}

# 模型真实 blend shape 名变体 → VRM 标准小写名（不同建模软件命名差异归一，用于中文 label）
# 例：当前模型真实名 Joy/Angry/Sorrow/Fun/Blink_L（首字母大写语义名），映射回标准名
_EXPRESSION_ALIASES: dict[str, str] = {
    "Neutral": "neutral",
    "A": "aa",
    "I": "ih",
    "U": "ou",
    "E": "ee",
    "O": "oh",
    "Blink": "blink",
    "Blink_L": "blinkLeft",
    "Blink_R": "blinkRight",
    "Joy": "happy",
    "Angry": "angry",
    "Sorrow": "sad",
    "Fun": "relaxed",
    "LookUp": "lookUp",
    "LookDown": "lookDown",
    "LookLeft": "lookLeft",
    "LookRight": "lookRight",
}

# three-vrm v0v1PresetNameMap 同步：VRM 0.x preset 变体 → VRM 1.0 标准名。
# 壳端 expressionManager 键是标准名（a→aa、joy→happy、lookup→lookUp、blink_l→blinkLeft…），
# 后端解析 GLB 的 presetName 必须做同一映射，前后端/壳播放才一致。
_V0_TO_V1: dict[str, str] = {
    "a": "aa",
    "e": "ee",
    "i": "ih",
    "o": "oh",
    "u": "ou",
    "blink": "blink",
    "joy": "happy",
    "angry": "angry",
    "sorrow": "sad",
    "fun": "relaxed",
    "lookup": "lookUp",
    "lookdown": "lookDown",
    "lookleft": "lookLeft",
    "lookright": "lookRight",
    "blink_l": "blinkLeft",
    "blink_r": "blinkRight",
    "neutral": "neutral",
}


def _expression_zh(name: str) -> str:
    """blend shape 真实名 → 中文标签（先原名、再别名变体、再小写兜底）。"""
    if name in EXPRESSION_LABELS:
        return EXPRESSION_LABELS[name]
    std = _EXPRESSION_ALIASES.get(name, name.lower())
    return EXPRESSION_LABELS.get(std, name)

# 预设动作中文标签（手写骨骼动画兜底；有同名 .vrma 时由 VRMA 覆盖播放）
ACTION_LABELS: dict[str, str] = {
    "wave_hand": "挥手打招呼",
    "nod": "点头同意",
    "shake_head": "摇头拒绝",
    "tilt_head": "歪头好奇",
    "raise_right_hand": "举起右手指向",
    "raise_left_hand": "举起左手指向",
    "look_left": "看向左边",
    "look_right": "看向右边",
    "look_up": "抬头看",
    "look_down": "低头思考",
    "hands_on_hips": "叉腰",
    "shrug": "耸肩无奈",
    "dance": "跳舞",
    "jump": "跳一下",
    "spin": "转一圈",
    "stretch": "伸懒腰",
    "elbow_punch": "肘击攻击",
    "sitting_laughing": "坐着大笑",
}


def list_vrm_expressions(model_path: Path) -> list[str]:
    """解析 VRM GLB 的 blend shape 名（无 three 依赖）。

    GLB = 12 字节头 + JSON chunk（0x4E4F534A）+ BIN chunk。
    VRM 0.x: extensions.VRM.blendShapeMaster.blendShapeGroups[].name
    VRM 1.0: extensions.VRMC_vrm.expressions[].name
    """
    try:
        with open(model_path, "rb") as f:
            head = f.read(12)
            if head[:4] != b"glTF":
                return []
            chunk_len = int.from_bytes(f.read(4), "little")
            chunk_type = f.read(4)
            if chunk_type != b"JSON":
                return []
            data = f.read(chunk_len)
        gltf = json.loads(data.decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    ext = gltf.get("extensions") or {}
    groups = ((ext.get("VRM") or {}).get("blendShapeMaster") or {}).get("blendShapeGroups") or []
    if groups:
        return [_vrm_expr_name(g) for g in groups if g.get("name")]
    exprs = ((ext.get("VRMC_vrm") or {}).get("expressions") or {}).get("expressions") or {}
    if isinstance(exprs, dict):
        return list(exprs)
    return []


def _vrm_expr_name(g: dict) -> str:
    """blend shape group → 播放用表情名（与壳端 three-vrm 键一致）。

    优先 VRM 0.x presetName（经 _V0_TO_V1 映射到标准名，如 a→aa、joy→happy、
    lookup→lookUp、blink_l→blinkLeft）；无 preset（自定义名，如 Joy/Angry）
    时经 _EXPRESSION_ALIASES 归一到标准名。
    """
    preset = (g.get("presetName") or "").strip().lower()
    if preset and preset not in ("custom", "unknown"):
        return _V0_TO_V1.get(preset, preset)
    name = g.get("name") or ""
    return _EXPRESSION_ALIASES.get(name, name)


def list_pet_actions() -> list[dict]:
    """动作清单：内置预设（手写兜底）+ assets/animations/*.vrma（VRMA 覆盖）。

    返回 [{"name", "label_zh", "has_vrma"}]，按 name 排序。
    """
    out: dict[str, dict] = {}
    for name, label in ACTION_LABELS.items():
        out[name] = {"name": name, "label_zh": label, "has_vrma": False}
    if SHELL_ANIM_DIR.is_dir():
        for f in sorted(SHELL_ANIM_DIR.glob("*.vrma")):
            name = f.stem
            entry = out.setdefault(name, {"name": name, "label_zh": name, "has_vrma": True})
            entry["has_vrma"] = True
    return list(out.values())


def list_pet_expressions() -> list[dict]:
    """当前激活 VRM 模型的 blend shape 清单 + 中文标签。"""
    active = get_active_model()
    if not active:
        return []
    model_path = MODEL_DIR_3D / f"{active}.vrm"
    if not model_path.is_file():
        return []
    names = list_vrm_expressions(model_path)
    return [{"name": n, "label_zh": _expression_zh(n)} for n in names]


def ensure_vrm_pet_plugin() -> None:
    """确保共享 VRM 插件目录存在（plugin.yaml + 空 main.py + instructions.md）。

    工具不在插件静态注册——由 PluginService.tools() 装配时按当前模型/动画动态构造。
    """
    plugin_dir = settings.workspace_path / "plugins" / VRM_PET_PLUGIN_ID
    plugin_dir.mkdir(parents=True, exist_ok=True)
    yaml = (
        f"id: {VRM_PET_PLUGIN_ID}\n"
        "version: 1.0.0\n"
        "name: 桌宠动作\n"
        "kind: tool\n"
        "description: 所有 VRM 桌宠共用的动作与表情工具（装配时按当前模型动态生成工具清单）。"
        "启用/停用跟随桌宠开关。\n"
        "entry: main.py\n"
    )
    (plugin_dir / "plugin.yaml").write_text(yaml, encoding="utf-8")
    main_py = (
        '"""共享 VRM 桌宠插件（自动生成）：工具由 PluginService.tools() 装配时动态构造。"""\n'
        "from __future__ import annotations\n\n"
        "def setup(ctx) -> None:\n"
        '    """动态工具不走插件静态注册；保留空入口以便 PluginRegistry 加载。"""\n'
        "    pass\n"
    )
    (plugin_dir / "main.py").write_text(main_py, encoding="utf-8")
    instructions = (
        "你有一个桌宠身体（VRM 3D 形象），对话时要主动调用工具让自己动起来，不要只靠文字和 emoji。\n\n"
        "可用工具：\n"
        "- do_action：让身体做出一个动作（挥手/点头/跳舞等，参数 action 从可用列表选）\n"
        "- set_expression：切换面部表情（开心/生气/难过等，参数 expression 从可用列表选）\n\n"
        "使用原则：\n"
        "- 用户让你打招呼、做动作、表达情绪时，调用对应工具让身体做出来，不要用 emoji 代替\n"
        "- 用户明确要求表情（如「笑一个/生气/难过」）时，调用 set_expression\n"
        "- 动作和表情可以组合（开心地挥手 = set_expression happy + do_action wave_hand）\n"
        "- 调用工具后简短回应即可，不要长篇大论\n"
    )
    (plugin_dir / "instructions.md").write_text(instructions, encoding="utf-8")


def _action_label(name: str) -> str:
    for a in list_pet_actions():
        if a["name"] == name:
            return a["label_zh"]
    return name


def _expression_label(name: str) -> str:
    for e in list_pet_expressions():
        if e["name"] == name:
            return e["label_zh"]
    return name


def delete_model(model_id: str) -> dict:
    """删除桌宠模型：资产目录 → config 联动（方案B：无每模型插件可级联）。

    级联顺序：
    1. 删模型资产目录（工作区 models/3D/<id>.vrm 或 models/2D/<id>/，2D 已下线）
    2. 若删的是当前激活模型：自动切到剩余第一个模型（会话不变）；
       无剩余模型 → ui.model 置空（壳 watch 变化，加载兜底）。
    非激活模型：config 不动（会话与模型解耦，属对话历史）。
    """
    target = next((m for m in list_models() if m["id"] == model_id), None)
    if target is None:
        raise KeyError(f"模型不存在: {model_id}")

    # 1. 删资产目录

    vrm_file = MODEL_DIR_3D / f"{model_id}.vrm"
    if vrm_file.is_file():
        vrm_file.unlink()
    legacy_2d_dir = settings.workspace_path / "models" / "2D" / model_id
    if legacy_2d_dir.is_dir():
        shutil.rmtree(legacy_2d_dir, ignore_errors=True)

    # 2. config 联动
    cfg = _load_json(SHELL_CONFIG)
    ui = cfg.setdefault("ui", {})
    was_active = ui.get("model") == model_id
    if was_active:
        remaining = [m for m in list_models() if m["id"] != model_id]
        if remaining:
            nxt = sorted(remaining, key=lambda m: m["id"])[0]
            ui["model"] = nxt["id"]
            ui["model_path"] = nxt["path"]
            ui["model_type"] = nxt.get("type", "vrm")
            SHELL_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            ui.pop("model", None)
            ui.pop("model_path", None)
            ui.pop("model_type", None)
            SHELL_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": model_id, "was_active": was_active}


def ensure_pet_plugins() -> dict:
    """方案B：桌宠只有一个共享 VRM 插件（vrm-pet），工具装配时动态构造。

    不再按模型生成插件（旧 generate_model_plugin/_generate_semantic_plugin 已删）。
    """
    ensure_vrm_pet_plugin()
    return {"ok": True, "plugin": VRM_PET_PLUGIN_ID}


def load_pet_instructions() -> str:
    """读共享 VRM 插件（vrm-pet）的 instructions.md（身体使用说明）。

    拼到 system_prompt 后面，让 LLM 知道"你有身体要主动做动作"。
    插件未启用 / 无 instructions.md 时返回空字符串。
    """
    ensure_vrm_pet_plugin()
    # 检查插件是否启用
    from app.storage import db

    with db.connect() as conn:
        row = conn.execute(
            "SELECT enabled FROM plugins WHERE plugin_id=?", (VRM_PET_PLUGIN_ID,)
        ).fetchone()
    if not row or not row["enabled"]:
        return ""
    instructions_path = settings.workspace_path / "plugins" / VRM_PET_PLUGIN_ID / "instructions.md"
    if not instructions_path.is_file():
        return ""
    try:
        return instructions_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ---------- AI 自动分析模型 → 生成 actions.json + instructions.md ----------

def enrich_model(model_id: str) -> dict:
    """分析模型，返回清单（方案B：不再按模型生成插件）。

    VRM：解析模型 blend shape + 动作清单（供动态工具装配与前端展示），不需要 AI。
    2D Live2D 已下线（2026-10-04）。
    """
    model_path = None
    for vrm_file in sorted(MODEL_DIR_3D.glob("*.vrm")):
        if vrm_file.stem == model_id:
            model_path = vrm_file
            break
    if model_path:
        return _enrich_vrm(model_id, model_path)
    return {"ok": False, "error": f"模型不存在或不是 VRM 3D 模型: {model_id}"}
def _enrich_vrm(model_id: str, vrm_path: Path) -> dict:
    """VRM 模型：确保共享桌宠插件就绪，返回模型实际可用清单。

    方案B：动作/表情工具由 PluginService.tools() 装配时按当前模型动态构造，
    这里只保证共享插件存在并返回清单（供接口/前端展示）。
    """
    ensure_vrm_pet_plugin()
    expressions = list_vrm_expressions(vrm_path)
    actions = [a["name"] for a in list_pet_actions()]
    logger.info(
        "enrich_vrm %s done: %d expressions, %d actions",
        model_id, len(expressions), len(actions),
    )
    return {
        "ok": True,
        "model_id": model_id,
        "expressions": len(expressions),
        "actions": len(actions),
        "expressions_list": expressions,
        "actions_list": actions,
    }
