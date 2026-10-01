"""core · V3 内核（Python 版 Cordis）：events / scope / context / fiber / skill / composition。

用法：
    bus = EventBus()                    # 5 种分发
    scope = Scope("global")             # 分层服务注册表
    registry = Registry(app, bus, scope)  # fiber 状态机 + 依赖驱动加载
    entries = resolve_profile(profile)  # 组合配置（应用 = 插件树）
"""
from .composition import ProfileEntry, default_profile, load_profile, resolve_profile
from .context import PluginContext
from .events import EventBus
from .fiber import Fiber, FiberState, Registry
from .scope import Scope
from .skill import SkillContribution

__all__ = [
    "EventBus", "Scope", "PluginContext", "Fiber", "FiberState", "Registry",
    "SkillContribution", "ProfileEntry", "resolve_profile", "load_profile", "default_profile",
]
