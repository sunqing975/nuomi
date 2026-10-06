"""transport 层共享请求体（跨域复用，避免一个域 import 另一个域的 body 定义）。

P0-2 拆分 api.py 时从各域抽出：GitImportBody 被 plugins 与 skills 两个域共用。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GitImportBody(BaseModel):
    """git 仓库导入请求体。"""

    url: str = Field(..., min_length=4, description="仓库地址（https/ssh/git@）")
