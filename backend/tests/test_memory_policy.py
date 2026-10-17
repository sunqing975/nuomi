"""记忆质量策略（app/infra/memory_policy）单测。

覆盖三处补丁：捕获只取用户消息、抽取 prompt 追加策略、召回地域过滤。
"""

from __future__ import annotations

import pytest

from app.infra.memory_policy import (
    POLICY_MARKER,
    filter_recall_result,
    install_memory_policies,
)


@pytest.fixture(scope="module", autouse=True)
def _installed() -> None:
    install_memory_policies()


def _snippet(text: str):
    from octop_memory.pipeline.recall import RecallSnippet

    return RecallSnippet(
        source_id="s1",
        timestamp_iso="2026-10-17T00:00:00Z",
        role_hint="atom",
        text=text,
        layer="atom",
    )


def _result(*texts: str):
    from octop_memory.pipeline.recall import RecallResult

    return RecallResult(snippets=[_snippet(t) for t in texts], rendered="original")


def test_capture_only_user_messages() -> None:
    from octop_memory.application import runtime as memory_runtime

    assert memory_runtime.DEFAULT_CAPTURE_CFG["include_roles"] == ["user"]


def test_extractor_prompt_has_policy_and_still_renders() -> None:
    from octop_memory.pipeline.extractor import prompts as extractor_prompts

    assert POLICY_MARKER in extractor_prompts._PROMPT_BODY_TEMPLATE
    rendered = extractor_prompts.render_prompt("[]")
    assert POLICY_MARKER in rendered
    assert "[]" in rendered


def test_install_is_idempotent() -> None:
    assert install_memory_policies() == []


def test_recall_guard_drops_other_location() -> None:
    filtered = filter_recall_result(
        _result("用户位于嘉兴（浙江）", "用户喜欢喝美式"), "北京今天天气怎么样"
    )
    assert [s.text for s in filtered.snippets] == ["用户喜欢喝美式"]
    assert "嘉兴" not in filtered.rendered


def test_recall_guard_keeps_matching_location() -> None:
    result = _result("用户位于嘉兴（浙江）")
    assert filter_recall_result(result, "我在嘉兴，北京天气呢").snippets == result.snippets


def test_recall_guard_keeps_locationless_query_untouched() -> None:
    result = _result("用户位于嘉兴（浙江）")
    assert filter_recall_result(result, "我有什么偏好").snippets == result.snippets


def test_recall_guard_clears_rendered_when_everything_dropped() -> None:
    filtered = filter_recall_result(_result("用户位于嘉兴（浙江）"), "上海天气")
    assert filtered.snippets == []
    assert filtered.rendered == ""


def test_guarded_recall_is_installed() -> None:
    import octop_memory.service as memory_service

    assert getattr(memory_service.recall_for_prompt, "_nuomi_guarded", False)


def test_recall_passes_atoms_only_policy(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from typing import Any

    import octop_memory.service as memory_service
    from octop_memory.core import Memory
    from octop_memory.pipeline.recall import RecallResult

    captured: dict[str, Any] = {}

    def fake_recall(memory: Any, query: str, **kwargs: Any) -> RecallResult:
        captured.update(kwargs)
        return RecallResult(snippets=[], rendered="")

    monkeypatch.setattr(memory_service, "recall_for_prompt", fake_recall)
    service = memory_service.MemoryService(
        Memory(
            namespace="test",
            backend="sqlite",
            backend_config={"db_path": str(tmp_path / "m.sqlite")},
        )
    )
    service.recall("你好")
    assert captured["raw_policy"] == "never"
    close = getattr(service, "close", None)
    if callable(close):
        close()


def test_atoms_only_recall_installed() -> None:
    from octop_memory.service import MemoryService

    assert getattr(MemoryService.recall, "_nuomi_atoms_only", False)
