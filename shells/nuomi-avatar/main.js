/**
 * 糯米壳（nuomi-avatar）主进程。
 *
 * ========================= 安全取舍说明（2026-10-06）=========================
 * 数字人窗口仍然是 `nodeIntegration: true` + `contextIsolation: false`，**这是刻意的**：
 *   1. 渲染进程需要用 Node `fs` 直接读本地 VRM 资产（工作区绝对路径，可能是任意目录），
 *      并用 `require()` 加载 three.js / @pixiv/three-vrm（ESM 需 esbuild 预打包成 CJS）；
 *   2. 迁移到 `contextIsolation + preload` 需要把 fs/path/require、IPC、动画资产加载
 *      全部改造成 preload 暴露的 API（app.js + js/** 约 6k 行），改动面大、回归风险高，
 *      而收益在当前威胁模型下有限。
 *
 * 因此风险边界必须靠「不加载远端内容」来兜底，本次已落地的三道闸门：
 *   · index.html 的 CSP meta：只允许 'self' + file: + http://127.0.0.1:*，挡掉远端脚本；
 *   · 两个窗口的 will-navigate / setWindowOpenHandler 白名单（见 lockNavigation）；
 *   · 控制台窗口本身就是 nodeIntegration:false + contextIsolation:true。
 *
 * 将来若要彻底收紧，需要动的文件：main.js（webPreferences + 新增 preload.js 暴露
 * fs/IPC 白名单接口）、index.html（引用 preload）、app.js（require('fs'/'path'/'electron')
 * 改走 window.nuomi API）、js/model/vrm-model-setup.js、js/tts-client.js、
 * js/tts-stream-processor.js、js/api-utils.js（日志 IPC）。
 * ===========================================================================
 */

const { app, BrowserWindow, ipcMain, screen, dialog } = require('electron')
const path = require('path')
const fs = require('fs')
const http = require('http')
const { spawn } = require('child_process')

const configPath = path.join(app.getAppPath(), 'config.json')

// 本机配置不入库（运行态：模型绝对路径、数字人开关都会被回写），模板是
// config.example.json。全新克隆直接跑 `npm start` 会因文件不存在而静默拿到空配置
// —— 连不上后端还看不出来，所以这里首启播种一次。打包态 app.asar 只读，
// 复制会失败，忽略即可（打包时 config.json 已在 asar 里）。
;(function ensureConfig() {
    if (fs.existsSync(configPath)) return
    const example = path.join(path.dirname(configPath), 'config.example.json')
    if (!fs.existsSync(example)) return
    try {
        fs.copyFileSync(example, configPath)
        console.log('[config] 首次运行：已从 config.example.json 生成本机配置')
    } catch (e) {
        console.warn('[config] 播种本机配置失败（打包态只读属正常）:', e.message)
    }
})()

// 仓库根 .logs/（已 gitignore）：壳 / 后端 / 前端的 pid 与日志统一落在这里
const LOG_DIR = path.join(__dirname, '..', '..', '.logs')
const BACKEND_PID_FILE = path.join(LOG_DIR, 'backend.pid')

// === 后端自动拉起（2026-10-05）：壳启动时检测 nuomi 后端，未就绪则 spawn uvicorn ===
function checkBackendReady(origin, timeoutMs = 1500) {
    return new Promise((resolve) => {
        const req = http.get(origin + '/api/health', { timeout: timeoutMs }, (res) => {
            res.resume()
            res.on('end', () => resolve(res.statusCode === 200))
        })
        req.on('timeout', () => { req.destroy(); resolve(false) })
        req.on('error', () => resolve(false))
    })
}

// 必须是「文件」，不能只是路径存在：目录/软链目录会让模型加载静默失败
function isFile(p) {
    if (!p || typeof p !== 'string') return false
    try { return fs.statSync(p).isFile() } catch (e) { return false }
}

