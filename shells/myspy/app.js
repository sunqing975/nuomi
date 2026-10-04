// app.js - 渲染进程入口
const fs = require('fs')
const path = require('path')
const { ipcRenderer } = require('electron')
const { TTSClient } = require('./js/tts-client')
const { ModelInteractionController } = require('./js/model/model-interaction.js')
const { TTSStreamProcessor } = require('./js/tts-stream-processor')
const { EmotionExpressionMapper } = require('./js/emotion-expression-mapper')
const { VRMModelSetup } = require('./js/model/vrm-model-setup.js')
const { VRMInteractionController } = require('./js/model/vrm-model-interaction.js')
const { UnifiedModelAdapter } = require('./js/model/unified-model-adapter.js')
const { UnifiedInteractionController } = require('./js/model/unified-interaction-controller.js')
const { appState } = require('./js/core/app-state.js')
const { ModelScanner } = require('./js/model/model-scanner.js')
const { logToTerminal } = require('./js/api-utils')

// 情绪表情映射器
const emotionMapper = new EmotionExpressionMapper()

// 日志记录
function log(msg, level = 'info') {
    console.log(msg)
    ipcRenderer.send('log-message', { level, message: msg, timestamp: Date.now() })
}

function logTool(msg, level = 'info') {
    console.log('[TOOL] ' + msg)
    ipcRenderer.send('log-message', { level, message: msg, timestamp: Date.now(), isTool: true })
}

// 加载配置
let config
try {
    config = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'))
} catch (e) {
    console.error('配置失败:', e)
}

// 初始化TTS
const tts = new TTSClient(config)

// 初始化流式 TTS 处理器（延迟初始化，需要 modelCtrl）
let ttsStreamProcessor = null

// 对话历史（发送给后端 LLM 的消息队列）
const messages = [
    { role: 'system', content: config?.llm?.system_prompt || '你是一个可爱的AI桌宠助手。' }
]

// === 情绪→表情自动映射（5秒后自动恢复）===
let _currentEmotionExpressions = []  // 当前激活的表情参数列表
let _emotionTimer = null              // 自动恢复定时器

const EMOTION_EXPRESSION_MAP = {
    '开心': ['lianhong'],           // 脸红
    '生气': ['shengqi', 'jiao'],    // 生气+角
    '难过': ['yanlei', 'buan'],     // 眼泪+不安
    '惊讶': ['wuyu'],               // 无语
    '害羞': ['hailian', 'lianhong'], // 害羞+脸红
    '俏皮': ['shanzi']              // 扇子
}

