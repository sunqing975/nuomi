"""记忆质量策略（糯米侧的车门锁）。

为什么需要这个模块
------------------
记忆的捕获 / 抽取 / 召回实现全在两个第三方包里（ ``octop-memory`` 与
``octop-harness`` ），它们**没有暴露**「只从用户消息捕获」「抽取规则」「召回后
过滤」的配置钩子：``HarnessAgentConfig`` 只有开关和触发节奏（见
``octop_harness.config`` 里的 ``memory_*`` 字段），``octop_harness/memory/
runtime.py`` 构造 ``MemoryService`` 时也不传 ``MemoryRuntimeConfig``。

用户反馈的四个问题——助手的话被当成事实、一次性操作被当长期记忆、同一件事换措
辞反复抽、查北京天气却召回「用户在嘉兴」——按上面三个环节各自有解，于是在应用
启动时做三处**最小侵入**的策略补丁，集中在本模块，便于随上游升级一起检查：

1. ``_install_capture_user_only``：捕获层 ``include_roles=["user"]``。助手消息
   不再进 raw，抽取器就没有助手原话可引（实测 61.5% 的原子引文来自
   ``assistant_message``）。
2. ``_install_extractor_policy``：给抽取 prompt 追加「糯米记忆策略」硬规则：只抽
   跨会话稳定信息；一次性操作、工具返回、演示数据、助手自述一律不抽；同一事实
   不换措辞重复抽；数量类断言不抽；矛盾只报冲突不自行裁决。
3. ``_install_recall_guard``：召回后置过滤。查询里点名了 A 地、召回的却是 B 地
   的事实（「查北京天气」召回「用户在嘉兴」）这类地域错配片段直接丢弃，并按过滤
   后的片段重新拼装注入文本。

约定
----
* 只在进程启动时调用一次 ``install_memory_policies()``（幂等，重复调用无副作用）。
* 上游结构变化时打 warning 而不是抛异常：铁律是「记忆策略失效可以接受，启动失败
  不可以接受」。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

POLICY_MARKER = "## NUOMI MEMORY POLICY"

#: 召回过滤用到的地点名。只放「事实性地点」，不放泛指词，避免误杀。
LOCATIONS: frozenset[str] = frozenset(
    {
        "北京",
        "上海",
        "天津",
        "重庆",
        "嘉兴",
        "杭州",
        "宁波",
        "苏州",
        "南京",
        "无锡",
        "温州",
        "金华",
        "绍兴",
        "湖州",
        "台州",
        "广州",
        "深圳",
        "东莞",
        "佛山",
        "珠海",
        "汕头",
        "惠州",
        "成都",
        "武汉",
        "西安",
        "长沙",
        "郑州",
        "合肥",
        "福州",
        "厦门",
        "泉州",
        "南昌",
        "济南",
        "青岛",
        "烟台",
        "沈阳",
        "大连",
        "长春",
        "哈尔滨",
        "石家庄",
        "太原",
        "呼和浩特",
        "兰州",
        "西宁",
        "银川",
        "乌鲁木齐",
        "拉萨",
        "昆明",
        "贵阳",
        "南宁",
        "桂林",
        "海口",
        "三亚",
        "香港",
        "澳门",
        "台北",
    }
)


def _locations_in(text: str) -> set[str]:
    return {name for name in LOCATIONS if name in text}


def _keep_snippet(snippet: Any, query_locations: set[str]) -> bool:
    """查询点名了地点时，过滤掉「其他地点」的事实片段。

    只处理「片段里出现了明确地点」的情况：片段没有地点则保留（多数记忆与地域无
    关）；片段地点命中了查询地点则保留；片段只有别的地点且与查询无交集，视为跟
    这次查询无关（典型是「查北京天气」召回「用户在嘉兴」）。
    """
    if not query_locations:
        return True
    text = str(getattr(snippet, "text", "") or "")
    snippet_locations = _locations_in(text)
    if not snippet_locations:
        return True
    return bool(snippet_locations & query_locations)


def filter_recall_result(result: Any, query: str) -> Any:
    """按地域相关性过滤 ``RecallResult``；未发生过滤时原样返回。"""
    query_locations = _locations_in(query or "")
    if not query_locations:
        return result
    snippets = list(getattr(result, "snippets", []) or [])
    kept = [s for s in snippets if _keep_snippet(s, query_locations)]
    if len(kept) == len(snippets):
        return result

    from octop_memory.pipeline.recall import RecallResult, _render

    rendered = _render(kept, query) if kept else ""
    logger.debug(
        "memory recall 地域过滤: query_locations=%s dropped=%d kept=%d",
        sorted(query_locations),
        len(snippets) - len(kept),
        len(kept),
    )
    return RecallResult(snippets=kept, rendered=rendered)


def _install_capture_user_only() -> list[str]:
    from octop_memory.application import runtime as memory_runtime

    cfg = dict(getattr(memory_runtime, "DEFAULT_CAPTURE_CFG", {}) or {})
    if cfg.get("include_roles") == ["user"]:
        return []
    cfg["include_roles"] = ["user"]
    memory_runtime.DEFAULT_CAPTURE_CFG = cfg
    return ["capture.include_roles=['user']"]


_EXTRACTOR_POLICY = """
## NUOMI MEMORY POLICY (added by the host application; takes precedence over the rules above)