// 主进程内的极简 JSON GET（无 CORS/Origin 约束）。失败一律 resolve(null)，
// 调用方按「拿不到就降级」处理，不抛异常。
function httpGetJson(url, timeoutMs = 3000) {
    return new Promise((resolve) => {
        const req = http.get(url, { timeout: timeoutMs }, (res) => {
            let body = ''
            res.setEncoding('utf8')
            res.on('data', (chunk) => { body += chunk })
            res.on('end', () => {
                if (res.statusCode !== 200) return resolve(null)
                try { resolve(JSON.parse(body)) } catch (e) { resolve(null) }
            })
        })
        req.on('timeout', () => { req.destroy(); resolve(null) })
        req.on('error', () => resolve(null))
    })
}

// === 本机 API token（写操作鉴权，见 backend/app/infra/local_guard.py）===
// 主进程用 Node http 取（无 Origin/CORS 约束），缓存后经 IPC 交给渲染进程。
// 后端进程重启会换 token，渲染进程收到 403 时会重新 invoke 拿新的。
let apiTokenPromise = null
function loadApiToken(origin) {
    if (!apiTokenPromise) {
        apiTokenPromise = new Promise((resolve) => {
            const req = http.get(origin + '/api/session-token', { timeout: 3000 }, (res) => {
                let body = ''
                res.setEncoding('utf8')
                res.on('data', (chunk) => { body += chunk })
                res.on('end', () => {
                    try { resolve(JSON.parse(body).token || '') } catch (e) { resolve('') }
                })
            })
            req.on('timeout', () => { req.destroy(); resolve('') })
            req.on('error', () => resolve(''))
        })
    }
    return apiTokenPromise
}
function refreshApiToken() {
    apiTokenPromise = null
    return loadApiToken(backendOrigin())
}
ipcMain.handle('api-token', () => loadApiToken(backendOrigin()))
ipcMain.handle('refresh-api-token', () => refreshApiToken())

// 后端 pid 落盘 + 常驻提示。
// 为什么：壳用 detached+unref 拉起后端是刻意设计（壳退出后端继续常驻，控制台/对话不断线），
// 但之前不记录 pid，用户只能靠 `make stop` 按端口杀 —— 换成记录 pid，停止方式可追溯。
function recordBackendPid(pid) {
    if (!pid) return
    try {
        fs.mkdirSync(LOG_DIR, { recursive: true })
        fs.writeFileSync(BACKEND_PID_FILE, String(pid), 'utf8')
    } catch (e) {
        console.error('[backend] 写入 backend.pid 失败: ' + e.message)
    }
    console.log('[backend] 后端已常驻（detached，壳退出不会被带走），pid=' + pid)
    console.log('[backend] 停止方式：kill ' + pid + '（或 make stop 按端口杀；pid 文件 .logs/backend.pid）')
}

function ensureBackend() {
    const origin = backendOrigin()
    return checkBackendReady(origin).then(async (alive) => {
        if (alive) {
            console.log('后端已就绪: ' + origin)
            // 已有后端（make backend / 上一次壳启动留下的常驻进程）：壳不接管、退出也不动它
            try {
                const pid = fs.readFileSync(BACKEND_PID_FILE, 'utf8').trim()
                if (pid) console.log('[backend] 复用已运行的后端（记录 pid=' + pid + '，停止方式：kill ' + pid + '）')
            } catch (e) {}
            return { started: false }
        }
        console.log('后端未就绪，自动拉起 uvicorn ...')
        const backendDir = path.join(__dirname, '..', '..', 'backend')
        const venvPython = path.join(backendDir, '.venv', 'bin', 'python')
        const python = fs.existsSync(venvPython) ? venvPython : 'python3'
        const port = new URL(origin).port || '8000'
        // 后端日志写 .logs/backend.log（文件 fd，非 pipe）：
        // ① uvicorn 访问日志不刷壳日志；② 壳退出后 pipe 断开不再 SIGPIPE 误杀常驻后端
        const backendLog = path.join(LOG_DIR, 'backend.log')
        try { fs.mkdirSync(path.dirname(backendLog), { recursive: true }) } catch (e) {}
        const logFd = fs.openSync(backendLog, 'a')
        const child = spawn(
            python,
            ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', port],
            { cwd: backendDir, stdio: ['ignore', logFd, logFd], env: process.env, detached: true }
        )
        child.unref() // 脱离壳进程组：壳退出后后端保持常驻
        child.on('error', (err) => console.error('[backend] 启动失败: ' + err.message))
        recordBackendPid(child.pid)

        // 最多等 30s 健康检查通过（后端含依赖加载/嵌入模型就绪）
        const deadline = Date.now() + 30000
        while (Date.now() < deadline) {
            if (await checkBackendReady(origin, 1000)) {
                console.log('后端已由壳拉起并就绪: ' + origin)
                return { started: true, pid: child.pid }
            }
            await new Promise((r) => setTimeout(r, 1000))
        }
        console.error('[backend] 30s 内未就绪（端口被占用或启动失败），控制面板将按重试逻辑兜底')
        return { started: false, pid: child.pid }
    })
}

