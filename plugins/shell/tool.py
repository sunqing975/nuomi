"""shell 能力插件：bash 命令执行 + 逻辑沙箱（read-only / workspace-write / full-access）。

安全模型（对齐 dsh sandbox seam 的语义，逻辑层实现）：
- read-only        ：只读查询；写命令黑名单 + 重定向符拦截
- workspace-write  ：允许写，但 cwd 锚定工作区根，逃逸工作区的写（.. 穿越 / 绝对路径写）被拦截
- full-access      ：无限制；独立工具 bash_full，plugin.json `approval` 标记进审批门
通用约束（所有模式）：
- 环境白名单（剥离 API key 等敏感变量，防模型经 shell 读密钥）
- 超时（settings.shell_timeout）+ 输出截断（settings.shell_max_output）
- bash -c 执行，不加载用户 shell 配置（无 -l/-i）
注意：逻辑沙箱非 OS 级隔离（未用 bwrap/Seatbelt），写操作拦截是启发式黑名单——文档如实说明。
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from app.config import settings
from langchain_core.tools import tool

_MODES = ("read-only", "workspace-write", "full-access")

# 默认沙箱模式：settings.global["shell_default_mode"] 覆盖（hook 监听注入），否则 config 默认
_DEFAULT_MODE = settings.shell_default_mode


def set_default_mode(mode: str) -> None:
    """运行时更新默认沙箱模式（service-settings 事件注入）。"""
    global _DEFAULT_MODE
    if mode in _MODES:
        _DEFAULT_MODE = mode


def _effective_mode(mode: str | None) -> str:
    """工具显式 mode 优先；空/None 用运行时默认。"""
    return mode if mode in _MODES else _DEFAULT_MODE


# 只读模式拦截的写命令（词边界匹配，启发式黑名单）
_WRITE_CMDS = re.compile(
    r"""(?<![\w\-=])
    (?:rm|rmdir|mv|cp|touch|mkdir|ln|chmod|chown|dd|tee|truncate|mkfs|mkfs\.\w+|
       mount|umount|fdisk|kill|pkill|killall|reboot|shutdown|poweroff|useradd|usermod|passwd|
       git\s+push|git\s+commit|git\s+reset|git\s+checkout|git\s+clean|git\s+merge|git\s+rebase|
       curl|wget|scp|rsync|pip\s+install|pip3\s+install|npm\s+(install|i|init|run)|brew\s+install|apt\s+install|yum\s+install)
    (?![-\w])
    """,
    re.I | re.X,
)
# 重定向符（read-only 拦截）
_REDIRECT_RE = re.compile(r"(?:^|\s)[12]?&?>+")
# 逃逸工作区的写：绝对路径写目标 / 包含 .. 的路径（workspace-write 拦截）
_ABS_PATH_WRITE_RE = re.compile(r"(?:^|\s)[12]?&?>+\s*/(?!dev/null\b)", re.M)
_TRAVERSAL_RE = re.compile(r"(?:^|\s)[12]?&?>+\s*[^\"']*\.\.[/\\]")
# 敏感环境变量名（shell 子进程一律剥离，防模型读取密钥）
_SENSITIVE_ENV_KEYS = {
    "LLM_API_KEY",
    "DEEPSEEK_API_KEY",
    "ARK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "GITHUB_TOKEN",
    "NPM_TOKEN",
    "JWT_SECRET",
    "PGPASSWORD",
    "DATABASE_URL",
}
# 子进程环境白名单（只继承这些，其余丢弃）
_ENV_ALLOW = {
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LC_MESSAGES",
    "TERM",
    "TZ",
    "PWD",
    "SHELL",
    "USER",
    "LOGNAME",
    "SSH_AUTH_SOCK",
    "EDITOR",
    "PYTHONIOENCODING",
    "VIRTUAL_ENV",
}


def _workspace() -> Path:
    return settings.workspace_path


def _safe_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOW and k not in _SENSITIVE_ENV_KEYS}
    env.setdefault("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
    env.setdefault("LANG", "C.UTF-8")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _resolve_cwd(cwd: str) -> Path:
    """把相对/绝对 cwd 解析到工作区内；工作区外路径拒绝。"""
    ws = _workspace().resolve()
    p = Path(cwd).expanduser()
    p = p if p.is_absolute() else ws / p
    p = p.resolve()
    if p != ws and ws not in p.parents:
        raise ValueError(f"cwd 必须在工作区内（{ws}），收到：{cwd}")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _guard(cmd: str, mode: str) -> str | None:
    """沙箱检查，返回错误说明或 None（放行）。"""
    if mode == "read-only":
        if _REDIRECT_RE.search(cmd):
            return "read-only 模式禁止重定向写文件（> / >>），请用 workspace-write 模式"
        if _WRITE_CMDS.search(cmd):
            m = _WRITE_CMDS.search(cmd)
            return f"read-only 模式禁止写命令：{m.group(0).strip()}"
    elif mode == "workspace-write":
        if _ABS_PATH_WRITE_RE.search(cmd):
            return "workspace-write 模式禁止向绝对路径写文件（系统路径），请使用工作区内相对路径或 bash_full"
        if _TRAVERSAL_RE.search(cmd):
            return "workspace-write 模式禁止重定向到工作区外路径（.. 穿越）"
    return None


def _run(cmd: str, cwd: str, mode: str) -> str:
    if mode not in _MODES:
        return f"未知沙箱模式 {mode}，可选：{', '.join(_MODES)}"
    err = _guard(cmd, mode)
    if err:
        return f"⛔ 沙箱拦截：{err}"
    try:
        cwd_p = _resolve_cwd(cwd)
    except ValueError as e:
        return f"⛔ {e}"
    try:
        proc = subprocess.run(
            ["/bin/bash", "-c", cmd],
            cwd=str(cwd_p),
            env=_safe_env(),
            capture_output=True,
            text=True,
            timeout=settings.shell_timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return f"⏱️ 命令超时（>{settings.shell_timeout}s），已终止"
    except OSError as e:
        return f"执行失败：{e.__class__.__name__}: {e}"

    out = (proc.stdout or "").strip()
    err_txt = (proc.stderr or "").strip()
    limit = settings.shell_max_output
    if len(out) > limit:
        out = out[:limit] + f"\n…（stdout 截断，共 {len(out)} 字符）"
    if len(err_txt) > limit:
        err_txt = err_txt[:limit] + f"\n…（stderr 截断，共 {len(err_txt)} 字符）"
    parts = []
    if out:
        parts.append(out)
    if err_txt:
        parts.append(f"[stderr]\n{err_txt}")
    if not parts:
        parts.append("（无输出）")
    parts.append(f"\n[退出码 {proc.returncode}]")
    return "\n".join(parts)


@tool
def bash(command: str, cwd: str = ".", mode: str | None = None) -> str:
    """在受限 shell 中执行一条 bash 命令并返回 stdout/stderr/退出码。

    - command: 要执行的命令（可用 && 串联、管道等）
    - cwd: 工作目录，相对工作区（backend/data/workspace）解析；默认工作区根
    - mode: 沙箱模式。read-only=只读查询（禁止写命令/重定向）；workspace-write=允许在工作区内写（默认）；
      系统级/工作区外操作请改用 bash_full（会请求用户批准）。
      未指定时使用「设置 → 行为 → Shell 沙箱模式」的默认值。
    """
    return _run(command, cwd, _effective_mode(mode))


@tool
def bash_full(command: str, cwd: str = ".") -> str:
    """以 full-access 模式执行任意 bash 命令（不受沙箱限制，⚠️ 高风险，执行前需用户批准）。

    仅用于模型确认需要系统级操作时：安装全局依赖、操作工作区外文件等。
    """
    return _run(command, cwd, "full-access")


TOOLS = [bash, bash_full]