function _applyEmotionExpression(emotion) {
    if (!model) return
    const inner = model.innerModel || model
    if (!inner.internalModel || !inner.internalModel.coreModel) return
    const cm = inner.internalModel.coreModel
    const fs = require('fs')

    // 清除旧定时器
    if (_emotionTimer) {
        clearTimeout(_emotionTimer)
        _emotionTimer = null
    }

    // 关闭上一个情绪的表情
    for (const p of _currentEmotionExpressions) {
        try { cm.setParameterValueById(p.Id, 0) } catch (e) {}
    }
    _currentEmotionExpressions = []

    // 开启新情绪的表情
    const exprNames = EMOTION_EXPRESSION_MAP[emotion]
    if (!exprNames) return

    const modelPath = config?.ui?.model_path || ''
    const charMatch = modelPath.match(/2D\/([^\/]+)\//)
    const charName = charMatch ? charMatch[1] : ''
    if (!charName) return

    for (const exprName of exprNames) {
        const exprPath = path.join(__dirname, '2D', charName, exprName + '.exp3.json')
        if (!fs.existsSync(exprPath)) continue
        try {
            const exprData = JSON.parse(fs.readFileSync(exprPath, 'utf8'))
            for (const p of (exprData.Parameters || [])) {
                try { cm.setParameterValueById(p.Id, p.Value) } catch (e) {}
                _currentEmotionExpressions.push({ id: p.id, value: p.Value })
            }
        } catch (e) {}
    }

    // 5秒后自动恢复
    _emotionTimer = setTimeout(() => {
        for (const p of _currentEmotionExpressions) {
            try { cm.setParameterValueById(p.id, 0) } catch (e) {}
        }
        _currentEmotionExpressions = []
        _emotionTimer = null
    }, 10000)
}

// ===== 持久化对话历史（已废除：记忆由后端 octop-harness 管理）=====

// 设置全局对话环境（供桌宠表现层使用；对话已收归控制台，sendToLLM 不再可用）
const voiceChat = {
    messages: messages,
    API_URL: config?.llm?.api_url || '',
    API_KEY: config?.llm?.api_key || '',
    MODEL: config?.llm?.model || '',
    ttsProcessor: tts,
    sendToLLM: async () => { /* 对话仅控制台，桌宠不再发消息 */ },
    setModel: (m) => { global.currentModel = m },
    setEmotionMapper: null
}

// 上下文裁剪
function trimMessages() {
    if (!config?.context?.enable_limit) return

    const maxMessages = config.context.max_messages || 18
    const systemMessages = messages.filter(msg => msg.role === 'system')
    const nonSystemMessages = messages.filter(msg => msg.role !== 'system')

    if (nonSystemMessages.length > maxMessages) {
        const recentMessages = nonSystemMessages.slice(-maxMessages)
        messages.length = 0
        messages.push(...systemMessages, ...recentMessages)
        log('上下文裁剪: 保留 ' + recentMessages.length + ' 条非系统消息')
    }
}



global.modelController = null

// DOM

let model = null
let modelCtrl = null

// ===== 会话管理（一个 thread_id 逻辑）：config.json 的 nuomi.thread_id 为权威 =====
// 桌宠与控制台共用同一「当前会话」：控制台切会话（后端写 config.json）后，
// 壳在每次对话前重读 config 自动跟随。
const configPath = path.join(__dirname, 'config.json')

function saveConfig() {
    try {
        // 壳只拥有 nuomi.*（会话绑定）；ui.*（模型等）由后端/控制台管理。
        // 必须以磁盘最新为底写回，否则壳内存里启动时的旧 ui.model 会覆盖后端刚切换的模型。
        let disk = {}
        try { disk = JSON.parse(fs.readFileSync(configPath, 'utf8')) } catch (e) { disk = {} }
        const merged = JSON.parse(JSON.stringify(disk))
        if (config.nuomi) merged.nuomi = config.nuomi
        fs.writeFileSync(configPath, JSON.stringify(merged, null, 2), 'utf8')
        config = merged // 同步内存，后续读取即为磁盘最新
    } catch (e) {
        log('配置写入失败: ' + e.message, 'warn')
    }
}


// 图片模型交互（overlay 只管穿透，交互走 document/overlay 级别）
const imgOverlay = document.createElement('div')
imgOverlay.id = 'image-overlay'
imgOverlay.style.cssText = 'position:fixed;z-index:99997;pointer-events:auto;display:none;'
document.body.appendChild(imgOverlay)
let imgDragging = false, imgDragOff = { x: 0, y: 0 }, imgModelActive = false
let gifRotateTimer = null, gifRotatePath = null, gifCurrentScale = 1

// 创建 GIF <img> 元素，自动缩放并更新 overlay
function createGifImage(src) {
    const el = document.createElement('img')
    el.id = 'gif-model'
    el.style.cssText = 'position:fixed;z-index:1;pointer-events:none;transform:translate(-50%,-50%);'
    el.style.left = actualWidth + 'px'
    el.style.top = (actualHeight * 0.85) + 'px'
    document.body.appendChild(el)
    el.onload = () => {
        const nw = el.naturalWidth, nh = el.naturalHeight
        global._imgNatW = nw; global._imgNatH = nh
        const sc = Math.min((actualWidth * 0.8) / nw, (actualHeight * 1.2) / nh, 1)
        el.style.width = (nw * sc) + 'px'; el.style.height = (nh * sc) + 'px'
        const sw = nw * sc, sh = nh * sc
        imgOverlay.style.left = (actualWidth - sw / 2) + 'px'
        imgOverlay.style.top = (actualHeight * 0.85 - sh / 2) + 'px'
        imgOverlay.style.width = sw + 'px'; imgOverlay.style.height = sh + 'px'
        imgOverlay.style.display = 'block'
        imgModelActive = true
    }
    el.src = src
    return el
}

function makeGifModel(el) {
    return {
        innerModel: el, _isGif: true, visible: true,
        x: actualWidth, y: actualHeight * 0.85,
        motion: () => {}, expression: () => {}, setEmotionMapper: () => {}
    }
}

// GIF 轮播：随机切换一张 GIF，更新 overlay 尺寸
function rotateGifOnce() {
    if (!gifRotatePath || !global.currentModel || !global.currentModel._isGif) return
    const next = ModelScanner.getRandomGif(gifRotatePath)
    if (!next) return
    const el = global.currentModel.innerModel
    const nw = global._imgNatW || 300, nh = global._imgNatH || 300
    const baseW = nw * Math.min((actualWidth * 0.8) / nw, (actualHeight * 1.2) / nh, 1)
    const finalW = baseW * gifCurrentScale
    const finalH = finalW * (nh / nw)
    el.style.width = finalW + 'px'
    el.style.height = finalH + 'px'
    const cx = parseFloat(el.style.left) || actualWidth
    const cy = parseFloat(el.style.top) || (actualHeight * 0.85)
    imgOverlay.style.left = (cx - finalW / 2) + 'px'
    imgOverlay.style.top = (cy - finalH / 2) + 'px'
    imgOverlay.style.width = finalW + 'px'
    imgOverlay.style.height = finalH + 'px'
    el.onload = () => {
        const rnw = el.naturalWidth, rnh = el.naturalHeight
        global._imgNatW = rnw; global._imgNatH = rnh
        const rb = rnw * Math.min((actualWidth * 0.8) / rnw, (actualHeight * 1.2) / rnh, 1)
        const rw = rb * gifCurrentScale, rh = rw * (rnh / rnw)
        el.style.width = rw + 'px'; el.style.height = rh + 'px'
        const cx2 = parseFloat(el.style.left) || actualWidth
        const cy2 = parseFloat(el.style.top) || (actualHeight * 0.85)
        imgOverlay.style.left = (cx2 - rw / 2) + 'px'
        imgOverlay.style.top = (cy2 - rh / 2) + 'px'
        imgOverlay.style.width = rw + 'px'; imgOverlay.style.height = rh + 'px'
    }
    el.src = next
}
function startGifRotation() {
    clearInterval(gifRotateTimer)
    gifRotateTimer = setInterval(rotateGifOnce, 5000)
}

function showImgOverlay(sprite, natW, natH) {
    const w = natW || sprite.width
    const h = natH || sprite.height
    const sw = w * sprite.scale.x / 2
    const sh = h * sprite.scale.y / 2
    const cssX = sprite.x / 2, cssY = sprite.y / 2
    imgOverlay.style.left = (cssX - sw / 2) + 'px'
    imgOverlay.style.top = (cssY - sh / 2) + 'px'
    imgOverlay.style.width = sw + 'px'
    imgOverlay.style.height = sh + 'px'
    imgOverlay.style.display = 'block'
    imgModelActive = true
    logToTerminal('info', `img overlay: ${sw.toFixed(0)}x${sh.toFixed(0)} at ${cssX.toFixed(0)},${cssY.toFixed(0)}`)
}

// 穿透控制：mouseenter 启用交互，mouseleave 恢复穿透
imgOverlay.addEventListener('mouseenter', () => {
    ipcRenderer.send('set-ignore-mouse-events', { ignore: false, options: { forward: false } })
})
imgOverlay.addEventListener('mouseleave', () => {
    if (!imgDragging) {
        ipcRenderer.send('set-ignore-mouse-events', { ignore: true, options: { forward: true } })
    }
})

// 拖拽起点（overlay mousedown）
imgOverlay.addEventListener('mousedown', (e) => {
    imgDragging = true
    const m = global.currentModel
    if (m && m.innerModel) {
        if (m._isGif) {
            imgDragOff.x = e.clientX
            imgDragOff.y = e.clientY
        } else {
            imgDragOff.x = e.clientX - m.innerModel.x / 2
            imgDragOff.y = e.clientY - m.innerModel.y / 2
        }
    }
    e.preventDefault()
})

// 拖拽移动（document mousemove，不依赖 overlay）
document.addEventListener('mousemove', (e) => {
    if (!imgDragging) return
    const m = global.currentModel
    if (!m || !m.innerModel) return
    if (m._isGif) {
        m.innerModel.style.left = e.clientX + 'px'
        m.innerModel.style.top = e.clientY + 'px'
        const dw = parseFloat(m.innerModel.style.width) || 100
        const dh = parseFloat(m.innerModel.style.height) || 100
        imgOverlay.style.left = (e.clientX - dw / 2) + 'px'
        imgOverlay.style.top = (e.clientY - dh / 2) + 'px'
    } else {
        m.innerModel.x = (e.clientX - imgDragOff.x) * 2
        m.innerModel.y = (e.clientY - imgDragOff.y) * 2
        const natW = global._imgNatW || 100, natH = global._imgNatH || 100
        const sw = natW * m.innerModel.scale.x / 2
        const sh = natH * m.innerModel.scale.y / 2
        imgOverlay.style.left = (e.clientX - sw / 2) + 'px'
        imgOverlay.style.top = (e.clientY - sh / 2) + 'px'
    }
})

// 拖拽结束（document mouseup）
document.addEventListener('mouseup', (e) => {
    if (!imgDragging) return
    imgDragging = false
    const rect = imgOverlay.getBoundingClientRect()
    if (e.clientX < rect.left || e.clientX > rect.right
        || e.clientY < rect.top || e.clientY > rect.bottom) {
        ipcRenderer.send('set-ignore-mouse-events', { ignore: true, options: { forward: true } })
    }
})

// 滚轮缩放（document 级别，仅在 overlay 区域内生效）
document.addEventListener('wheel', (e) => {
    if (!imgModelActive || !global.currentModel || !global.currentModel.innerModel) return
    const rect = imgOverlay.getBoundingClientRect()
    if (e.clientX < rect.left || e.clientX > rect.right
        || e.clientY < rect.top || e.clientY > rect.bottom) return
    e.preventDefault()
    const m = global.currentModel
    const natW = global._imgNatW || 100, natH = global._imgNatH || 100
    const d = e.deltaY > 0 ? 0.9 : 1.1
    if (m._isGif) {
        gifCurrentScale *= d
        gifCurrentScale = Math.max(0.2, Math.min(3, gifCurrentScale))
        const el = m.innerModel
        const baseW = natW * Math.min((actualWidth * 0.8) / natW, (actualHeight * 1.2) / natH, 1)
        const nw = baseW * gifCurrentScale
        const nh = nw * (natH / natW)
        el.style.width = nw + 'px'
        el.style.height = nh + 'px'
        const centerX = parseFloat(el.style.left) || actualWidth
        const centerY = parseFloat(el.style.top) || (actualHeight * 0.85)
        imgOverlay.style.left = (centerX - nw / 2) + 'px'
        imgOverlay.style.top = (centerY - nh / 2) + 'px'
        imgOverlay.style.width = nw + 'px'
        imgOverlay.style.height = nh + 'px'
    } else {
        const sprite = m.innerModel
        const ns = Math.max(0.1, Math.min(5, sprite.scale.x * d))
        sprite.scale.set(ns)
        const sw = natW * sprite.scale.x / 2
        const sh = natH * sprite.scale.y / 2
        const cssX = sprite.x / 2, cssY = sprite.y / 2
        imgOverlay.style.left = (cssX - sw / 2) + 'px'
        imgOverlay.style.top = (cssY - sh / 2) + 'px'
        imgOverlay.style.width = sw + 'px'
        imgOverlay.style.height = sh + 'px'
    }
}, { passive: false })

// 鼠标是否在交互区域（模型或聊天框）
let mouseOverInteractive = false



async function main() {
    try {
        const bounds = await ipcRenderer.invoke('get-window-bounds')
        const actualWidth = bounds.width
        const actualHeight = bounds.height

        // 保存缩放因子到全局
        window.actualWidth = actualWidth
        window.actualHeight = actualHeight
        window.canvasScaleFactor = 2

        let app = null

        // ===== 自动检测模型 =====
        // 1. 优先使用配置的模型路径
        // 2. 根据文件扩展名自动检测类型（.vrm → VRM, .model3.json → Live2D）
        // 3. 如果没配置，扫描 2D/ 和 3D/ 目录自动选择
        let modelPath = config?.ui?.model_path || ''
        let modelType = config?.ui?.model_type || ''

        // 如果没配置模型路径，扫描目录自动选择
        if (!modelPath) {
            const scanned = ModelScanner.getDefaultModel(__dirname)
            if (scanned) {
                modelPath = scanned.path
                modelType = scanned.type
                logToTerminal('info', `自动检测到模型: ${scanned.name} (${scanned.type})`)
            }
        }

        // 根据文件扩展名自动检测类型（覆盖配置）
        if (modelPath) {
            const detectedType = ModelScanner.detectType(modelPath)
            if (detectedType) {
                modelType = detectedType
            }
        }

        // 兜底默认值
        if (!modelType) modelType = 'live2d'
        if (!modelPath) modelPath = '2D/feiniu/hiyori_pro_t11.model3.json'

        logToTerminal('info', `模型类型: ${modelType}, 路径: ${modelPath}`)

        if (modelType === 'vrm') {
            // VRM 3D 模型
            logToTerminal('info', '正在加载VRM 3D模型...')
            try {
                const result = await VRMModelSetup.initialize(
                    modelCtrl, config,
                    config?.tts?.enabled !== false,
                    config?.asr?.enabled !== false,
                    tts, global.voiceChat
                )

                // 用统一适配器包装 VRM 模型
                model = new UnifiedModelAdapter(result.model, result.app, 'vrm', config)
                global.currentModel = model
                global.pixiApp = result.app

                // VRM模式：替换modelController并更新TTS唇形回调
                if (result.vrmController) {
                    modelCtrl = result.vrmController
                }

                logToTerminal('info', 'VRM 模型加载完成')
            } catch (vrmErr) {
                logToTerminal('error', 'VRM 加载失败: ' + vrmErr.message)
                console.error('VRM 加载失败:', vrmErr)
            }
        } else if (modelType === 'image') {
            // 图片/GIF 模型
            logToTerminal('info', '正在加载图片模型...')
            app = new PIXI.Application({
                view: document.getElementById('canvas'),
                autoStart: true,
                transparent: true,
                width: actualWidth * 2,
                height: actualHeight * 2
            })
            app.view.style.width = `${actualWidth}px`
            app.view.style.height = `${actualHeight}px`

            // GIF 文件夹：随机选一个
            let actualModelPath = modelPath
            let isGifFolder = false
            try {
                if (fs.statSync(modelPath).isDirectory()) {
                    isGifFolder = true
                    gifRotatePath = modelPath
                    gifCurrentScale = 1
                    const randomGif = ModelScanner.getRandomGif(modelPath)
                    if (randomGif) {
                        actualModelPath = randomGif
                        logToTerminal('info', '随机选择GIF: ' + path.basename(randomGif))
                    }
                }
            } catch (e) {}

            const isGif = actualModelPath.toLowerCase().endsWith('.gif')

            if (isGif) {
                const gifEl = createGifImage(actualModelPath)
                if (isGifFolder) startGifRotation()
                model = makeGifModel(gifEl)
            } else {
                const sprite = PIXI.Sprite.from(modelPath)
                const maxH = actualHeight * 1.2
                const maxW = actualWidth * 0.8
                const scaleX = maxW / sprite.width
                const scaleY = maxH / sprite.height
                const scale = Math.min(scaleX, scaleY, 1)
                sprite.scale.set(scale)
                sprite.anchor.set(0.5)
                sprite.x = actualWidth
                sprite.y = actualHeight * 0.85
                app.stage.addChild(sprite)
                showImgOverlay(sprite, actualWidth, actualHeight)
                const img = new Image()
                img.onload = () => {
                    global._imgNatW = img.naturalWidth
                    global._imgNatH = img.naturalHeight
                    showImgOverlay(sprite, img.naturalWidth, img.naturalHeight)
                }
                img.src = modelPath
                model = {
                    innerModel: sprite, visible: true,
                    x: sprite.x, y: sprite.y, scale: sprite.scale,
                    width: sprite.width, height: sprite.height,
                    motion: () => {}, expression: () => {},
                    setEmotionMapper: () => {},
                    get的表情: () => null, set表情: () => {}
                }
            }
            global.currentModel = model
            global.pixiApp = app

            logToTerminal('info', '图片模型加载完成: ' + modelPath)
        } else {
            // Live2D 模型
            // 2x canvas（跟原项目一致，支持高分辨率）
            app = new PIXI.Application({
                view: document.getElementById('canvas'),
                autoStart: true,
                transparent: true,
                width: actualWidth * 2,
                height: actualHeight * 2
            })
            app.view.style.width = `${actualWidth}px`
            app.view.style.height = `${actualHeight}px`

            const live2dModel = await PIXI.live2d.Live2DModel.from(modelPath)
            app.stage.addChild(live2dModel)

            // 用统一适配器包装 Live2D 模型
            model = new UnifiedModelAdapter(live2dModel, app, 'live2d', config)

            // 模型可见性
            model.visible = config?.ui?.show_model !== false

            console.log(`=== 模型调试 ===`)
            console.log(`模型尺寸: ${model.width}x${model.height}`)
            console.log(`模型缩放: ${model.scale.x}`)
            console.log(`Canvas尺寸: ${app.view.width}x${app.view.height}`)
            console.log(`窗口尺寸: ${actualWidth}x${actualHeight}`)
            console.log(`模型可见: ${model.visible}`)

            // 初始化统一交互控制器
            const unifiedCtrl = new UnifiedInteractionController()
            unifiedCtrl.init(model, config)
            unifiedCtrl.setupInitialModelProperties()

            // 初始化情绪表情映射器
            emotionMapper.init(model.innerModel)
            model.setEmotionMapper(emotionMapper)

            console.log(`模型位置: (${model.x}, ${model.y})`)
            console.log(`模型最终缩放: ${model.scale.x}`)

            // 嘴型控制器（包装 unifiedCtrl）
            modelCtrl = {
                setMouthOpenY: (v) => unifiedCtrl.setMouthOpenY(v)
            }
        }

        // 初始化流式 TTS 处理器（先销毁旧的）
        if (tts.enabled) {
            if (ttsStreamProcessor) ttsStreamProcessor.destroy()
            ttsStreamProcessor = new TTSStreamProcessor(config, tts, modelCtrl)
        }

        // 设置全局模型引用（供插件使用）
        global.modelController = modelCtrl
        global.currentModel = model

        // 监听模型切换
        ipcRenderer.on('switch-model', async (event, newPath) => {
            try {
                // 自动检测新模型类型
                const newType = ModelScanner.detectType(newPath) || config?.ui?.model_type || 'live2d'
                log('切换模型: ' + newPath + ' (类型: ' + newType + ')')

                if (newType === 'vrm') {
                    // VRM 模型切换需要重启
                    log('VRM 模型切换需要重启桌宠生效')
                } else if (newType === 'image') {
                    // GIF 文件夹：随机选一个
                    let actualNewPath = newPath
                    let switchIsGifFolder = false
                    try {
                        if (fs.statSync(newPath).isDirectory()) {
                            switchIsGifFolder = true
                            gifRotatePath = newPath
                            const randomGif = ModelScanner.getRandomGif(newPath)
                            if (randomGif) {
                                actualNewPath = randomGif
                                log('随机选择GIF: ' + path.basename(randomGif))
                            }
                        }
                    } catch (e) {}

                    // 图片模型切换
                    if (model && model.innerModel) {
                        app.stage.removeChild(model.innerModel)
                    }
                    // 移除旧 GIF 元素
                    const oldGif = document.getElementById('gif-model')
                    if (oldGif) oldGif.remove()

                    const switchIsGif = actualNewPath.toLowerCase().endsWith('.gif')
                    if (switchIsGif) {
                        const gifImg = createGifImage(actualNewPath)
                        model = makeGifModel(gifImg)
                        global.currentModel = model
                        if (switchIsGifFolder) startGifRotation()
                        log('GIF模型已切换: ' + path.basename(actualNewPath))
                        return
                    }
                    const sprite = PIXI.Sprite.from(actualNewPath)
                    const maxH = actualHeight * 1.2
                    const maxW = actualWidth * 0.8
                    const scX = maxW / sprite.width
                    const scY = maxH / sprite.height
                    const sc = Math.min(scX, scY, 1)
                    sprite.scale.set(sc)
                    sprite.anchor.set(0.5)
                    sprite.x = actualWidth
                    sprite.y = actualHeight * 0.85
                    app.stage.addChild(sprite)

                    // 显示 overlay
                    showImgOverlay(sprite, actualWidth, actualHeight)

                    const img2 = new Image()
                    img2.onload = () => {
                        global._imgNatW = img2.naturalWidth
                        global._imgNatH = img2.naturalHeight
                        showImgOverlay(sprite, img2.naturalWidth, img2.naturalHeight)
                    }
                    img2.src = newPath

                    model = {
                        innerModel: sprite, visible: true,
                        x: sprite.x, y: sprite.y, scale: sprite.scale,
                        width: sprite.width, height: sprite.height,
                        motion: () => {}, expression: () => {},
                        setEmotionMapper: () => {}
                    }
                    global.currentModel = model
                    log('图片模型已切换: ' + newPath)
                } else {
                    // Live2D 模型切换
                    clearInterval(gifRotateTimer)
                    gifRotatePath = null
                    imgOverlay.style.display = 'none'
                    imgModelActive = false
                    ipcRenderer.send('set-ignore-mouse-events', { ignore: true, options: { forward: true } })
                    if (model && model.innerModel) {
                        app.stage.removeChild(model.innerModel)
                    }
                    const live2dModel = await PIXI.live2d.Live2DModel.from(newPath)
                    app.stage.addChild(live2dModel)
                    model = new UnifiedModelAdapter(live2dModel, app, 'live2d', config)
                    model.visible = config?.ui?.show_model !== false
                    const unifiedCtrl = new UnifiedInteractionController()
                    unifiedCtrl.init(model, config)
                    unifiedCtrl.setupInitialModelProperties()
                    emotionMapper.init(model.innerModel)
                    model.setEmotionMapper(emotionMapper)
                    modelCtrl = { setMouthOpenY: (v) => unifiedCtrl.setMouthOpenY(v) }
                    global.currentModel = model
                    log('模型已切换: ' + newPath)
                }
            } catch (e) {
                console.error('切换模型失败:', e)
            }
        })

        // 监听复位位置
        ipcRenderer.on('reset-pet-position', () => {
            if (model) {
                // 通过统一交互控制器复位
                if (modelCtrl && modelCtrl.setupInitialModelProperties) {
                    modelCtrl.setupInitialModelProperties()
                }
                log('皮套位置已复位')
            }
        })

        // 监听配置重载
        ipcRenderer.on('reload-config', () => {
            try {
                const oldConfig = JSON.parse(JSON.stringify(config))
                config = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'))


                // TTS 启用
                const ttsEnabled = config?.tts?.enabled !== false
                if (tts.enabled !== ttsEnabled) {
                    log('TTS: ' + (ttsEnabled ? '启用' : '禁用'))
                }
                tts.enabled = ttsEnabled

                // TTS 语言
                const oldLang = tts.language
                tts.language = config?.tts?.language || 'zh'
                if (oldLang !== tts.language) {
                    log('TTS 语言: ' + tts.language)
                }

                // 模型可见性
                if (model) {
                    const showModel = config?.ui?.show_model !== false
                    const oldShowModel = oldConfig?.ui?.show_model !== false
                    if (showModel !== oldShowModel) {
                        log('模型已' + (showModel ? '显示' : '隐藏'))
                    }
                    model.visible = showModel
                }

                // 字幕标签
                const subtitleEnabled = config?.subtitle_labels?.enabled !== false
                const oldSubtitleEnabled = oldConfig?.subtitle_labels?.enabled !== false
                if (subtitleEnabled !== oldSubtitleEnabled) {
                    log('字幕已' + (subtitleEnabled ? '启用' : '禁用'))
                }
                const newUser = config?.subtitle_labels?.user || ''
                const oldUser = oldConfig?.subtitle_labels?.user || ''
                const newAi = config?.subtitle_labels?.ai || ''
                const oldAi = oldConfig?.subtitle_labels?.ai || ''
                if (newUser !== oldUser || newAi !== oldAi) {
                    log('字幕标签: ' + (newUser || '用户') + ' / ' + (newAi || 'AI'))
                }

                // 上下文限制
                const contextLimit = config?.context?.enable_limit !== false
                const oldContextLimit = oldConfig?.context?.enable_limit !== false
                if (contextLimit !== oldContextLimit) {
                    log('上下文限制已' + (contextLimit ? '启用' : '禁用'))
                }

                // 最大消息数
                const maxMessages = config?.context?.max_messages || 18
                const oldMaxMessages = oldConfig?.context?.max_messages || 18
                if (maxMessages !== oldMaxMessages) {
                    log('最大消息数已调整为: ' + maxMessages)
                }

                // 温度
                const temperature = config?.llm?.temperature || 0.7
                const oldTemperature = oldConfig?.llm?.temperature || 0.7
                if (temperature !== oldTemperature) {
                    log('温度已调整为: ' + temperature)
                }

                // 温度开关
                const tempEnabled = config?.llm?.temperature_enabled || false
                const oldTempEnabled = oldConfig?.llm?.temperature_enabled || false
                if (tempEnabled !== oldTempEnabled) {
                    log('温度设置已' + (tempEnabled ? '启用' : '禁用'))
                }


                // BERT 分类热重载
                const bertEnabled = config?.bert?.enabled || false
                if (bertEnabled !== (oldConfig?.bert?.enabled || false)) {
                    log('BERT: ' + (bertEnabled ? '启用' : '禁用'))
                    logToTerminal('info', 'BERT: ' + (bertEnabled ? '已启用' : '已禁用'))
                }

                // 同步 voiceChat API 信息（插件 callLLM 使用）
                if (global.voiceChat) {
                    global.voiceChat.API_URL = config?.llm?.api_url || ''
                    global.voiceChat.API_KEY = config?.llm?.api_key || ''
                    global.voiceChat.MODEL = config?.llm?.model || ''
                }

            } catch (e) {
                log('重载配置失败: ' + e.message, 'error')
            }
        })

        // MCP 配置热重载（WebUI 保存小米配置后触发）
        ipcRenderer.on('mcp-reload-config', () => {
            try {
                // 重新读取小米配置（下次 MCP 调用时自动生效）
                log('MCP 配置已热重载')
            } catch (e) {
                log('MCP 热重载失败: ' + e.message, 'error')
            }
        })

        // 情绪表情映射热重载
        ipcRenderer.on('reload-emotion-config', () => {
            try {
                emotionMapper.reloadConfig()
                log('情绪表情映射已热重载')
            } catch (e) {
                log('情绪映射热重载失败: ' + e.message, 'error')
            }
        })

        // 预览表情
        ipcRenderer.on('preview-expression', (event, exprName) => {
            try {
                if (model) {
                    // 尝试直接调用表情（可能失败，因为未注册到model3.json）
                    try {
                        model.expression(exprName)
                    } catch (e) {
                        // 如果失败，用参数模拟微笑效果作为预览
                        const inner = model.innerModel || model
                        if (inner.internalModel && inner.internalModel.coreModel) {
                            const cm = inner.internalModel.coreModel
                            try { cm.setParameterValueById('ParamEyeLSmile', 1) } catch (e) {}
                            try { cm.setParameterValueById('ParamEyeRSmile', 1) } catch (e) {}
                            try { cm.setParameterValueById('ParamMouthForm', 0.5) } catch (e) {}
                            setTimeout(() => {
                                try { cm.setParameterValueById('ParamEyeLSmile', 0) } catch (e) {}
                                try { cm.setParameterValueById('ParamEyeRSmile', 0) } catch (e) {}
                                try { cm.setParameterValueById('ParamMouthForm', 0) } catch (e) {}
                            }, 2000)
                        }
                    }
                    log('预览表情: ' + exprName)
                }
            } catch (e) {
                log('预览表情失败: ' + e.message, 'error')
            }
        })

        // 切换表情（开/关）
        ipcRenderer.on('toggle-expression', (event, data) => {
            try {
                if (!model) return
                const inner = model.innerModel || model
                if (!inner.internalModel || !inner.internalModel.coreModel) return
                const cm = inner.internalModel.coreModel

                // 读取表情文件获取参数
                const fs = require('fs')
                const modelPath = config?.ui?.model_path || ''
                const charMatch = modelPath.match(/2D\/([^\/]+)\//)
                const charName = charMatch ? charMatch[1] : ''
                const exprPath = path.join(__dirname, '2D', charName, data.file)
                if (!fs.existsSync(exprPath)) {
                    log('表情文件不存在: ' + data.file, 'warn')
                    return
                }
                const exprData = JSON.parse(fs.readFileSync(exprPath, 'utf8'))
                const params = exprData.Parameters || []

                if (data.active) {
                    // 开启：设置参数值
                    for (const p of params) {
                        try { cm.setParameterValueById(p.Id, p.Value) } catch (e) {}
                    }
                    log('开启表情: ' + data.name + ' (' + params.map(p => p.Id).join(', ') + ')')
                } else {
                    // 关闭：重置参数为默认值（0）
                    for (const p of params) {
                        try { cm.setParameterValueById(p.Id, 0) } catch (e) {}
                    }
                    log('关闭表情: ' + data.name)
                }
            } catch (e) {
                log('切换表情失败: ' + e.message, 'error')
            }
        })


        log('myspy 启动完成')

        // 订阅后端动作广播：控制台等来源的对话也会驱动桌宠动作
        subscribePetEvents()


    } catch (e) {
        console.error('初始化失败:', e)
    }
}

// 构建 LLM 请求体
function buildRequestBody(messages, tools) {
    const body = {
        model: config.llm.model,
        messages: messages
    }
    if (tools && tools.length > 0) {
        body.tools = tools
    }
    if (config.llm.temperature_enabled) {
        body.temperature = config.llm.temperature || 0.7
    }
    return body
}

// 清洗消息以兼容各种 LLM API
function cleanMessagesForAPI(messages) {
    return messages.map(msg => {
        const cleaned = { ...msg }
        // null content → 空字符串
        if (cleaned.content === null || cleaned.content === undefined) {
            cleaned.content = ''
        }
        // tool message 对象 → JSON.stringify
        if (cleaned.role === 'tool' && typeof cleaned.content === 'object' && cleaned.content !== null) {
            cleaned.content = JSON.stringify(cleaned.content)
        }
        // 字符串内容：过滤控制字符，截断超长内容
        if (typeof cleaned.content === 'string') {
            cleaned.content = cleaned.content.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '')
            if (cleaned.content.length > 8000) {
                cleaned.content = cleaned.content.substring(0, 8000) + '...(内容已截断)'
            }
        }
        return cleaned
    })
}

// ============ Nuomi 后端模式（SSE）：后端统一执行工具，壳只消费事件流播放 ============

// 动作映射表：pet_action 工具参数 → 壳可播放的 motion（aidang 分组）/ 表情组合
// aidang 可用分组：idle/home/login/mail/main_1~3/mission/mission_complete/complete/wedding/touch_body/touch_head/touch_special
const PET_ACTION_MAP = {
    heart:     { motion: 'touch_special', expressions: ['开心', '害羞'], text: '比心' },
    wave:      { motion: 'main_1', expressions: ['开心'], text: '挥手' },
    dance:     { motion: 'main_2', expressions: ['开心'], text: '跳舞' },
    sleep:     { motion: 'idle', expressions: [], text: '睡觉' },
    nod:       { motion: 'main_3', expressions: [], text: '点头' },
    shake_head:{ motion: 'touch_head', expressions: [], text: '摇头' },
    blow_kiss: { motion: 'touch_special', expressions: ['开心', '害羞'], text: '飞吻' }
}

// 桌宠动作播放：表情组合（5s 自动恢复）+ 动作（Tap 兜底）
function playPetAction(action) {
    const cfg = PET_ACTION_MAP[action] || { motion: 'Tap', expressions: ['开心'], text: action }
    log('桌宠动作: ' + (cfg.text || action), 'info')
    try {
        if (cfg.expressions && cfg.expressions.length > 0) {
            for (const e of cfg.expressions) {
                if (_applyEmotionExpression) _applyEmotionExpression(e)
            }
        }
        if (cfg.motion && model) model.motion(cfg.motion)
    } catch (e) {
        log('动作播放失败: ' + e.message, 'warn')
    }
}

// tool_result → 播放器（pet_action 动作 / set_emotion 表情）
function handleNuomiToolResult(name, content) {
    let data = {}
    try { data = JSON.parse(content || '{}') } catch (e) { return }
    // 模型插件（工具名=动作/表情名）：返回 {motion} 或 {expression}，直接播放
    if (data.motion) {
        log('桌宠动作: ' + data.motion, 'info')
        try { if (model) model.motion(data.motion) } catch (e) { log('动作播放失败: ' + e.message, 'warn') }
        return
    }
    if (data.expression) {
        log('桌宠表情: ' + data.expression, 'info')
        try {
            if (model) model.expression(data.expression)
        } catch (e) { log('表情播放失败: ' + e.message, 'warn') }
        return
    }
    // 兼容旧插件 pet_action（已废弃，仅防御性保留）
    if (name === 'pet_action' && data.action) {
        playPetAction(data.action)
    }
}


// 按工具名播放动作/表情（模型插件工具名 = 动作/表情名）
let lastPlayedTool = null // 去重：广播动作与本地播放（1s 内同名跳过）
function playPetToolByName(name) {
    lastPlayedTool = { name, ts: Date.now() }
    log('桌宠工具: ' + name, 'info')
    try {
        if (model && model.motion) { model.motion(name); return }
    } catch (e) { log('动作播放失败: ' + e.message, 'warn') }
    try {
        if (model && model.expression) model.expression(name)
    } catch (e) { log('表情播放失败: ' + e.message, 'warn') }
}

// 订阅后端动作广播：控制台等任何来源的对话触发工具调用时，桌宠同步播放
async function subscribePetEvents() {
    try {
        const base = String(config.llm.api_url || '').replace(/\/api\/v1\/?$/, '') || 'http://127.0.0.1:8000'
        const res = await fetch(base + '/api/pet/events')
        const reader = res.body.getReader()
        const decoder = new TextDecoder('utf-8')
        let buffer = ''
        while (true) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const lines = buffer.split('\n')
            buffer = lines.pop() || ''
            for (const line of lines) {
                const t = line.trim()
                if (!t.startsWith('data:')) continue
                const p = t.slice(5).trim()
                if (!p) continue
                let ev
                try { ev = JSON.parse(p) } catch (e) { continue }
                if (ev.type === 'tool_call' && ev.name) {
                    const now = Date.now()
                    if (lastPlayedTool && lastPlayedTool.name === ev.name && now - lastPlayedTool.ts < 1000) continue
                    playPetToolByName(ev.name)
                }
            }
        }
    } catch (e) { log('订阅连接失败: ' + e.message, 'warn') }
    setTimeout(subscribePetEvents, 3000)
}

