"""敏感配置存储测试：脱敏语义 + 原子写 + 0600 权限。

对应第 1 周第 9b/9c 项。这些行为一旦回退，后果是「明文密钥经接口泄漏」或
「用户保存配置后被静默还原成旧值」，都属于很难从现象反推的问题。
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from app.infra import env_store
from app.infra.secret_file import write_json

# ---------- 脱敏 ----------


def test_secret_keys_are_masked_plain_keys_are_not() -> None:
    masked = env_store.mask_all(
        {
            "OPENAI_API_KEY": "sk-abcdefghijklmnop",
            "TTS_TOKEN": "tok-abcdefghij",
            "MY_PASSWORD": "hunter2hunter2",
            "MY_CITY": "杭州",
            "TIMEOUT": "30",
        }
    )
    assert masked["OPENAI_API_KEY"] == "sk-a***mnop"
    assert masked["MY_CITY"] == "杭州"  # 非密钥键照常可读
    assert masked["TIMEOUT"] == "30"
    assert "***" in masked["MY_PASSWORD"]
    assert "hunter2" not in masked["MY_PASSWORD"]


def test_short_secret_is_fully_masked() -> None:
    assert env_store.mask_all({"API_KEY": "short"})["API_KEY"] == "******"
    assert env_store.mask_all({"API_KEY": ""})["API_KEY"] == ""


def test_masked_value_round_trip_keeps_real_secret() -> None:
    """前端拿到脱敏值原样回写，真实密钥不能被覆盖（与 providers 同语义）。"""
    env_store.save({"OPENAI_API_KEY": "sk-real-secret-123456"})
    out = env_store.save({"OPENAI_API_KEY": "sk-r***3456"})
    assert out["OPENAI_API_KEY"] == "sk-real-secret-123456"


def test_real_new_secret_still_updates() -> None:
    env_store.save({"OPENAI_API_KEY": "sk-old-secret-123456"})
    out = env_store.save({"OPENAI_API_KEY": "sk-brand-new-999999"})
    assert out["OPENAI_API_KEY"] == "sk-brand-new-999999"


def test_non_secret_value_containing_stars_is_not_mistaken_for_mask() -> None:
    """普通配置的值里恰好含 `***` 不能被当成脱敏串还原（曾是实现漏洞）。"""
    env_store.save({"MY_CITY": "A***B"})
    out = env_store.save({"MY_CITY": "C***D"})
    assert out["MY_CITY"] == "C***D"


def test_masked_rule_does_not_create_keys_from_nothing() -> None:
    """旧值不存在的 key 传脱敏串：不能凭空造出一条旧密钥。"""
    out = env_store.save({"FRESH_API_KEY": "abc***xyz"})
    assert out["FRESH_API_KEY"] == "abc***xyz"


def test_deleted_keys_are_removed() -> None:
    env_store.save({"A_TOKEN": "1", "B_TOKEN": "2"})
    env_store.save({"B_TOKEN": "2"})
    assert "A_TOKEN" not in env_store.load()


def test_real_change_containing_stars_is_not_swallowed() -> None:
    """密钥键**真的**改成含 `***` 的新值时必须落盘（曾用「含 ***」当哨兵 → 静默丢弃）。"""
    env_store.save({"MY_SECRET": "old-value-1"})
    out = env_store.save({"MY_SECRET": "new***value"})
    assert out["MY_SECRET"] == "new***value"


def test_secret_key_detection_is_word_anchored() -> None:
    """未锚定的正则会把 MONKEY / KEYWORD_X / TOKENIZER_PATH 误判成密钥。"""
    assert env_store.is_secret_key("OPENAI_API_KEY")
    assert env_store.is_secret_key("MY_SECRET")
    assert env_store.is_secret_key("TTS_TOKEN")
    assert env_store.is_secret_key("DB_PASSWORD")
    for not_secret in ("MONKEY", "KEYWORD_X", "TOKENIZER_PATH", "MY_CITY", "TIMEOUT"):
        assert not env_store.is_secret_key(not_secret), f"{not_secret} 被误判为密钥"


def test_sentinel_requires_exact_mask_match() -> None:
    assert env_store.is_masked_sentinel("sk-r***3456", "sk-real-secret-123456")
    assert not env_store.is_masked_sentinel("sk-r***345", "sk-real-secret-123456")
    assert not env_store.is_masked_sentinel("new***value", "old-value-1")
    assert not env_store.is_masked_sentinel("anything", "")  # 无旧值


# ---------- 落盘安全 ----------


def test_env_file_is_0600(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(env_store.settings, "nuomi_home", str(tmp_path), raising=False)
    env_store.save({"X_API_KEY": "v"})
    mode = stat.S_IMODE(env_store.env_path().stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_write_json_is_atomic_and_leaves_no_temp_files(tmp_path) -> None:
    target = tmp_path / "secrets.json"
    write_json(target, {"a": 1})
    write_json(target, {"a": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "secrets.json"]
    assert leftovers == [], f"残留临时文件: {leftovers}"


def test_write_json_cleans_up_on_failure(tmp_path) -> None:
    """序列化失败不能留下半截文件或临时文件（序列化在 mkstemp 之前，故连临时文件都不该有）。"""
    target = tmp_path / "secrets.json"
    write_json(target, {"ok": True})

    class _Boom:
        pass

    with pytest.raises(TypeError):
        write_json(target, {"bad": _Boom()})

    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}  # 旧内容完好
    assert [p.name for p in tmp_path.iterdir() if p.name != "secrets.json"] == []


def test_tmp_file_is_not_world_readable_before_chmod(tmp_path) -> None:
    """mkstemp 本身就是 0600，chmod 之前没有可读窗口。"""
    import tempfile

    fd, name = tempfile.mkstemp(dir=tmp_path)
    try:
        assert stat.S_IMODE(os.stat(name).st_mode) == 0o600
    finally:
        os.close(fd)
        os.unlink(name)
