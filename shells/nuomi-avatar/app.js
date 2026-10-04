// app.js - 渲染进程入口
const fs = require('fs')
const path = require('path')
const { pathToFileURL } = require('url')
const { ipcRenderer } = require('electron')

// 模型资产在工作区（后端下发绝对路径）→ 转 file:// URL 供加载
function toModelUrl(p) {
    if (typeof p === 'string' && p.startsWith('/')) return pathToFileURL(p).href
    return p
}
const { TTSClient } = require('./js/tts-client')
const { TTSStreamProcessor } = require('./js/tts-stream-processor')
const { EmotionExpressionMapper } = require('./js/emotion-expression-mapper')
const { VRMModelSetup } = require('./js/model/vrm-model-setup.js')
const { VRMInteractionController } = require('./js/model/vrm-model-interaction.js')
const { UnifiedModelAdapter } = require('./js/model/unified-model-adapter.js')
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
    { role: 'system', content: config?.llm?.system_prompt || '你是一个可爱的AIAI 数字人助手。' }
]


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
        // 表情文件与模型同目录（工作区模型资产）
        const exprPath = path.join(path.dirname(modelPath), exprName + '.exp3.json')
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

// 设置全局对话环境（供AI 数字人表现层使用；对话已收归控制台，sendToLLM 不再可用）
const voiceChat = {
    messages: messages,
    API_URL: config?.llm?.api_url || '',
    API_KEY: config?.llm?.api_key || '',
    MODEL: config?.llm?.model || '',
    ttsProcessor: tts,
    sendToLLM: async () => { /* 对话仅控制台，AI 数字人不再发消息 */ },
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
// AI 数字人与控制台共用同一「当前会话」：控制台切会话（后端写 config.json）后，
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
        // 方案B（2026-10-04）：只支持 VRM 3D 模型（2D Live2D/图片已下线）
        // 1. 优先使用配置的模型路径（后端下发）
        // 2. 根据文件扩展名自动检测类型（.vrm → VRM）
        // 3. 如果没配置，扫描 3D/ 目录自动选择
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

        // 兜底默认值（模型路径由后端下发；无则报错提示，不再指向仓库内置路径）
        if (!modelType) modelType = 'vrm'
        if (!modelPath) logToTerminal('error', '未配置模型路径（后端未下发 ui.model_path）')

        logToTerminal('info', `模型类型: ${modelType}, 路径: ${modelPath}`)

        // 方案B：仅支持 VRM。非 VRM 模型类型直接报错（2D 已下线，不静默降级）
        if (modelType !== 'vrm') {
            logToTerminal('error', `不支持的模型类型 ${modelType}（2D Live2D 已下线，仅支持 VRM 3D）`)
        }
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
                // 自动检测新模型类型（方案B：仅支持 VRM，2D 已下线）
                const newType = ModelScanner.detectType(newPath) || config?.ui?.model_type || 'vrm'
                log('切换模型: ' + newPath + ' (类型: ' + newType + ')')

                if (newType !== 'vrm') {
                    log('不支持的模型类型 ' + newType + '（2D Live2D/图片已下线，仅支持 VRM 3D）')
                    return
                }
                // VRM 切换：后端已同步 config.ui.model_path，重载页面让 initialize 读取新模型（窗口不关，零重启）
                log('VRM 模型切换：重载页面加载新模型')
                setTimeout(() => window.location.reload(), 400)
            } catch (e) {
                console.error('切换模型失败:', e)
            }
        })

        // 监听复位位置
        ipcRenderer.on('reset-avatar-position', () => {
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


        log('糯米启动完成')

        // 订阅后端动作广播：控制台等来源的对话也会驱动AI 数字人动作
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

// 语义动作映射表（P1 改造用：未来后端工具名直接用语义名，壳内部映射到 motion+expression 组合）
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

// 表情自动恢复定时器：LLM 调一次表情工具后，N 秒后自动回默认表情（避免脸卡死）
let _expressionRecoveryTimer = null
const EXPRESSION_RECOVERY_MS = 8000

// 状态→表情映射（第 2 层：LLM 状态自动切脸）
const STATUS_EXPRESSION = {
    thinking: 'Surprised',  // 思考中 → 瞪眼张嘴（夸张）
    working: 'Angry',       // 干活中 → 倒八字眉（用力）
    idle: 'Normal',         // 空闲 → 恢复
}

function playStatusExpression(status) {
    if (!model) return
    log('AI 数字人状态: ' + status, 'info')
    try {
        // 显式表情在播时（用户主动要求 set_expression_*），状态表情让位，不覆盖
        if (_expressionRecoveryTimer) return

        if (status === 'idle') {
            // 空闲：若有显式表情在播（playPetExpression 恢复定时器未到期），不重置
            if (_expressionRecoveryTimer) return
            // 重置所有表情参数到默认
            try { model.expression() } catch (e) {}
            return
        }

        const expr = STATUS_EXPRESSION[status]
        if (!expr) return
        model.expression(expr)
    } catch (e) { log('状态表情失败: ' + e.message, 'warn') }
}

function playPetMotion(name) {
    if (!model) return
    log('AI 数字人动作: ' + name, 'info')
    try { model.motion(name) } catch (e) { log('动作播放失败: ' + e.message, 'warn') }
}

function playPetExpression(name) {
    if (!model) return
    log('AI 数字人表情: ' + name, 'info')
    try {
        model.expression(name)
        // 重置旧定时器（连续表情调用时刷新恢复时间）
        if (_expressionRecoveryTimer) {
            clearTimeout(_expressionRecoveryTimer)
            _expressionRecoveryTimer = null
        }
        // N 秒后恢复默认表情（pixi expression() 不传参=重置所有表情参数）
        _expressionRecoveryTimer = setTimeout(() => {
            try { model.expression() } catch (e) {}
            _expressionRecoveryTimer = null
        }, EXPRESSION_RECOVERY_MS)
    } catch (e) { log('表情播放失败: ' + e.message, 'warn') }
}

// 按动作 payload 播放（后端已解析好 motion+expressions 组合，壳不再反查）
let lastPlayedAction = null // 去重：1s 内同 label 跳过
function playAvatarActionPayload(payload) {
    if (!payload) return
    const label = payload.label || payload.motion || payload.expressions?.[0] || 'action'
    const now = Date.now()
    if (lastPlayedAction && lastPlayedAction.label === label && now - lastPlayedAction.ts < 1000) return
    lastPlayedAction = { label, ts: now }
    log('AI 数字人动作: ' + label, 'info')
    if (payload.motion) playPetMotion(payload.motion)
    for (const expr of (payload.expressions || [])) playPetExpression(expr)
}

// 订阅后端动作广播：控制台等任何来源的对话触发工具调用时，AI 数字人同步播放
async function subscribePetEvents() {
    try {
        const base = String(config.llm.api_url || '').replace(/\/api\/v1\/?$/, '') || 'http://127.0.0.1:8000'
        const res = await fetch(base + '/api/avatar/events')
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
                if (ev.type === 'avatar_action') {
                    playAvatarActionPayload(ev)
                } else if (ev.type === 'avatar_status') {
                    playStatusExpression(ev.status)
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