/**
 * 解析真正可用的 VRM 模型绝对路径（2026-10-06）。
 *
 * 为什么：config.json 里的 ui.model_path 是「上一台机器上的绝对路径」
 * （如 /Users/<别人>/Nuomi/models/3D/xxx.vrm），仓库里不含任何 .vrm 资产，
 * 换机器/换用户目录后该路径必然不存在 → 数字人静默白屏。所以不信任配置里的路径：
 *   1. 配置路径确实存在 → 直接用（日常快路径，零网络开销）
 *   2. 不存在 → 向后端 GET /api/avatar/models（返回 {models:[{id,path,...}], active}）
 *      问当前激活模型，取真实路径**回写 config.json**（渲染进程读 config 即拿到正确路径，
 *      不必改动渲染进程的模型加载链路；同时把 main.js 的 fs.watch 切换逻辑也修好）
 *   3. 都拿不到 → 返回 null，调用方弹可读错误框（不做静默白屏）
 *
 * 注意：后端地址来自 config.json 的 llm.api_url（形如 http://127.0.0.1:8000/api/v1），
 * 这里只用它的 origin，再拼 /api/avatar/models。
 *
 * 已知边界：打包态 config.json 位于 app.asar 内只读，回写会失败——此时路径仍通过
 * `--nuomi-model=` 参数下发给渲染进程（见 createWindow 的 additionalArguments），
 * 保证本次启动能正常渲染；但「切换模型后持久化」在打包态仍需可写 config（见 README 遗留项）。
 */
async function resolveModelPath() {
    let cfg = {}
    try { cfg = JSON.parse(fs.readFileSync(configPath, 'utf8')) } catch (e) {}
    const ui = cfg.ui || {}
    const configured = ui.model_path

    if (isFile(configured)) {
        console.log('[model] 使用 config.json 中的模型路径: ' + configured)
        return configured
    }
    console.warn('[model] config.json 的模型路径不可用: ' + (configured || '(未配置)'))

    const origin = backendOrigin()
    const url = origin + '/api/avatar/models'
    const data = await httpGetJson(url, 5000)
    const models = Array.isArray(data && data.models) ? data.models : []
    if (!models.length) {
        console.error('[model] 后端 ' + url + ' 未返回任何模型')
        return null
    }
    // 优先 active 指向的模型；active 缺失/失配时退到列表第一个（能渲染总比白屏好）
    const hit = models.find((m) => m && m.id && m.id === data.active) || models[0]
    const realPath = hit && typeof hit.path === 'string' ? hit.path : ''
    if (!isFile(realPath)) {
        console.error('[model] 后端下发的模型路径不存在: ' + (realPath || '(空)'))
        return null
    }
    console.log('[model] 已从后端解析到激活模型: ' + hit.id + ' -> ' + realPath)

    // 回写 config.json：让渲染进程（fs 直读配置）与 fs.watch 切换逻辑都拿到真实路径
    try {
        cfg.ui = Object.assign({}, ui, {
            model_path: realPath,
            model: hit.id || ui.model,
            model_type: hit.type || ui.model_type || 'vrm'
        })
        fs.writeFileSync(configPath, JSON.stringify(cfg, null, 2), 'utf8')
        console.log('[model] 已回写 config.json（ui.model_path / ui.model）')
    } catch (e) {
        // 打包态 app.asar 只读；本次启动靠 --nuomi-model 参数兜底，不回退成白屏
        console.error('[model] 回写 config.json 失败（打包态 asar 只读）: ' + e.message)
    }
    return realPath
}