// 流式 LLM 调用 - 逐块返回文本
async function callLLMStream(messages, tools = null, onChunk = null) {
    const url = config.llm.api_url + '/chat/completions'
    const key = config.llm.api_key
    let cleaned = cleanMessagesForAPI(messages)
    const body = buildRequestBody(cleaned, tools)
    body.stream = true

    log('LLM流式请求: ' + url + ' 消息数: ' + messages.length)

    const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
        body: JSON.stringify(body)
    })

    log('LLM流式响应状态: ' + response.status)

    if (!response.ok) {
        const errorText = await response.text()
        throw new Error(`API错误 ${response.status}: ${errorText}`)
    }

    // 读取 SSE 流
    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let fullContent = ''
    let hasToolCalls = false
    let toolCallsData = []

    while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split('\n')
        buffer = lines.pop() || ''  // 保留未完成的行

        for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed || trimmed.startsWith('data: [DONE]')) continue

            if (trimmed.startsWith('data:')) {
                const jsonStr = trimmed.startsWith('data: ') ? trimmed.slice(6) : trimmed.slice(5)
                try {
                    const chunk = JSON.parse(jsonStr)
                    const choice = chunk.choices?.[0]

                    if (!choice) continue

                    // 检查是否有工具调用
                    if (choice.delta?.tool_calls) {
                        hasToolCalls = true
                        for (const tc of choice.delta.tool_calls) {
                            if (tc.index !== undefined) {
                                if (!toolCallsData[tc.index]) {
                                    toolCallsData[tc.index] = {
                                        id: tc.id || '',
                                        type: tc.type || 'function',
                                        function: { name: '', arguments: '' }
                                    }
                                }
                                if (tc.id) toolCallsData[tc.index].id = tc.id
                                if (tc.function?.name) toolCallsData[tc.index].function.name += tc.function.name
                                if (tc.function?.arguments) toolCallsData[tc.index].function.arguments += tc.function.arguments
                            }
                        }
                    }

                    // 检查文本内容
                    const delta = choice.delta
                    if (delta?.content) {
                        fullContent += delta.content
                        if (onChunk) onChunk(delta.content)
                    }
                } catch (e) {
                    // 解析失败跳过
                }
            }
        }
    }

    // 如果有工具调用，返回特殊格式
    if (hasToolCalls && toolCallsData.length > 0) {
        return {
            content: fullContent || null,
            tool_calls: toolCallsData.filter(Boolean)
        }
    }

    return { content: fullContent }
}