The end user asked for a much stricter memory. Additional mandatory rules:

1. Only extract durable, cross-session facts about the USER and their world:
   identity/profile, stable preferences, standing decisions, long-lived project
   facts, explicit agreements.
2. Do NOT extract one-off actions or their results: tool calls that were run,
   report submissions, weather/data lookups, demo/example payloads, greetings,
   tests, or anything that was true only during this conversation.
3. Do NOT extract from assistant messages, tool results, or the assistant's own
   capabilities or self-description. If a candidate's only support is the
   assistant's words, skip it.
4. Durability test: would this still be useful and true in a month, in a
   different conversation? If not, skip it.
5. Never restate an existing memory with different wording. Prefer zero
   candidates over near-duplicates.
6. Do NOT extract counts or "how many times the user did X" claims; they are
   unreliable.
7. Conflicting information: emit a conflict candidate and stop. Never rewrite,
   supersede or deprecate older memories yourself.

"""


def _install_extractor_policy() -> list[str]:
    from octop_memory.pipeline.extractor import prompts as extractor_prompts

    template = getattr(extractor_prompts, "_PROMPT_BODY_TEMPLATE", None)
    if not isinstance(template, str):
        logger.warning("memory 策略：抽取 prompt 模板结构变化，跳过抽取策略补丁")
        return []
    if POLICY_MARKER in template:
        return []
    anchor = "Now process the actual input."
    if anchor not in template:
        logger.warning("memory 策略：抽取 prompt 锚点缺失，跳过抽取策略补丁")
        return []
    extractor_prompts._PROMPT_BODY_TEMPLATE = template.replace(
        anchor, _EXTRACTOR_POLICY.lstrip("\n") + anchor, 1
    )
    return ["extractor.prompt_policy"]


def _install_recall_guard() -> list[str]:
    import octop_memory.service as memory_service

    original = getattr(memory_service, "recall_for_prompt", None)
    if original is None or getattr(original, "_nuomi_guarded", False):
        return []

    def guarded(memory: Any, query: str, **kwargs: Any) -> Any:
        result = original(memory, query, **kwargs)
        try:
            return filter_recall_result(result, query)
        except Exception:  # noqa: BLE001 - 召回过滤失败不能影响对话
            logger.warning("memory 策略：召回地域过滤失败，按原结果返回", exc_info=True)
            return result

    guarded._nuomi_guarded = True  # type: ignore[attr-defined]
    memory_service.recall_for_prompt = guarded
    return ["recall.location_guard"]


def _install_recall_atoms_only() -> list[str]:
    """自动注入只注入蒸馏后的原子事实，不再回退到 raw 原文。

    上游 ``raw_policy`` 默认 ``"fallback"``：没有原子命中时把历史 raw（旧数据里
    大量是助手原话，如「你好呀 ✨ 我在的」）整段注入 prompt——既噪声大，又把助手
    的话固化成「记忆」。用户明确要「只记跨会话稳定事实」，所以自动注入关闭 raw
    回退；``memory_search`` 工具仍可按需检索全部语料，能力不丢。
    """
    import octop_memory.service as memory_service
    from octop_memory.service import MemoryService

    if getattr(MemoryService.recall, "_nuomi_atoms_only", False):
        return []

    def recall(
        self: Any,
        query: str,
        *,
        thread_id: str | None = None,
        session_id: str | None = None,
        limit: int = memory_service.DEFAULT_RECALL_LIMIT,
    ) -> Any:
        return memory_service.recall_for_prompt(
            self._memory,
            query,
            thread_id=thread_id,
            session_id=session_id,
            limit=limit,
            raw_policy="never",
        )

    recall._nuomi_atoms_only = True  # type: ignore[attr-defined]
    MemoryService.recall = recall  # type: ignore[method-assign]
    return ["recall.atoms_only"]


def install_memory_policies() -> list[str]:
    """安装全部记忆策略补丁，返回实际生效的补丁名（幂等）。"""
    applied: list[str] = []
    for installer in (
        _install_capture_user_only,
        _install_extractor_policy,
        _install_recall_guard,
        _install_recall_atoms_only,
    ):
        try:
            applied.extend(installer())
        except Exception:  # noqa: BLE001 - 策略失效可接受，启动失败不可接受
            logger.warning("memory 策略：补丁 %s 安装失败", installer.__name__, exc_info=True)
    if applied:
        logger.info("memory 策略已生效: %s", ", ".join(applied))
    return applied
