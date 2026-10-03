"""voice 能力型插件：语音。

- speak(text)：macOS `say` 合成语音 → ffmpeg 转 mp3 → 返回音频文件绝对路径。
  非 macOS 或无 ffmpeg 时返回明确错误（插件自检，不阻断对话）。
- transcribe(audio_path)：本地 STT——faster-whisper（CTranslate2）离线转写，
  免费、数据不出本机；模型首次调用时下载并缓存（NUOMI_HOME/hf-cache），
  之后走缓存。模型可用环境变量 NUOMI_STT_MODEL 覆盖（默认 small，中文够用；
  base/tiny 更快更小，large-v3 更准更慢）。
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from langchain_core.tools import tool

# 模型缓存锚定 NUOMI_HOME（单一数据根原则）；下载走 HF 镜像（直连 huggingface 实测超时）
_HF_ENDPOINT = "https://hf-mirror.com"
_HF_HOME = (
    Path(os.environ.get("NUOMI_HOME", Path.home() / "Library/Application Support/Nuomi"))
    / "hf-cache"
)
_MODEL_NAME = os.environ.get("NUOMI_STT_MODEL", "small")

_AUDIO_DIR = Path(__file__).resolve().parents[2] / "backend" / "data" / "audio"

_model = None  # 模块级缓存：首次调用加载，之后复用（三级加载的"资源按需"）


def _get_model():
    """懒加载 faster-whisper 模型（int8 CPU，macOS 无 Metal 加速但足够实时）。"""
    global _model
    if _model is None:
        os.environ.setdefault("HF_ENDPOINT", _HF_ENDPOINT)
        os.environ.setdefault("HF_HOME", str(_HF_HOME))
        from faster_whisper import WhisperModel

        _model = WhisperModel(_MODEL_NAME, device="cpu", compute_type="int8")
    return _model


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
            capture_output=True,
            text=True,
            timeout=60,
        )
        if r.returncode != 0:
            return f"语音合成失败（say 返回 {r.returncode}）：{r.stderr.strip() or '未知错误'}"
        r2 = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(aiff), str(mp3)],
            capture_output=True,
            text=True,
            timeout=60,
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
    """转写音频为文字（本地 STT：faster-whisper 离线推理，免费、数据不出本机）。支持 mp3/wav/m4a 等常见格式。"""
    p = Path(audio_path)
    if not p.exists():
        return f"音频文件不存在：{audio_path}"
    if p.stat().st_size == 0:
        return "音频文件为空（0 字节）。"
    try:
        model = _get_model()
        segments, info = model.transcribe(
            str(p),
            vad_filter=True,  # 过滤静音，中文口语更稳
            beam_size=5,
            language="zh",  # 糯米主场景中文；多语言可去掉该参数走自动检测
        )
        text = "".join(seg.text for seg in segments).strip()
        if not text:
            return "未识别到语音内容（音频可能无人声或过短）。"
        return f"转写结果：{text}（语言 {info.language}，置信度 {info.language_probability:.2f}）"
    except Exception as e:  # noqa: BLE001 —— 工具内兜底，不阻断对话
        return f"转写失败：{type(e).__name__}: {e}"


TOOLS = [speak, transcribe]
