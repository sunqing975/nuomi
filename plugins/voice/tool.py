"""voice 能力型插件：语音。

- speak(text)：macOS `say` 合成语音 → ffmpeg 转 mp3 → 返回音频文件绝对路径。
  非 macOS 或无 ffmpeg 时返回明确错误（插件自检，不阻断对话）。
- transcribe(audio_path)：STT 接口化占位——校验输入、说明接入方式，
  体现"换实现 = 换这个插件"的 adapter 形态（可换成 Whisper / 豆包语音 API）。
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from langchain_core.tools import tool

_AUDIO_DIR = Path(__file__).resolve().parents[2] / "backend" / "data" / "audio"


@tool
def speak(text: str, voice: str = "Ting-Ting") -> str:
    """用 macOS 语音朗读文本并生成音频文件（mp3）。voice 可选：Ting-Ting（中文女声）/ Alex / Samantha。"""
    if not text.strip():
        return "内容为空，没有可朗读的文本。"
    _AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    aiff = _AUDIO_DIR / f"speak_{int(time.time() * 1000)}.aiff"
    mp3 = aiff.with_suffix(".mp3")
    try:
        r = subprocess.run(
            ["say", "-v", voice, "-o", str(aiff), text],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            return f"语音合成失败（say 返回 {r.returncode}）：{r.stderr.strip() or '未知错误'}"
        r2 = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), str(mp3)],
            capture_output=True, text=True, timeout=60,
        )
        aiff.unlink(missing_ok=True)
        if r2.returncode != 0 or not mp3.exists():
            return "音频转码失败（需要 ffmpeg，可用 brew install ffmpeg 安装）"
        return f"已生成语音：{mp3}"
    except FileNotFoundError:
        return "当前环境没有 say/ffmpeg（macOS 专用工具），请换到 macOS 或替换 TTS 实现。"
    except subprocess.TimeoutExpired:
        return "语音合成超时（文本过长？）"


@tool
def transcribe(audio_path: str) -> str:
    """转写音频为文字（STT 接口化占位：当前校验输入并说明接入方式，可替换为 Whisper / 豆包语音 API）。"""
    p = Path(audio_path)
    if not p.exists():
        return f"音频文件不存在：{audio_path}"
    # 接口化：真实接入时在此处调用 STT 服务（adapter 形态），返回转写文本
    return (
        "STT 接口已就绪（输入校验通过）。当前未接入具体转写引擎，"
        "可在本插件的 transcribe 实现中替换为 Whisper / 豆包语音 API。"
    )


TOOLS = [speak, transcribe]