/**
 * 导航封锁（安全基线，2026-10-06）。
 *
 * 数字人窗口是 nodeIntegration:true 的：一旦它能被导航到远端页面，等于把 Node 能力
 * 交给远端脚本。所以两个窗口只允许停在「本地 file:// + 127.0.0.1 后端」这两类地址上，
 * 其余跳转/新窗口一律拒绝并打日志。
 */
function isAllowedTarget(rawUrl) {
    try {
        const u = new URL(rawUrl)
        if (u.protocol === 'file:') return true
        const isLocalHost = u.hostname === '127.0.0.1' || u.hostname === 'localhost' || u.hostname === '[::1]'
        if ((u.protocol === 'http:' || u.protocol === 'https:') && isLocalHost) return true
        return false
    } catch (e) {
        return false // 解析不了（about:blank / javascript: 等）一律不放行
    }
}

function lockNavigation(win, label) {
    win.webContents.on('will-navigate', (event, url) => {
        if (!isAllowedTarget(url)) {
            event.preventDefault()
            console.warn('[security] ' + label + ' 已拦截导航: ' + url)
        }
    })
    win.webContents.setWindowOpenHandler(({ url }) => {
        if (isAllowedTarget(url)) return { action: 'allow' }
        console.warn('[security] ' + label + ' 已拦截新窗口: ' + url)
        return { action: 'deny' }
    })
}

function createWindow(modelPathOverride) {
    let config = {}
    try {
        config = JSON.parse(fs.readFileSync(configPath, 'utf8'))
    } catch (e) {
        console.error('读取配置失败:', e)
    }

    const primaryDisplay = screen.getPrimaryDisplay()

    // AI 数字人窗口固定在主显示器内，避免跨屏导致窗口偏移到屏幕外
    const winW = primaryDisplay.bounds.width
    const winH = primaryDisplay.bounds.height
    const winX = primaryDisplay.bounds.x
    const winY = primaryDisplay.bounds.y

    const win = new BrowserWindow({
        x: winX,
        y: winY,
        width: winW,
        height: winH,
        transparent: true,
        frame: false,
        alwaysOnTop: true,
        backgroundColor: '#00000000',
        hasShadow: false,
        focusable: true,
        // macOS 上 type:'desktop' 透明窗口兼容性差，去掉以正常显示
        // type: 'desktop',
        webPreferences: {
            nodeIntegration: true,
            contextIsolation: false,
            // 主进程把「解析后的模型路径」下发给渲染进程：config.json 可能是只读的
            // （打包态在 app.asar 内），此时渲染进程读到的仍是旧路径——参数是兜底通道。
            additionalArguments: [
                '--nuomi-model=' + (modelPathOverride || currentModelPath || '')
            ]
        },
        resizable: true,
        movable: true,
        skipTaskbar: true
    })

    win.setAlwaysOnTop(true, 'screen-saver')
    win.setMenu(null)
    win.setIgnoreMouseEvents(true, { forward: true })
    win.loadFile('index.html')
    lockNavigation(win, '数字人窗口')

    // AI 数字人窗口关闭时清引用（控制面板是远程 /console/ 页面，无 preload，
    // 无需也收不到 IPC 通知，故不再发送 pet-stopped）
    win.on('closed', () => {
        avatarWindow = null
    })

    // 禁用默认右键菜单
    win.webContents.on('context-menu', (event) => {
        event.preventDefault()
    })

    // 降低置顶检查频率，避免影响任务栏点击
    setInterval(() => {
        if (!win.isDestroyed() && !win.isFocused() && !win.isAlwaysOnTop()) {
            win.setAlwaysOnTop(true, 'screen-saver')
        }
    }, 5000)

    return win
}

