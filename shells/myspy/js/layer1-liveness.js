// layer1-liveness.js - 壳侧每帧持续参数控制（第 1 层：让模型"活"起来）
//
// 这一层不依赖 LLM，壳自己跑：
//   1. 视线追踪：头+瞳孔跟鼠标
//   2. 自动眨眼：随机间隔闭眼
//   3. idle 微抖：头/身体极轻微晃动（不是 motion，是参数）
//
// 关键技巧（dsh-live2d-pet）：每帧在 beforeUpdate 写入参数，
// 表情快照（exp3.json）和 motion 不会覆盖——因为下一帧又写回去了。

class Layer1Liveness {
  constructor() {
    this.model = null
    this.app = null
    this.enabled = true

    // 鼠标位置（-1 ~ 1）
    this.mouseX = 0
    this.mouseY = 0
    // 当前平滑值（用于 lerp，避免生硬跳转）
    this.smoothAngleX = 0
    this.smoothAngleY = 0
    this.smoothEyeX = 0
    this.smoothEyeY = 0

    // 眨眼状态
    this.blinkTimer = null
    this.isBlinking = false
    this.blinkProgress = 0

    // idle 微抖相位
    this.idleTime = 0

    // 嘴型状态（每帧持续写，防止 motion 曲线覆盖）
    this.mouthOpenY = 0  // 0=闭嘴, 0.4=张嘴
  }

  init(model, app) {
    this.model = model
    this.app = app
    if (!model || !app) return

    // 鼠标追踪
    document.addEventListener('mousemove', (e) => {
      // 归一化到 -1 ~ 1（以窗口中心为原点）
      this.mouseX = (e.clientX / window.innerWidth) * 2 - 1
      this.mouseY = (e.clientY / window.innerHeight) * 2 - 1
    })

    // 每帧 ticker：写视线参数
    app.ticker.add(() => this._tick())

    // 启动自动眨眼循环
    this._scheduleBlink()

    console.log('[Layer1] 活感层已启动：视线追踪 + 自动眨眼 + idle 微抖')
  }

  _coreModel() {
    if (!this.model) return null
    const inner = this.model.innerModel || this.model
    if (!inner.internalModel || !inner.internalModel.coreModel) return null
    return inner.internalModel.coreModel
  }

  _tick() {
    const cm = this._coreModel()
    if (!cm) return

    this.idleTime += 1 / 60 // 假设 60fps

    // === 1. 视线追踪（lerp 平滑跟随）===
    // 头转 ±30°，瞳孔跟 ±1
    const targetAngleX = this.mouseX * 30
    const targetAngleY = -this.mouseY * 20 // 屏幕 y 向下为正，反过来
    const targetEyeX = this.mouseX
    const targetEyeY = -this.mouseY

    // idle 微抖：加一个极轻微的正弦波动（±2°）
    const idleSwayX = Math.sin(this.idleTime * 0.8) * 2
    const idleSwayY = Math.sin(this.idleTime * 0.5) * 1.5

    this.smoothAngleX += (targetAngleX + idleSwayX - this.smoothAngleX) * 0.08
    this.smoothAngleY += (targetAngleY + idleSwayY - this.smoothAngleY) * 0.08
    this.smoothEyeX += (targetEyeX - this.smoothEyeX) * 0.12
    this.smoothEyeY += (targetEyeY - this.smoothEyeY) * 0.12

    this._trySet(cm, 'ParamAngleX', this.smoothAngleX)
    this._trySet(cm, 'ParamAngleY', this.smoothAngleY)
    this._trySet(cm, 'ParamEyeBallX', this.smoothEyeX)
    this._trySet(cm, 'ParamEyeBallY', this.smoothEyeY)

    // 嘴型：每帧持续写，防止 motion 曲线覆盖
    this._trySet(cm, 'ParamMouthOpenY', this.mouthOpenY)

    // === 2. 眨眼（覆盖在视线之上）===
    if (this.isBlinking) {
      this._updateBlink(cm)
    }
  }

  _trySet(cm, id, value) {
    try { cm.setParameterValueById(id, value) } catch (e) { /* 参数不存在就跳过 */ }
  }

  // === 自动眨眼 ===
  _scheduleBlink() {
    // 随机 2~6 秒眨一次
    const delay = 2000 + Math.random() * 4000
    this.blinkTimer = setTimeout(() => {
      this._startBlink()
      this._scheduleBlink()
    }, delay)
  }

  _startBlink() {
    this.isBlinking = true
    this.blinkProgress = 0
  }

  _updateBlink(cm) {
    // 一次眨眼约 150ms：闭 50ms + 开 100ms
    this.blinkProgress += 1 / 60
    const t = this.blinkProgress / 0.15 // 0~1

    let eyeOpen
    if (t < 0.33) {
      // 闭合阶段：1 → 0
      eyeOpen = 1 - t / 0.33
    } else if (t < 0.6) {
      // 闭眼停留
      eyeOpen = 0
    } else {
      // 睁开阶段：0 → 1
      eyeOpen = (t - 0.6) / 0.4
    }

    eyeOpen = Math.max(0, Math.min(1, eyeOpen))
    // 0=睁开, 1=闭眼（Live2D ParamEyeLOpen 是 0=睁开 1=闭眼）
    this._trySet(cm, 'ParamEyeLOpen', 1 - eyeOpen)
    this._trySet(cm, 'ParamEyeROpen', 1 - eyeOpen)

    if (t >= 1) {
      this.isBlinking = false
      this._trySet(cm, 'ParamEyeLOpen', 0)
      this._trySet(cm, 'ParamEyeROpen', 0)
    }
  }

  destroy() {
    if (this.blinkTimer) clearTimeout(this.blinkTimer)
  }
}

module.exports = { Layer1Liveness }
