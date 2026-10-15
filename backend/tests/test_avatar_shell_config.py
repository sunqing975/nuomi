"""壳 config 播种（2026-10-06：config.json 改为本机文件、不入库）。

为什么要有这条测试：config.json 一旦不在（全新克隆），后端「读→改→整体写回」的
三处（开关 / 切模型 / 删模型）会拿空 dict 去写，把 llm.api_url / tts / bert 全丢掉
—— 壳下次启动连不上后端，而且现象离改动点很远，很难查。
"""

from __future__ import annotations

import json

from app.domain.avatar import service


def _make_example(tmp_path, monkeypatch):
    shell_config = tmp_path / "config.json"
    example = tmp_path / "config.example.json"
    example.write_text(
        json.dumps(
            {
                "llm": {"api_url": "http://127.0.0.1:8000/api/v1", "model": "nuomi"},
                "tts": {"enabled": False, "url": "http://127.0.0.1:5006"},
                "bert": {"enabled": True, "url": "http://127.0.0.1:6007/classify"},
                "ui": {"intro_text": "你好", "avatar_enabled": True},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "SHELL_CONFIG", shell_config)
    monkeypatch.setattr(service, "SHELL_CONFIG_EXAMPLE", example)
    return shell_config, example


def test_missing_shell_config_is_seeded_from_example(tmp_path, monkeypatch):
    shell_config, _ = _make_example(tmp_path, monkeypatch)
    assert not shell_config.exists()

    assert service.set_avatar_enabled(False) is False

    cfg = json.loads(shell_config.read_text(encoding="utf-8"))
    # 开关写进去了，模板里其它段一个都不能少
    assert cfg["ui"]["avatar_enabled"] is False
    assert cfg["llm"]["api_url"] == "http://127.0.0.1:8000/api/v1"
    assert cfg["tts"]["url"] == "http://127.0.0.1:5006"
    assert cfg["bert"]["enabled"] is True


def test_existing_shell_config_is_not_overwritten_by_example(tmp_path, monkeypatch):
    shell_config, example = _make_example(tmp_path, monkeypatch)
    shell_config.write_text(
        json.dumps({"llm": {"api_url": "http://127.0.0.1:9999/api/v1"}, "ui": {"model": "m1"}}),
        encoding="utf-8",
    )

    service.set_avatar_enabled(True)

    cfg = json.loads(shell_config.read_text(encoding="utf-8"))
    assert cfg["llm"]["api_url"] == "http://127.0.0.1:9999/api/v1"  # 本机值不被模板盖掉
    assert cfg["ui"]["model"] == "m1"
    assert cfg["ui"]["avatar_enabled"] is True


def test_readers_work_before_first_write(tmp_path, monkeypatch):
    """读侧（开关缺省=开、无选中模型）在文件还不存在时也要能答，不能抛。"""
    _make_example(tmp_path, monkeypatch)
    assert service.get_avatar_enabled() is True
    assert service.get_active_model() is None