// 创建控制面板窗口（指向 nuomi 后端挂载的 React 控制台 /console/）
function backendOrigin() {
    try {
        const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'))
        const u = new URL(cfg.llm.api_url)
        return u.origin
    } catch (e) {
        return 'http://127.0.0.1:8000'
    }
}

function createControlPanel() {
    const panel = new BrowserWindow({
        width: 1100,
        height: 720,
        title: 'Nuomi 控制台',
        icon: path.join(__dirname, 'icon.png'),
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true
        }
    })

    panel.setMenu(null)
    lockNavigation(panel, '控制台窗口')

    // 后端可能尚未启动：加载失败则每 2s 重试（最多 30 次，约 1 分钟）
    const origin = backendOrigin()
    const panelUrl = origin + '/console/'
    let retries = 0
    const load = () => {
        if (!panel.isDestroyed()) panel.loadURL(panelUrl)
    }
    panel.webContents.on('did-fail-load', () => {
        retries += 1
        if (retries <= 30) {
            setTimeout(load, 2000)
        }
    })
    load()

    return panel
}

let avatarWindow = null
let controlPanel = null
// 启动时解析出的模型绝对路径（后端下发/配置里的有效路径），供后续重建窗口复用
let currentModelPath = null

// 动作资产导入/删除后，控制面板窗口跟随刷新（数字人渲染进程收到 SSE 后经 IPC 通知）
ipcMain.on('reload-control-panel', () => {
    if (controlPanel && !controlPanel.isDestroyed()) {
        controlPanel.reload()
        console.log('控制面板已刷新（动作资产变更）')
    }
})

/**
 * 显示/隐藏控制面板（数字人窗口上双击角色触发）。
 *
 * 关闭控制面板不再退出整个应用（见下方 controlPanel.on('closed')）：只关面板
 * 时数字人继续常驻，用户双击角色即可再打开；退出应用用 Cmd+Q / Ctrl+Q。
 */
function toggleControlPanel() {
    if (controlPanel && !controlPanel.isDestroyed()) {
        if (controlPanel.isVisible()) {
            controlPanel.hide()
        } else {
            controlPanel.show()
            controlPanel.focus()
        }
        return
    }
    controlPanel = createControlPanel()
    controlPanel.on('closed', () => { controlPanel = null })
}

ipcMain.on('toggle-control-panel', () => {
    toggleControlPanel()
})

// PTT 全局快捷键已废弃（旧 ASR 语音输入体系，renderer 无监听，2026-10-05 清理）

