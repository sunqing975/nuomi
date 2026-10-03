"""可观测 · trace 日志（Phase 3）。

每轮对话写一行 JSON 到 trace.jsonl：时间 / 会话 / 用户消息 / 调用的工具 /
回复长度 / 模型 / 耗时。文件即唯一权威来源（/logs 端点读它，脚本 tail 它）。
日志按大小轮转（默认 5MB，保留 3 个备份），避免长期运行无限膨胀。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

_MAX_BYTES = 5 * 1024 * 1024  # 单个日志文件上限
_KEEP_BACKUPS = 3


class TraceLogger:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _rotate(self):
        if not self.path.exists() or self.path.stat().st_size < _MAX_BYTES:
            return
        for i in range(_KEEP_BACKUPS - 1, 0, -1):
            bak = self.path.with_suffix(f".jsonl.{i}")
            if bak.exists():
                bak.replace(self.path.with_suffix(f".jsonl.{i + 1}"))
        if self.path.with_suffix(".jsonl.1").exists():
            self.path.with_suffix(".jsonl.1").unlink()
        self.path.replace(self.path.with_suffix(".jsonl.1"))

    def log(self, **fields):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._rotate()
        entry = {"ts": time.time(), **fields}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def tail(self, n: int = 20) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-n:]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return out


# 应用内单例（lifespan 注入）
_logger: TraceLogger | None = None


def set_logger(logger: TraceLogger):
    global _logger
    _logger = logger


def get_logger() -> TraceLogger:
    if _logger is None:
        raise RuntimeError("TraceLogger 尚未初始化")
    return _logger
