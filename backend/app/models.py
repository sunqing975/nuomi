"""models.py · 模型管理（供应商 → 模型 → 思考强度；供应商全部手动添加）。

对齐 DeepSeek Harness 的 ModelSelection 语义：{provider, model, reasoningEffort?}：
- 无内置预设供应商（用户明确要求：deepseek / doubao / local 都不该内置，全部手动添加）
- 供应商（custom_providers）：存 settings.global["custom_providers"]，OpenAI 兼容
  （name + base_url + api_key + protocol + models[]），设置面板统一增删改、随时挂进模型树
- 无 temperature：对齐 dsh（不暴露温度，交给提供商默认）
- API Key 一律掩码回显；无 key 的供应商标记不可用（输入栏模型菜单只列可用）
- 激活持久化：/api/models/activate 后写入 settings.global["active_model"]，启动时恢复
"""
from __future__ import annotations

import uuid

from langchain_openai import ChatOpenAI

# 思考强度展示名（effort 按模型声明）
EFFORT_LABELS: dict[str, str] = {
    "low": "省电",
    "medium": "标准",
    "high": "深度思考",
}

# settings.global 中自定义供应商的键名与内置供应商密钥前缀
CUSTOM_PROVIDERS_KEY = "custom_providers"
PROVIDER_KEY_PREFIX = "provider_"
ACTIVE_MODEL_KEY = "active_model"

# --- 自定义供应商工具 ---


def custom_key(base_url: str, name: str) -> str:
    """生成唯一供应商 key（url 主机 + 名称 slug + 随机后缀，避免重名覆盖）。"""
    import re

    host = re.sub(r"[^a-z0-9]", "", (base_url or "provider").split("//")[-1].split("/")[0].lower())[:16] or "provider"
    slug = re.sub(r"[^a-z0-9]", "", name.lower())[:12] or "custom"
    return f"custom-{host}-{slug}-{uuid.uuid4().hex[:4]}"


def mask_key(api_key: str | None) -> str:
    """回显掩码：sk-****wxyz（保留末 4 位；短 key 全掩）。"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * 4
    return api_key[:4] + "***" + api_key[-4:]


def _merge_custom(custom_providers: list[dict] | None) -> list[dict]:
    return list(custom_providers or [])


def _provider_keys_map(provider_keys: dict | None) -> dict:
    return dict(provider_keys or {})


def list_providers(
    current_provider: str | None = None,
    current_model: str | None = None,
    custom_providers: list[dict] | None = None,
    provider_keys: dict | None = None,
) -> dict:
    """返回供应商树：{providers: [{key, label, models, ...}]}（纯自定义供应商）。

    每个模型含 key / model（实际请求 id）/ label / description / efforts / active / available / configured。
    api_key 一律掩码回显；无 key 的供应商 unavailable（输入栏模型菜单只列可用）。
    """
    keys = _provider_keys_map(provider_keys)
    out = []
    for cp in _merge_custom(custom_providers):
        models = []
        for mk in cp.get("models", []):
            models.append(
                {
                    "key": mk["id"],
                    "model": mk["id"],
                    "label": mk.get("label") or mk["id"],
                    "description": mk.get("description") or "自定义供应商模型",
                    "efforts": mk.get("efforts") or ["medium"],
                    "context_window": mk.get("context_window"),
                    "max_output": mk.get("max_output"),
                    "active": cp["key"] == current_provider and mk["id"] == current_model,
                    "available": bool(cp.get("api_key") or keys.get(f"{PROVIDER_KEY_PREFIX}{cp['key']}")),
                    "configured": bool(cp.get("api_key")),
                }
            )
        out.append(
            {
                "key": cp["key"],
                "label": cp.get("name") or cp["key"],
                "base_url": cp.get("base_url", ""),
                "protocol": cp.get("protocol", "openai"),
                "custom": True,
                "configured": bool(cp.get("api_key")),
                "api_key_masked": mask_key(cp.get("api_key")),
                "models": models,
            }
        )
    return {"providers": out}


def find_model(
    provider: str,
    model_key: str,
    custom_providers: list[dict] | None = None,
    provider_keys: dict | None = None,
) -> dict | None:
    """校验 供应商+模型 存在且可用（含 API Key），返回模型定义或 None。"""
    keys = _provider_keys_map(provider_keys)
    for cp in _merge_custom(custom_providers):
        if cp["key"] == provider:
            if not (cp.get("api_key") or keys.get(f"{PROVIDER_KEY_PREFIX}{provider}")):
                return None  # 无 key → 不可用
            for mk in cp.get("models", []):
                if mk["id"] == model_key:
                    return {
                        "id": mk["id"],
                        "efforts": mk.get("efforts") or ["medium"],
                        "context_window": mk.get("context_window"),
                        "max_output": mk.get("max_output"),
                        "_custom": True,
                    }
            return None
    return None


def default_model(provider: str, custom_providers: list[dict] | None = None) -> str:
    """默认模型：取该供应商第一个模型 id。"""
    for cp in _merge_custom(custom_providers):
        if cp["key"] == provider and cp.get("models"):
            return cp["models"][0]["id"]
    raise KeyError(provider)


def build_model_llm(
    provider: str,
    model_key: str,
    effort: str | None = None,
    custom_providers: list[dict] | None = None,
    provider_keys: dict | None = None,
) -> ChatOpenAI:
    """按 供应商+模型 构建 ChatOpenAI（OpenAI 兼容；自定义供应商同协议）。

    - 无 temperature（对齐 dsh：不暴露温度，提供商默认）
    - effort 若在模型声明的 efforts 内，经 extra_body 透传 reasoning_effort
    - 模型声明的 max_output 绑定 max_tokens（截断单次输出）；context_window 存档备用（后续压缩/计量）
    - 内置供应商 key：设置写入优先，其次环境变量；自定义供应商用自带 api_key
    """
    keys = _provider_keys_map(provider_keys)
    cp = next((x for x in _merge_custom(custom_providers) if x["key"] == provider), None)
    if cp is None:
        raise KeyError(f"未知供应商：{provider}")
    mk = next((x for x in cp.get("models", []) if x["id"] == model_key), None)
    if mk is None:
        raise KeyError(f"未知模型：{provider}/{model_key}")
    api_key = cp.get("api_key") or keys.get(f"{PROVIDER_KEY_PREFIX}{provider}") or ""
    base_url = cp.get("base_url", "")
    efforts = mk.get("efforts") or ["medium"]
    kwargs: dict = dict(
        model=model_key,
        api_key=api_key,
        base_url=base_url,
        streaming=True,
    )
    max_output = mk.get("max_output")
    if max_output:
        kwargs["max_tokens"] = int(max_output)
    if effort and effort in efforts:
        kwargs["extra_body"] = {"reasoning_effort": effort}
    return ChatOpenAI(**kwargs)


def fetch_available_models(base_url: str, api_key: str = "") -> list[str]:
    """调用 OpenAI 兼容 /models 拉取可用模型 id 列表（自定义供应商设置用）。"""
    import requests

    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    data = r.json()
    ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict)]
    return [i for i in ids if isinstance(i, str) and i]