// ===== 单实例锁（2026-10-06）=====
// 为什么必须加：壳自己会拉起 uvicorn，双开 = 双数字人窗口 + 两个后端抢 :8000
// （还会互相争 config.json 的写权）。第二个实例直接退出，并把已有实例的窗口拉到前面。
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
    console.log('检测到糯米已在运行（单实例锁未取得），本次启动退出')
    app.quit()
} else {
    app.on('second-instance', () => {
        // 已有实例收到：把用户能看到的窗口 show/focus（数字人窗口是透明无边框的，
        // 单靠它用户容易「点了没反应」，所以控制面板优先）
        const wins = [controlPanel, avatarWindow].filter((w) => w && !w.isDestroyed())
        if (!wins.length) {
            // 数字人开关为关 + 控制面板被关过：进程活着却没窗口，补一个控制面板
            controlPanel = createControlPanel()
            controlPanel.on('closed', () => { controlPanel = null })
            return
        }
        for (const w of wins) {
            if (w.isMinimized()) w.restore()
            w.show()
            w.focus()
        }
        console.log('第二个实例已退出，聚焦到已有窗口')
    })

app.whenReady().then(() => {
    // 后端就绪（未启动则自动拉起）→ 解析模型路径 → 再创建窗口：
    // 控制面板加载依赖后端；模型路径依赖后端 /api/avatar/models
    ensureBackend()
        .catch((e) => { console.error('[backend] 就绪检查异常: ' + e.message); return null })
        .then(() => resolveModelPath())
        .catch((e) => { console.error('[model] 解析模型路径异常: ' + e.message); return null })
        .then((modelPath) => {
        currentModelPath = modelPath
        let initialConfig = {}
        try { initialConfig = JSON.parse(fs.readFileSync(configPath, 'utf8')) } catch (e) {}
        const petEnabled = (initialConfig.ui || {}).avatar_enabled !== false // 缺省开

        if (petEnabled) {
            if (!modelPath) {
                // 拿不到模型 = 必然白屏：给可读错误提示，别让用户对着透明窗口猜
                dialog.showErrorBox(
                    '糯米：找不到数字人模型',
                    '未能确定可用的 VRM 模型路径，数字人窗口可能是空白的。\n\n' +
                    '已尝试：\n' +
                    '  · config.json 的 ui.model_path：' + ((initialConfig.ui || {}).model_path || '(未配置)') + '\n' +
                    '  · 后端接口：' + backendOrigin() + '/api/avatar/models\n\n' +
                    '请依次确认：\n' +
                    '  1. 后端已启动（make backend，或 make start 自动拉起）\n' +
                    '  2. 工作区 models/3D/ 下至少有一个 .vrm 模型文件\n' +
                    '  3. 控制台「模型」页已选中一个模型'
                )
            }
            avatarWindow = createWindow(modelPath)
        } else {
            console.log('AI 数字人开关为关，跳过创建AI 数字人窗口')
        }
        controlPanel = createControlPanel()

        // 转发渲染进程日志到主进程 stdout（便于排查切换/加载问题）
        if (avatarWindow && avatarWindow.webContents) {
            avatarWindow.webContents.on('console-message', (event, level, message, line, sourceId) => {
                console.log('[renderer:' + level + '] ' + message + ' (' + line + ')')
            })
        }

    // 监听 config.json 的 ui.model 变化 → 自动切换模型（后端 /api/avatar/models/switch 写入 config）；
    // ui.avatar_enabled 变化 → 创建/销毁AI 数字人窗口（控制台「模型」页开关）
    let lastModelId = null
    let lastPetEnabled = petEnabled
    try {
        lastModelId = (JSON.parse(fs.readFileSync(configPath, 'utf8'))?.ui || {}).model || null
    } catch (e) {}
    fs.watch(configPath, () => {
        setTimeout(() => {
            try {
                const cfg = JSON.parse(fs.readFileSync(configPath, 'utf8'))
                const ui = (cfg?.ui) || {}
                // AI 数字人开关
                const petEnabledNow = ui.avatar_enabled !== false
                if (petEnabledNow !== lastPetEnabled) {
                    lastPetEnabled = petEnabledNow
                    if (petEnabledNow) {
                        if (!avatarWindow || avatarWindow.isDestroyed()) {
                            avatarWindow = createWindow()
                            console.log('AI 数字人开关打开，创建AI 数字人窗口')
                        }
                    } else {
                        if (avatarWindow && !avatarWindow.isDestroyed()) {
                            avatarWindow.destroy()
                            avatarWindow = null
                            console.log('AI 数字人开关关闭，销毁AI 数字人窗口')
                        }
                    }
                }
                // 模型切换
                const modelId = ui.model || null
                const modelPath = ui.model_path || null
                if (modelId && modelId !== lastModelId && avatarWindow && !avatarWindow.isDestroyed()) {
                    lastModelId = modelId
                    if (modelPath) {
                        avatarWindow.webContents.send('switch-model', modelPath)
                        console.log('检测到模型切换: ' + modelId + ' -> ' + modelPath)
                    }
                }
            } catch (e) {}
        }, 200) // 防抖：等配置文件写完
    })

    // 关闭控制面板**不退出**应用：数字人继续常驻（用户双击角色可再打开面板，
    // 退出走 Cmd+Q / Ctrl+Q）。原实现 app.quit() 会让"关掉控制台"= 整个桌宠消失。
    controlPanel.on('closed', () => {
        controlPanel = null
        console.log('控制面板已关闭（数字人继续运行，双击角色可重新打开）')
    })

        console.log('糯米启动完成')
        }) // ensureBackend → resolveModelPath 回调结束
}) // whenReady 结束
} // else（取得单实例锁）结束

