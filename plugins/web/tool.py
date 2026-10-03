"""web 能力型插件：http_get 抓取网页正文。

stdlib 实现（urllib + HTMLParser），不引额外依赖；robust 由 plugin.json
统一配置（超时 10s + 重试 1 次）。演示"浏览器/MCP 版可按需替换"：
换 playwright/MCP 插件即可升级为完整浏览器能力。
"""

from __future__ import annotations

import re
import urllib.request
from html.parser import HTMLParser

from langchain_core.tools import tool

_MAX_TEXT = 3000


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        raw = re.sub(r"\s+", " ", raw).strip()
        return raw


@tool
def http_get(url: str, max_chars: int = _MAX_TEXT) -> str:
    """抓取一个网页并返回正文文本（最多 max_chars 字符）。用于查资料、读页面内容。"""
    if not url.startswith(("http://", "https://")):
        return "URL 必须以 http:// 或 https:// 开头"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 NuomiCompanion/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read(512 * 1024)  # 最多读 512KB
        charset = resp.headers.get_content_charset() or "utf-8"
        html = body.decode(charset, errors="replace")
        parser = _TextExtractor()
        parser.feed(html)
        title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        out = f"标题：{title.group(1).strip()}\n" if title else ""
        out += parser.text()
        return out[:max_chars] or "（页面无可提取的正文文本）"
    except Exception as e:
        return f"抓取失败：{e.__class__.__name__}: {e}"


TOOLS = [http_get]
