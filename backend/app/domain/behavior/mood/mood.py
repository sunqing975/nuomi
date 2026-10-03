"""mood · 内核模块（modules/，v0.7 三区：模块=内核组成部分）。

订阅 RESPONSE_DONE 事件，用轻量规则分析回复情绪 → app.state.last_emotion。
/ api/chat 的 done 事件携带 emotion，前端 PetBuddy 播放对应表情后回 idle。
规则可扩展（关键词/标点/语气）；停用模块 = 表情回到 idle（无情绪分析）。
"""

from app.infrastructure.engine.runtime import RESPONSE_DONE

# 简单规则：命中优先在前。每个规则 = (情绪名, 触发词元组)
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("surprised", ("哇", "天哪", "居然", "没想到", "竟然", "太意外", "?!", "？！")),
    ("excited", ("太棒了", "厉害", "太好了", "耶", "搞定", "成功", "哇塞", "nice", "！")),
    ("happy", ("哈哈", "嘻嘻", "嘿嘿", "开心", "喜欢", "真棒", "可爱", "😄", "😊", ":)")),
    ("curious", ("？", "?", "为什么", "怎么", "想不想", "你知道", "好奇", "让我想想", "嗯…")),
    ("shy", ("喵", "蹭蹭", "撒娇", "尾巴", "不好意思", "害羞", "~")),
    ("proud", ("我可", "当然", "我可厉害", "小意思", "这有什么难", "我可是")),
    ("sad", ("对不起", "抱歉", "难过", "心疼", "别难过", "可惜", "遗憾", "呜呜")),
    ("neutral", ()),
]

_EMOJI = ("😄", "😊", "🐾", "🎉", "✨", "🥰", "😂")


def apply(ctx) -> None:
    def _on_response_done(payload) -> None:
        ctx.app.state.last_emotion = analyze_emotion(payload.get("reply", ""))

    ctx.on(RESPONSE_DONE, _on_response_done)
    ctx.app.state.last_emotion = "neutral"


def analyze_emotion(text: str) -> str:
    """轻量规则情绪分析：关键词 → 情绪。空/默认回 neutral。"""
    if not text:
        return "neutral"
    for emotion, triggers in RULES:
        if emotion == "neutral":
            continue
        if any(t in text for t in triggers):
            return emotion
    return "neutral"