app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') {
        app.quit()
    }
})

// macOS：Dock 图标被点击时兜底恢复窗口。
// 关闭控制面板已不再退出应用（见上），若此时数字人开关是关的，就会出现
// 「进程活着但一个窗口都没有」——点 Dock 若无反应，用户只能 Cmd+Q。
app.on('activate', () => {
    if (!controlPanel || controlPanel.isDestroyed()) {
        controlPanel = createControlPanel()
        controlPanel.on('closed', () => { controlPanel = null })
        return
    }
    controlPanel.show()
})

ipcMain.on('set-ignore-mouse-events', (event, { ignore, options }) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    if (win && !win.isDestroyed()) {
        win.setIgnoreMouseEvents(ignore, options || {})
    }
})

ipcMain.handle('get-window-bounds', (event) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    const bounds = win.getBounds()
    return { width: bounds.width, height: bounds.height, x: bounds.x, y: bounds.y }
})

// 保存 UI 配置（模型位置等）
ipcMain.on('save-ui-config', (event, data) => {
    try {
        let config = {}
        try { config = JSON.parse(fs.readFileSync(configPath, 'utf8')) } catch (e) {}
        if (!config.ui) config.ui = {}
        Object.assign(config.ui, data)
        fs.writeFileSync(configPath, JSON.stringify(config, null, 2), 'utf8')
    } catch (e) {
        console.error('保存 UI 配置失败:', e)
    }
})

ipcMain.on('open-devtools', (event) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    if (win && !win.isDestroyed()) {
        win.webContents.openDevTools()
    }
})

// 启动AI 数字人
ipcMain.on('start-avatar', () => {
    if (avatarWindow && !avatarWindow.isDestroyed()) {
        avatarWindow.destroy()
    }
    avatarWindow = createWindow()
})

// 停止AI 数字人
ipcMain.on('stop-avatar', () => {
    if (avatarWindow && !avatarWindow.isDestroyed()) {
        avatarWindow.destroy()
        avatarWindow = null
    }
})

// 获取AI 数字人状态
ipcMain.handle('get-avatar-status', () => {
    return avatarWindow && !avatarWindow.isDestroyed()
})

// 切换模型
ipcMain.on('switch-model', (event, modelPath) => {
    if (avatarWindow && !avatarWindow.isDestroyed()) {
        avatarWindow.webContents.send('switch-model', modelPath)
    }
})

// 预览表情
ipcMain.on('preview-expression', (event, exprName) => {
    if (avatarWindow && !avatarWindow.isDestroyed()) {
        avatarWindow.webContents.send('preview-expression', exprName)
    }
})

// 切换表情（开/关）
ipcMain.on('toggle-expression', (event, data) => {
    if (avatarWindow && !avatarWindow.isDestroyed()) {
        avatarWindow.webContents.send('toggle-expression', data)
    }
})

// 复位皮套位置
ipcMain.on('reset-avatar-position', () => {
    if (avatarWindow && !avatarWindow.isDestroyed()) {
        avatarWindow.webContents.send('reset-avatar-position')
    }
})

// 通知AI 数字人重新加载配置
ipcMain.on('reload-config', (event, data) => {
    if (avatarWindow && !avatarWindow.isDestroyed()) {
        avatarWindow.webContents.send('reload-config')
    }
})

// MCP 配置热重载（通知AI 数字人进程重新读取 MCP 配置）
ipcMain.handle('mcp-reload-config', () => {
    if (avatarWindow && !avatarWindow.isDestroyed()) {
        avatarWindow.webContents.send('mcp-reload-config')
    }
})

