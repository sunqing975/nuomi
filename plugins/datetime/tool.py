"""datetime 能力型插件示例。

插件契约：入口模块必须导出 `TOOLS`（list，元素为 @tool 函数或 BaseTool）。
加载器（backend/app/skills.py）扫描 plugin.json 后自动注入 LangGraph agent。
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


@tool
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    """获取指定时区的当前日期、时间与星期。传入 IANA 时区名，如 Asia/Shanghai、UTC。"""
    now = datetime.now(ZoneInfo(timezone))
    return f"{now:%Y-%m-%d %H:%M:%S} {_WEEKDAYS[now.weekday()]}（{timezone}）"


TOOLS = [get_current_time]
