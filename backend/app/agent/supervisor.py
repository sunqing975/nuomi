"""Phase 4b · 多智能体编排：Supervisor 路由器（LangGraph）。

架构（对应面试常问的 Supervisor 模式）：
- 一个 **router 节点**：LLM 读用户消息，分派给哪个子 Agent
  （companion 陪伴 / researcher 研究）。
- 两个 **子 Agent**（create_agent，各自带精简工具集）：
  - companion：人设 + 记忆 + 时间 + 便签（轻量日常陪伴）
  - researcher：知识库 + 计算 + 便签（信息核查，强调不编造）
- 子 Agent 作为 subgraph 节点嵌入主 StateGraph，输出经 add_messages
  合并回主消息流；主图持 checkpointer（对话持久化）。

设计取舍（如实标注）：子 Agent 不单独持 checkpointer，历史由主图承载
（内存子 Agent + 持久主图，是 Supervisor 常见形态；换持久子 Agent
只需给 create_agent 传 checkpointer 并按子命名空间隔离）。
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

ROUTER_PROMPT = (
    "你是糯米的多智能体调度器。根据用户最后一条消息判断交给谁处理：\n"
    "- 用户在闲聊、倾诉、需要陪伴/记住个人偏好、问时间或让记便签 → companion\n"
    "- 用户要查资料、问知识库内容、做计算、核查信息 → researcher\n"
    "只输出一个词：companion 或 researcher。"
)

COMPANION_PROMPT = (
    "你是糯米，一只住在电脑里的小猫伙伴。说话简短自然，1-3 句，像亲密朋友。"
    "记住用户的偏好；需要真实信息时用工具，不编造。"
)

RESEARCHER_PROMPT = (
    "你是糯米的研究员子智能体。任务是查证和整理信息：优先用知识库与工具，"
    "给出有依据的回答；查不到就明确说查不到，绝不编造。回答用中文，简洁分点。"
)


class State(TypedDict):
    messages: Annotated[list, add_messages]
    next: str


class Route(BaseModel):
    next: str = Field(description="companion 或 researcher")


def build_supervisor(
    llm: BaseChatModel,
    tools: list[BaseTool],
    checkpointer=None,
    router=None,
):
    """router 可注入（测试用确定性路由）；默认用 LLM 结构化输出路由。"""
    # 全能化（Phase 5）：子 agent 共享全量工具，不再按角色硬编码白名单——
    # companion/researcher 的差异在 system prompt（陪伴 vs 严谨查证），工具都放开。
    companion_tools = tools
    researcher_tools = tools

    from langchain.agents import create_agent

    companion = create_agent(model=llm, tools=companion_tools, system_prompt=COMPANION_PROMPT)
    researcher = create_agent(model=llm, tools=researcher_tools, system_prompt=RESEARCHER_PROMPT)

    if router is None:
        # 路由：纯文本 JSON 解析，不绑定工具。
        # DeepSeek 思考模式不接受 tool_choice（function_calling 绑定会报
        # "Thinking mode does not support this tool_choice"），且不支持 json_schema。
        router = None

    async def router_node(state: State):
        last = state["messages"][-1]
        if router is not None:
            res = await router.ainvoke([SystemMessage(content=ROUTER_PROMPT), last])
            # 路由 LLM 解析失败（如 FakeChatModel/弱模型返回 None）→ 回退陪伴
            if res is None:
                return {"next": "companion"}
            nxt = getattr(res, "next", None) or (res.get("next") if isinstance(res, dict) else None)
            return {"next": "researcher" if nxt == "researcher" else "companion"}
        # 兼容路径：直接让 LLM 输出 JSON 路由（DeepSeek thinking / 任意模型）
        try:
            res = await llm.ainvoke(
                [SystemMessage(content=ROUTER_PROMPT + "\n只输出 JSON：{\"next\": \"companion\" 或 \"researcher\"}"), last]
            )
            import json as _json
            import re as _re

            txt = str(res.content).strip()
            m = _re.search(r"\{.*\}", txt, _re.S)
            data = _json.loads(m.group(0)) if m else {}
            return {"next": "researcher" if data.get("next") == "researcher" else "companion"}
        except Exception:
            return {"next": "companion"}

    g = StateGraph(State)
    g.add_node("router", router_node)
    g.add_node("companion", companion)
    g.add_node("researcher", researcher)
    g.add_edge(START, "router")
    g.add_conditional_edges(
        "router",
        lambda s: s["next"],
        {"companion": "companion", "researcher": "researcher"},
    )
    g.add_edge("companion", END)
    g.add_edge("researcher", END)
    info = {
        "companion": {"agent": companion, "tools": [t.name for t in companion_tools]},
        "researcher": {"agent": researcher, "tools": [t.name for t in researcher_tools]},
    }
    return g.compile(checkpointer=checkpointer), info


def summarize_supervisor_reply(ai_msg: AIMessage) -> str:
    """子 Agent 输出统一为 AIMessage，取文本。"""
    return str(ai_msg.content)
