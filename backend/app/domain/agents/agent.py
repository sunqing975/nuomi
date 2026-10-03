"""Agent（实例）领域模型：agents 是 Expert（模板）的实例化，对齐 Octop Agent 生命周期。

领域语义：
  - Expert（专家模板，experts/<name>/）= 人格 + 能力模板资产，只读资产。
  - Agent（实例，workspace/agents.json）= 模板的实例化：引用 expert，携带自己的
    display_name / description / 状态（running | stopped）。用户创建/启动/停止/编辑/删除
    的是 Agent；运行时加载的是当前 Agent 引用的 Expert。
  - 单用户单运行时：start = 把该实例设为 current（重启生效，nuomi 哲学）；stop = 清空
    current（回落默认专家）。与 Octop 多进程 start/stop 语义对齐，落地为单实例切换。

存储：workspace/agents.json = {"current": id|null, "agents": {id: {...}}}。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Agent:
    """一个 Agent 实例（对齐 Octop Agent：模板实例 + 生命周期状态）。"""

    id: str
    name: str
    display_name: str
    expert: str  # 引用的专家模板名（experts/<expert>/）
    description: str = ""
    icon_name: str = ""
    color: str = ""
    status: str = "stopped"  # running | stopped
    created_at: str = ""
    updated_at: str = ""


def agents_path(workspace_dir: str | Path) -> Path:
    return Path(workspace_dir) / "agents.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_agents(path: str | Path) -> dict:
    """容错读取 agents 清单：{"current": id|null, "agents": {id: {...}}}。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("agents"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"current": None, "agents": {}}


def save_agents(path: str | Path, data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _to_agent(agent_id: str, raw: dict) -> Agent:
    return Agent(
        id=agent_id,
        name=str(raw.get("name", agent_id)),
        display_name=str(raw.get("display_name", raw.get("name", agent_id))),
        expert=str(raw.get("expert", "")),
        description=str(raw.get("description", "")),
        icon_name=str(raw.get("icon_name", "")),
        color=str(raw.get("color", "")),
        status=str(raw.get("status", "stopped")),
        created_at=str(raw.get("created_at", "")),
        updated_at=str(raw.get("updated_at", "")),
    )


def list_agents(path: str | Path) -> list[Agent]:
    data = load_agents(path)
    return [_to_agent(aid, raw) for aid, raw in sorted(data["agents"].items())]


def get_agent(path: str | Path, agent_id: str) -> Agent | None:
    raw = load_agents(path)["agents"].get(agent_id)
    return _to_agent(agent_id, raw) if raw else None


def current_agent_id(path: str | Path) -> str | None:
    cur = load_agents(path).get("current")
    return cur if cur in load_agents(path)["agents"] else None


def create_agent(
    path: str | Path,
    expert: str,
    display_name: str,
    description: str = "",
    icon_name: str = "",
    color: str = "",
) -> Agent:
    """从专家模板创建 Agent 实例（对齐 Octop create-from-template）。"""
    display_name = display_name.strip()
    if not display_name:
        raise ValueError("display_name 不能为空")
    base = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", display_name).strip() or "agent"
    slug = f"agent-{base}"
    data = load_agents(path)
    n = 2
    while slug in data["agents"]:
        slug = f"agent-{base}-{n}"
        n += 1
    now = _now()
    agent = Agent(
        id=slug,
        name=slug,
        display_name=display_name,
        expert=expert,
        description=description,
        icon_name=icon_name,
        color=color,
        status="stopped",
        created_at=now,
        updated_at=now,
    )
    data["agents"][slug] = asdict(agent)
    save_agents(path, data)
    return agent


def update_agent(
    path: str | Path,
    agent_id: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
) -> Agent | None:
    data = load_agents(path)
    raw = data["agents"].get(agent_id)
    if raw is None:
        return None
    if display_name is not None:
        display_name = display_name.strip()
        if not display_name:
            raise ValueError("display_name 不能为空")
        raw["display_name"] = display_name
    if description is not None:
        raw["description"] = description.strip()
    raw["updated_at"] = _now()
    save_agents(path, data)
    return _to_agent(agent_id, raw)


def set_current(path: str | Path, agent_id: str | None) -> None:
    """启动/停止：current=id 或 None（回落默认专家）。"""
    data = load_agents(path)
    if agent_id is not None and agent_id not in data["agents"]:
        raise ValueError(f"Agent 不存在：{agent_id}")
    data["current"] = agent_id
    for aid, raw in data["agents"].items():
        raw["status"] = "running" if aid == agent_id else "stopped"
        raw["updated_at"] = _now()
    save_agents(path, data)


def delete_agent(path: str | Path, agent_id: str) -> bool:
    data = load_agents(path)
    if agent_id not in data["agents"]:
        return False
    del data["agents"][agent_id]
    if data.get("current") == agent_id:
        data["current"] = None
    save_agents(path, data)
    return True


def current_expert_name(workspace_dir: str | Path, default: str) -> str:
    """当前运行的专家名：agents.json 的 current → 该实例的 expert；无 → 默认。

    兼容旧版：workspace/experts.json 的 expert_name 覆盖仍生效（专家选择器遗留）。
    """
    cur = current_agent_id(agents_path(workspace_dir))
    if cur:
        return get_agent(agents_path(workspace_dir), cur).expert  # type: ignore[union-attr]
    legacy = Path(workspace_dir) / "experts.json"
    try:
        name = json.loads(legacy.read_text(encoding="utf-8")).get("expert_name")
        if name:
            return str(name)
    except (OSError, ValueError):
        pass
    return default
