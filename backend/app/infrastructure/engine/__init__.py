"""engine · 机制基础库（机制语言沉底，≈ Octop 的 octop-harness 定位）。

所有"怎么加载/怎么编排/怎么执行"的机制都在这里；领域包（domain/）依赖它，
engine 绝不反向依赖领域包或 transport。组成：
    events / scope / context / fiber / composition   —— 运行时内核
    loader / lifecycle / composer / runtime          —— 插件与模块生命周期
    approval / robust / skill                        —— 能力机制（审批门/健壮层/技能读取）

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
    "EventBus",
    "Scope",
    "PluginContext",
    "Fiber",
    "FiberState",
    "Registry",
    "SkillContribution",
    "ProfileEntry",
    "resolve_profile",
    "load_profile",
    "default_profile",
]