// === 情绪表情映射配置 ===
ipcMain.handle('scan-expressions', (event, characterPath) => {
    try {
        const results = []
        // 搜索1：expressions/ 子目录
        const exprDir = path.join(characterPath, 'expressions')
        if (fs.existsSync(exprDir)) {
            fs.readdirSync(exprDir)
                .filter(f => f.endsWith('.exp3.json'))
                .forEach(f => results.push({ name: path.basename(f, '.exp3.json'), file: 'expressions/' + f }))
        }
        // 搜索2：模型根目录下的 .exp3.json 文件
        if (fs.existsSync(characterPath)) {
            fs.readdirSync(characterPath)
                .filter(f => f.endsWith('.exp3.json'))
                .forEach(f => {
                    if (!results.some(r => r.name === path.basename(f, '.exp3.json'))) {
                        results.push({ name: path.basename(f, '.exp3.json'), file: f })
                    }
                })
        }
        return results
    } catch (e) {
        console.error('扫描表情目录失败:', e.message)
        return []
    }
})

ipcMain.handle('load-emotion-config', () => {
    try {
        const configPath = path.join(__dirname, 'emotion_expressions.json')
        if (!fs.existsSync(configPath)) return {}
        return JSON.parse(fs.readFileSync(configPath, 'utf8'))
    } catch (e) {
        console.error('加载情绪配置失败:', e.message)
        return {}
    }
})

ipcMain.handle('save-emotion-config', (event, data) => {
    try {
        const configPath = path.join(__dirname, 'emotion_expressions.json')
        fs.writeFileSync(configPath, JSON.stringify(data, null, 2), 'utf8')
        // 通知宠物窗口热重载
        if (avatarWindow && !avatarWindow.isDestroyed()) {
            avatarWindow.webContents.send('reload-emotion-config')
        }
        return true
    } catch (e) {
        console.error('保存情绪配置失败:', e.message)
        return false
    }
})

// === Skill 管理（已废除：技能由后端 Octop 管理，此处理器保留为空实现以免 webui 报错）===
ipcMain.handle('scan-skills', () => {
    try {
        const skillsDir = path.join(__dirname, 'skills')
        if (!fs.existsSync(skillsDir)) return []
        const skills = []
        for (const name of fs.readdirSync(skillsDir)) {
            const dir = path.join(skillsDir, name)
            if (!fs.statSync(dir).isDirectory()) continue
            const meta = { name, displayName: name, description: '', hasSoul: false, hasSkill: false }
            const soulPath = path.join(dir, 'SOUL.md')
            const skillPath = path.join(dir, 'SKILL.md')
            if (fs.existsSync(soulPath)) {
                meta.hasSoul = true
                const content = fs.readFileSync(soulPath, 'utf8')
                // 从第一行提取标题
                const titleMatch = content.match(/^#\s+(.+)/m)
                if (titleMatch) meta.displayName = titleMatch[1].trim()
                // 从第二行提取描述
                const descMatch = content.match(/^>\s*(.+)/m)
                if (descMatch) meta.description = descMatch[1].trim()
            }
            if (fs.existsSync(skillPath)) meta.hasSkill = true
            if (meta.hasSoul || meta.hasSkill) skills.push(meta)
        }
        return skills
    } catch (e) {
        console.error('扫描 Skill 失败:', e.message)
        return []
    }
})

ipcMain.handle('load-skill-content', (event, skillName) => {
    try {
        const dir = path.join(__dirname, 'skills', skillName)
        const result = {}
        const soulPath = path.join(dir, 'SOUL.md')
        const skillPath = path.join(dir, 'SKILL.md')
        if (fs.existsSync(soulPath)) result.soul = fs.readFileSync(soulPath, 'utf8')
        if (fs.existsSync(skillPath)) result.skill = fs.readFileSync(skillPath, 'utf8')
        return result
    } catch (e) {
        console.error('读取 Skill 内容失败:', e.message)
        return {}
    }
})

// 转发日志到控制面板
ipcMain.on('log-message', (event, logData) => {
    if (controlPanel && !controlPanel.isDestroyed()) {
        controlPanel.webContents.send('log-message', logData)
    }
})

// 截屏 IPC 已废弃（旧 DLC 插件体系，前端无调用，2026-10-05 清理）
