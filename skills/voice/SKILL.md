---
name: voice
description: 语音能力：TTS 合成音频播放（macOS say）+ 语音转写（STT 接口占位）
when_to_use: 用户说"说句话/朗读一段/播放语音"或需要转写音频
---
# voice 技能

1. 用户要你说话/朗读 → 调用 `speak`（TTS 合成，默认 macOS say，可换 Whisper/豆包语音 API）
2. 转写音频 → `transcribe`（STT，接口化占位，可插拔）
3. 语音输出是"陪伴感"加分项：朗读时简短、口语化