// 发送消息


// 窗口关闭时清理 MCP
window.addEventListener('beforeunload', () => {
    if (global.mcpManager) {
        global.mcpManager.stop()
    }
})


// 自定义右键菜单
const contextMenu = document.getElementById('custom-context-menu')
let contextMenuTarget = null

document.addEventListener('contextmenu', (e) => {
    e.preventDefault()
    contextMenuTarget = e.target

    // 显示菜单
    contextMenu.style.display = 'block'
    contextMenu.style.left = e.clientX + 'px'
    contextMenu.style.top = e.clientY + 'px'

    // 边界检测
    const rect = contextMenu.getBoundingClientRect()
    if (rect.right > window.innerWidth) {
        contextMenu.style.left = (e.clientX - rect.width) + 'px'
    }
    if (rect.bottom > window.innerHeight) {
        contextMenu.style.top = (e.clientY - rect.height) + 'px'
    }
})

document.addEventListener('click', () => {
    contextMenu.style.display = 'none'
})

document.querySelectorAll('.ctx-menu-item').forEach(item => {
    item.addEventListener('click', () => {
        const action = item.dataset.action
        if (action === 'copy') {
            document.execCommand('copy')
        } else if (action === 'paste') {
            navigator.clipboard.readText().then(text => {
                if (contextMenuTarget && contextMenuTarget.tagName === 'INPUT') {
                    contextMenuTarget.value += text
                }
            })
        } else if (action === 'devtools') {
            ipcRenderer.send('open-devtools')
        }
        contextMenu.style.display = 'none'
    })
})


main()
