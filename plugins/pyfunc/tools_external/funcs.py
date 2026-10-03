"""模拟"外部插件格式"（无 LangChain 依赖，普通函数 + register 标记）。

假设这是从别的智能体生态（Codex/Claude 技能、某个开源仓库）拿来的能力包，
adapter.py 负责把它们转成自家插件体系的工具。
"""

from __future__ import annotations


def register(fn):
    fn._registered = True  # noqa: SLF001  adapter 靠这个标记识别
    return fn


@register
def calc_add(a: int, b: int) -> int:
    """两个整数相加，返回和。"""
    return a + b


@register
def greeting(name: str) -> str:
    """生成一句问候语。"""
    return f"你好，{name}！今天也要元气满满呀 🐾"
