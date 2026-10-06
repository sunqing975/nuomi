"""插件导入的线程分工测试（P1 竞态回归）。

`PluginRegistry` 是**进程级单例**，`octop_harness.load_all()` 是「先 `clear()` 再逐个
注册」。所以：

- **文件操作**（zip 解包 / git clone / copytree）必须 offload 到线程池 —— 它们是秒级阻塞；
- **注册**（`plugin_service.sync()`）必须留在事件循环线程 —— 否则并发对话会在
  clear→register 的窗口期读到空注册表，该轮静默丢失全部插件工具（实测可观察到 0）。

这两条约束互相拉扯，很容易在某次重构里被破坏（本次就是先破坏了才发现），所以锁在这里。
"""

from __future__ import annotations

import threading
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.domain.plugins.service import plugin_service

MARKET_ZIP = Path(__file__).resolve().parents[1] / "assets" / "market" / "weather-octop.zip"


def _remove_plugin(client: TestClient, plugin_id: str) -> None:
    """测试用清理：会话级 client 共享同一临时工作区，重复导入会 400。"""
    client.delete(f"/api/plugins/{plugin_id}")


def test_import_plugin_zip_registers_and_exposes_tools(client: TestClient) -> None:
    """走真实 zip 的导入链路：落盘 → 注册 → 工具可装配。"""
    assert MARKET_ZIP.is_file(), f"缺少测试用市场包: {MARKET_ZIP}"
    _remove_plugin(client, "weather-octop")
    before = {p["plugin_id"] for p in plugin_service.list_all()}

    r = client.post(
        "/api/plugins/import",
        files={"file": ("weather.zip", MARKET_ZIP.read_bytes(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    plugin_id = body["plugin"]["plugin_id"]
    assert plugin_id not in before

    # 工作区确实落了目录
    assert (plugin_service.plugins_dir() / plugin_id / "plugin.yaml").is_file()
    # 注册表里有，且工具能装配出来
    assert plugin_id in {p["plugin_id"] for p in plugin_service.list_all()}
    names = {getattr(t, "name", "") for t in plugin_service.tools()}
    assert names, "导入后应至少装配出一个工具"


def test_file_work_is_offloaded_but_registration_stays_on_loop(
    client: TestClient, monkeypatch
) -> None:
    """核心断言：落盘在别的线程，注册在事件循环线程。

    若哪天有人把 `plugin_service.sync()` 也塞进 `asyncio.to_thread`，两者线程相同 →
    本用例失败（那正是注册表被清空的竞态来源）。
    """
    from app.domain import importer

    seen: dict[str, str] = {}
    real_sync = plugin_service.sync

    def spy_sync():
        seen["sync_thread"] = threading.current_thread().name
        return real_sync()

    real_import = importer.import_plugin_zip

    def spy_import(data: bytes):
        seen["import_thread"] = threading.current_thread().name
        return real_import(data)

    monkeypatch.setattr(plugin_service, "sync", spy_sync)
    monkeypatch.setattr(importer, "import_plugin_zip", spy_import)
    _remove_plugin(client, "weather-octop")

    r = client.post(
        "/api/plugins/import",
        files={"file": ("weather.zip", MARKET_ZIP.read_bytes(), "application/zip")},
    )
    assert r.status_code == 200, r.text

    assert "import_thread" in seen and "sync_thread" in seen, f"未观察到调用: {seen}"
    assert seen["import_thread"] != seen["sync_thread"], (
        f"注册与落盘在同一线程（{seen['sync_thread']}）→ sync 被 offload，"
        "并发对话会在注册表清空窗口期丢光插件工具"
    )


def test_plugin_sync_endpoint_returns_full_registry(client: TestClient) -> None:
    """`/plugins/sync` 返回的行数应与注册表一致（注册在循环上完成，无中间态泄漏）。"""
    rows = client.post("/api/plugins/sync").json()
    assert isinstance(rows, list)
    installed = {p["plugin_id"] for p in plugin_service.list_all()}
    assert {r["plugin_id"] for r in rows} == installed


def test_market_install_registers_plugin(client: TestClient, monkeypatch) -> None:
    """市场安装同样遵守「落盘 offload / 注册回循环」。"""
    from app.infra.plugins import market

    seen: dict[str, str] = {}
    real_sync = plugin_service.sync

    def spy_sync():
        seen["sync_thread"] = threading.current_thread().name
        return real_sync()

    real_install = market.install

    def spy_install(plugin_id: str):
        seen["install_thread"] = threading.current_thread().name
        return real_install(plugin_id)

    monkeypatch.setattr(plugin_service, "sync", spy_sync)
    monkeypatch.setattr(market, "install", spy_install)
    _remove_plugin(client, "tts")

    r = client.post("/api/plugins/market/install", json={"plugin_id": "tts"})
    assert r.status_code == 200, r.text
    manifest = yaml.safe_load((plugin_service.plugins_dir() / "tts" / "plugin.yaml").read_text())
    assert manifest["id"] == "tts"
    assert seen["install_thread"] != seen["sync_thread"]
