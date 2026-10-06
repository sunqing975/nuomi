"""敏感 JSON 落盘：原子写 + 0600 权限。

工作区里有四个文件存的是明文密钥（``providers.json`` / ``env.json`` /
``langfuse.json`` / ``connectors.json``），原实现是 ``Path.write_text``：

- **非原子**：写到一半进程被杀 → 文件截断；而读取侧一律「解析失败就静默回退默认值」
  （providers_store 回退 .env 种子、env_store 返回空），用户会看到「配置凭空消失」
  且没有任何提示。
- **权限 0644**：同机其它用户可读。仓库根的 ``.env`` 是 0600，工作区这几个反而是 0644。

这里统一成：写到同目录临时文件 → ``chmod 0600`` → ``os.replace`` 原子替换。
``os.replace`` 在同一文件系统内是原子的，所以读侧永远看到旧版本或新版本，不会看到半个文件。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

SECRET_MODE = 0o600


def write_json(path: Path, data, *, indent: int = 2) -> None:
    """原子写 JSON（先 0600 临时文件再 replace）；失败时清理临时文件并抛出。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=indent)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, SECRET_MODE)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def tighten(path: Path) -> None:
    """把已存在的敏感文件权限收紧到 0600（对旧文件补一刀，失败静默）。"""
    try:
        if path.is_file() and (path.stat().st_mode & 0o777) != SECRET_MODE:
            os.chmod(path, SECRET_MODE)
    except OSError:
        pass
