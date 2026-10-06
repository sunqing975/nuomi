"""插件市场：内置 registry（backend/assets/market/）+ 安装 + 插件配置读写。

- 市场清单：``{repo}/backend/assets/market/registry.json``（后续可扩展远程 URL 源）；
- 安装：下载对应 ``<id>.zip`` → 复用 infra/importers.import_plugin_zip（工作区 plugins/<id>/ + DB 注册）；
- 配置：插件 ``plugin.yaml`` 声明 ``settings`` 段，控制台动态渲染表单，值存 ``plugins/<id>/config.json``；
- 服务型插件（kind=service）：后端经 ``synthesize()`` 调用其能力（如 TTS 播报）。

分层（2026-10-06）：本模块是 infra 层，不反向依赖 domain ——
``list_market`` 的"已安装列表"由 transport 组装传入（installed 参数），
导入落盘走 ``app.infra.importers``。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

from app.config import settings

MARKET_DIR = Path(__file__).resolve().parents[3] / "assets" / "market"
REGISTRY_FILE = MARKET_DIR / "registry.json"

# settings 段支持的类型（含 secret 脱敏语义）
_SETTING_TYPES = {"boolean", "text", "secret", "select"}
_BOOL = ("true", "false", "1", "0")


def _registry() -> dict:
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"plugins": []}
    except (OSError, ValueError):
        return {"plugins": []}


def list_market(installed: list | None = None) -> dict:
    """市场清单 + 已安装状态（installed/enabled/installed_version）。

    ``installed`` 为已安装插件行（``plugin_id`` → row），由 transport 传入
    （infra 不反向依赖 domain.plugins.plugin_service）。
    """
    installed_map = {p["plugin_id"]: p for p in (installed or [])}
    out = []
    for p in _registry().get("plugins", []):
        item = dict(p)
        row = installed_map.get(p["id"])
        item["installed"] = row is not None
        item["enabled"] = bool(row["enabled"]) if row else False
        item["installed_version"] = row["version"] if row else None
        out.append(item)
    return {"name": _registry().get("name", ""), "plugins": out}


def install(plugin_id: str) -> str:
    """从内置市场把插件 zip **落盘**到工作区 plugins/，返回 plugin_id。

    不做注册：``PluginRegistry`` 是进程级单例，注册必须回到事件循环做
    （见 ``infra/importers._import_plugin_from_root`` 的说明）。
    """
    from app.infra.importers import import_plugin_zip

    pkg = MARKET_DIR / f"{plugin_id}.zip"
    if not pkg.is_file():
        raise ValueError(f"市场没有该插件包：{plugin_id}")
    return import_plugin_zip(pkg.read_bytes())


def plugin_dir(plugin_id: str) -> Path:
    d = settings.workspace_path / "plugins" / plugin_id
    if not (d / "plugin.yaml").is_file():
        raise FileNotFoundError(f"插件未安装：{plugin_id}")
    return d


def settings_schema(plugin_id: str) -> list[dict]:
    """读 plugin.yaml 的 settings 段（未声明返回 []）。"""
    d = plugin_dir(plugin_id)
    manifest = yaml.safe_load((d / "plugin.yaml").read_text(encoding="utf-8")) or {}
    fields = manifest.get("settings") or []
    if not isinstance(fields, list):
        return []
    return [
        f
        for f in fields
        if isinstance(f, dict) and f.get("key") and f.get("type") in _SETTING_TYPES
    ]


def _mask(value: str) -> str:
    if not value:
        return ""
    return f"{value[:4]}***{value[-4:]}" if len(value) > 8 else "******"


def get_config(plugin_id: str) -> dict:
    """读插件 config.json（缺失字段取 plugin.yaml settings default）。"""
    d = plugin_dir(plugin_id)
    saved: dict = {}
    try:
        v = json.loads((d / "config.json").read_text(encoding="utf-8"))
        if isinstance(v, dict):
            saved = v
    except (OSError, ValueError):
        pass
    out: dict = {}
    for f in settings_schema(plugin_id):
        key = f["key"]
        has = key in saved and saved[key] is not None
        if f["type"] == "secret":
            out[key] = _mask(str(saved[key])) if has else ""
            out[f"{key}__set"] = has
        else:
            out[key] = (
                saved[key] if has else f.get("default", "" if f["type"] != "boolean" else False)
            )
    out["__schema"] = settings_schema(plugin_id)
    out["__keys"] = [f["key"] for f in settings_schema(plugin_id)]
    return out


def save_config(plugin_id: str, values: dict) -> dict:
    """保存插件配置：类型校验 + secret 留空/脱敏串复用旧明文（不能用 get_config 的脱敏展示值回写）。"""
    d = plugin_dir(plugin_id)
    schema = settings_schema(plugin_id)
    # 旧值读磁盘明文（secret 复用需要原始值；get_config 返回的是脱敏展示值，写回会污染配置）
    old_raw: dict = {}
    try:
        old_raw = json.loads((d / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        old_raw = {}
    merged: dict = {}
    for f in schema:
        key = f["key"]
        raw = values.get(key)
        if f["type"] == "boolean":
            merged[key] = raw if isinstance(raw, bool) else (str(raw).strip().lower() in _BOOL)
        elif f["type"] in ("text", "select"):
            merged[key] = (str(raw) if raw is not None else "").strip()
        else:  # secret
            s = (str(raw) if raw is not None else "").strip()
            if not s or "***" in s:  # 留空 / 脱敏串 → 复用旧明文
                merged[key] = str(old_raw.get(key, ""))
            else:
                merged[key] = s
    (d / "config.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return get_config(plugin_id)


def load_module(plugin_id: str):
    """加载插件 main.py 模块（同 octop loader 方式；kind=service 供后端调用）。"""
    d = plugin_dir(plugin_id)
    entry = (d / "main.py") if (d / "main.py").is_file() else None
    if entry is None:
        raise ImportError(f"插件缺少入口文件：{plugin_id}")
    safe_id = plugin_id.replace("-", "_")
    module_name = f"market_plugin_{safe_id}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(
        module_name, entry, submodule_search_locations=[str(d)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载插件入口：{plugin_id}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def synthesize(plugin_id: str, text: str) -> bytes:
    """调用插件 synthesize(text)（TTS 等 kind=service 插件）。"""
    cfg = get_config(plugin_id)
    module = load_module(plugin_id)
    fn = getattr(module, "synthesize", None)
    if not callable(fn):
        raise RuntimeError(f"插件 {plugin_id} 未提供 synthesize()")
    return fn(text, cfg)
