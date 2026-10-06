const { app, BrowserWindow, ipcMain, screen } = require('electron')
const path = require('path')
const fs = require('fs')
const http = require('http')
const { spawn } = require('child_process')

const configPath = path.join(app.getAppPath(), 'config.json')

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

function ensureBackend() {
    const origin = backendOrigin()
    return checkBackendReady(origin).then(async (alive) => {
        if (alive) {
            console.log('后端已就绪: ' + origin)
            return { started: false }
        }
        console.log('后端未就绪，自动拉起 uvicorn ...')
        const backendDir = path.join(__dirname, '..', '..', 'backend')
        const venvPython = path.join(backendDir, '.venv', 'bin', 'python')
        const python = fs.existsSync(venvPython) ? venvPython : 'python3'
        const port = new URL(origin).port || '8000'
        // 后端日志写 .logs/backend.log（文件 fd，非 pipe）：
        // ① uvicorn 访问日志不刷壳日志；② 壳退出后 pipe 断开不再 SIGPIPE 误杀常驻后端
        const backendLog = path.join(__dirname, '..', '..', '.logs', 'backend.log')
        try { fs.mkdirSync(path.dirname(backendLog), { recursive: true }) } catch (e) {}
        const logFd = fs.openSync(backendLog, 'a')
        const child = spawn(
            python,
            ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', port],
            { cwd: backendDir, stdio: ['ignore', logFd, logFd], env: process.env, detached: true }
        )
        child.unref() // 脱离壳进程组：壳退出后后端保持常驻
        child.on('error', (err) => console.error('[backend] 启动失败: ' + err.message))
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

function createWindow() {
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
            contextIsolation: false
        },
        resizable: true,
        movable: true,
        skipTaskbar: true
    })

    win.setAlwaysOnTop(true, 'screen-saver')
    win.setMenu(null)
    win.setIgnoreMouseEvents(true, { forward: true })
    win.loadFile('index.html')

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

app.whenReady().then(() => {
    // 先确保后端就绪（未启动则自动拉起），再创建窗口——控制面板加载依赖后端
    ensureBackend().finally(() => {
        let initialConfig = {}
        try { initialConfig = JSON.parse(fs.readFileSync(configPath, 'utf8')) } catch (e) {}
        const petEnabled = (initialConfig.ui || {}).avatar_enabled !== false // 缺省开

        if (petEnabled) {
            avatarWindow = createWindow()
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
    }) // ensureBackend().finally 回调结束
})

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
