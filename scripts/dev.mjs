/**
 * 统一进程管理脚本 — 同时启动前端、后端 API、Dispatcher，
 * 进程崩溃时自动重启（带指数退避），Ctrl+C 优雅退出全部服务。
 *
 * 用法: node scripts/dev.mjs
 * 无外部依赖，仅使用 Node.js 内置模块。
 */
import { spawn } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { platform } from 'node:os'
import { resolve } from 'node:path'

const IS_WIN = platform() === 'win32'
const SHELL = IS_WIN ? { shell: 'powershell.exe' } : { shell: true }

/**
 * 从项目根目录的 .env 文件加载指定前缀的键到环境变量。
 * 仅覆盖代码未显式注入的键（OneImg/AI 等需要从 .env 读取）。
 * 不读取 APP_ENV/SESSION_SECRET 等敏感键，避免覆盖代码侧的 dev 兜底。
 *
 * @param {string} rootDir - 项目根目录绝对路径。
 * @param {string[]} keys - 要读取的键名列表。
 * @returns {Record<string, string>} 解析出的环境变量。
 */
function loadEnvKeys(rootDir, keys) {
  const envPath = resolve(rootDir, '.env')
  /** @type {Record<string, string>} */
  const result = {}
  let content
  try {
    content = readFileSync(envPath, 'utf8')
  } catch {
    return result
  }
  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const eq = trimmed.indexOf('=')
    if (eq <= 0) continue
    const key = trimmed.slice(0, eq).trim()
    if (!keys.includes(key)) continue
    let value = trimmed.slice(eq + 1).trim()
    // 去掉包裹引号
    if ((value.startsWith('"') && value.endsWith('"'))
      || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1)
    }
    result[key] = value
  }
  return result
}

/** 服务定义 */
const SERVICES = [
  {
    name: 'API',
    color: '\x1b[36m', // cyan
    command: 'uv',
    args: ['run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'],
    cwd: 'backend',
    env: {},
    readyMarker: 'Application startup complete',
  },
  {
    name: 'Dispatcher',
    color: '\x1b[35m', // magenta
    command: 'uv',
    args: ['run', 'python', '-m', 'app.services.dispatcher'],
    cwd: 'backend',
    env: { LOCAL_INLINE_WORKER: 'true' },
    readyMarker: null,
  },
  {
    name: 'Frontend',
    color: '\x1b[32m', // green
    command: 'npm',
    args: ['run', 'dev'],
    cwd: 'frontend',
    env: {},
    readyMarker: 'ready in',
  },
]

const RESET = '\x1b[0m'
const BOLD = '\x1b[1m'
const YELLOW = '\x1b[33m'
const RED = '\x1b[31m'

/** 最大重启退避秒数 */
const MAX_BACKOFF_SEC = 30
/** 连续快速崩溃次数超过此阈值后停止重启（防止死循环） */
const MAX_RAPID_CRASHES = 5

/** 运行中的进程映射 */
const procs = new Map()
/** 每个服务的连续快速崩溃计数 */
const rapidCrashCounts = new Map()
/** 是否正在关闭 */
let shuttingDown = false

/**
 * 为服务输出带前缀和颜色的日志行。
 * @param {string} name - 服务名称。
 * @param {string} color - ANSI 颜色码。
 * @param {string} line - 日志内容。
 */
function log(name, color, line) {
  for (const l of String(line).split(/\r?\n/)) {
    if (l.trim()) {
      process.stdout.write(`${color}[${name}]${RESET} ${l}\n`)
    }
  }
}

/**
 * 启动单个服务，监听输出和退出事件。
 * 崩溃后自动重启（带指数退避）。
 * @param {typeof SERVICES[number]} svc - 服务定义。
 * @param {number} [delaySec=0] - 延迟启动秒数。
 */
function startService(svc, delaySec = 0) {
  if (shuttingDown) return

  const run = () => {
    if (shuttingDown) return

    const startTime = Date.now()
    log(svc.name, svc.color, `${BOLD}启动中...${RESET}`)

    const env = { ...process.env, ...svc.env }
    const proc = spawn(svc.command, svc.args, {
      cwd: svc.cwd,
      env,
      stdio: ['ignore', 'pipe', 'pipe'],
      ...SHELL,
    })

    procs.set(svc.name, proc)

    let stdoutBuf = ''
    proc.stdout.on('data', (chunk) => {
      stdoutBuf += chunk.toString()
      let idx
      while ((idx = stdoutBuf.indexOf('\n')) !== -1) {
        const line = stdoutBuf.slice(0, idx)
        stdoutBuf = stdoutBuf.slice(idx + 1)
        log(svc.name, svc.color, line)
      }
    })

    let stderrBuf = ''
    proc.stderr.on('data', (chunk) => {
      stderrBuf += chunk.toString()
      let idx
      while ((idx = stderrBuf.indexOf('\n')) !== -1) {
        const line = stderrBuf.slice(0, idx)
        stderrBuf = stderrBuf.slice(idx + 1)
        log(svc.name, svc.color, line)
      }
    })

    proc.on('exit', (code, signal) => {
      procs.delete(svc.name)

      if (shuttingDown) return

      const uptimeSec = Math.round((Date.now() - startTime) / 1000)
      const isRapidCrash = uptimeSec < 5

      if (isRapidCrash) {
        const count = (rapidCrashCounts.get(svc.name) ?? 0) + 1
        rapidCrashCounts.set(svc.name, count)

        if (count >= MAX_RAPID_CRASHES) {
          log(svc.name, RED, `${BOLD}连续 ${count} 次在 5 秒内崩溃，停止重启。${RESET}`)
          log(svc.name, RED, '请检查配置或日志，修复后重新运行 npm run dev。')
          checkAllStopped()
          return
        }
      } else {
        // 运行超过 5 秒后重置计数
        rapidCrashCounts.set(svc.name, 0)
      }

      const reason = signal ? `信号 ${signal}` : `退出码 ${code}`
      log(svc.name, YELLOW, `进程结束（${reason}，运行 ${uptimeSec}秒）`)

      // 指数退避重启
      const crashes = rapidCrashCounts.get(svc.name) ?? 0
      const backoff = Math.min(MAX_BACKOFF_SEC, 2 ** crashes)
      log(svc.name, YELLOW, `${backoff}秒后自动重启...`)
      setTimeout(() => startService(svc), backoff * 1000)
    })
  }

  if (delaySec > 0) {
    log(svc.name, svc.color, `等待 ${delaySec}秒后启动...`)
    setTimeout(run, delaySec * 1000)
  } else {
    run()
  }
}

/** 检查是否所有服务都已停止，是则退出主进程。 */
function checkAllStopped() {
  if (procs.size === 0 && shuttingDown) {
    process.exit(0)
  }
  // 所有服务因崩溃停止（非手动 Ctrl+C）
  const allDead = SERVICES.every((s) => !procs.has(s.name))
  if (allDead && !shuttingDown) {
    const allGaveUp = SERVICES.every(
      (s) => (rapidCrashCounts.get(s.name) ?? 0) >= MAX_RAPID_CRASHES,
    )
    if (allGaveUp) {
      log('SYSTEM', RED, `${BOLD}所有服务均已停止。${RESET}`)
      process.exit(1)
    }
  }
}

/**
 * 优雅关闭所有服务。
 * 先发 Ctrl+C（Windows 下用 taskkill），3 秒后强制 kill。
 */
function shutdown() {
  if (shuttingDown) return
  shuttingDown = true
  process.stdout.write(`\n${YELLOW}${BOLD}正在停止所有服务...${RESET}\n`)

  let stopped = 0
  const total = procs.size

  if (total === 0) {
    process.exit(0)
    return
  }

  for (const [name, proc] of procs) {
    log(name, YELLOW, '正在停止...')

    const timer = setTimeout(() => {
      if (!proc.killed) {
        log(name, RED, '强制终止')
        proc.kill('SIGKILL')
      }
    }, 3000)

    proc.on('exit', () => {
      clearTimeout(timer)
      log(name, YELLOW, '已停止')
      stopped++
      if (stopped >= total) {
        process.exit(0)
      }
    })

    // Windows 下 send SIGINT 不生效，用 taskkill 发送 Ctrl+C
    if (IS_WIN) {
      try {
        // /T 同时终止子进程树
        spawn('taskkill', ['/PID', String(proc.pid), '/T'], { shell: true })
      } catch {
        proc.kill('SIGTERM')
      }
    } else {
      proc.kill('SIGTERM')
    }
  }
}

// ── 启动 ────────────────────────────────────────────
// 把根目录 .env 中的 OneImg / AI 配置注入到 Python 子进程。
// 代码侧保留 APP_ENV=development 等 dev 兜底，避免触发生产校验。
const PROJECT_ROOT = resolve(process.cwd())
const ENV_KEYS_TO_FORWARD = [
  'ONEIMG_BASE_URL', 'ONEIMG_API_TOKEN', 'ONEIMG_TIMEOUT_SECONDS',
  'AI_PROVIDER', 'AI_BASE_URL', 'AI_CHAT_COMPLETIONS_PATH',
  'AI_API_KEY', 'AI_MODEL', 'AI_TIMEOUT_SECONDS',
]
const sharedEnv = loadEnvKeys(PROJECT_ROOT, ENV_KEYS_TO_FORWARD)
for (const svc of SERVICES) {
  if (svc.name === 'Frontend') continue
  svc.env = { ...sharedEnv, ...svc.env }
}

process.stdout.write(
  `${BOLD}═══════════════════════════════════════════════${RESET}\n` +
  `${BOLD}  Sofa Prompt Workbench — 统一开发服务${RESET}\n` +
  `${BOLD}═══════════════════════════════════════════════${RESET}\n` +
  `  前端:    http://127.0.0.1:5173/\n` +
  `  API:     http://127.0.0.1:8000/\n` +
  `  API文档: http://127.0.0.1:8000/api/docs\n` +
  `${BOLD}  按 Ctrl+C 停止全部服务${RESET}\n\n`,
)

// API 先启动（Dispatcher 和 Frontend 依赖数据库就绪）
for (const svc of SERVICES) {
  startService(svc)
}

process.on('SIGINT', shutdown)
process.on('SIGTERM', shutdown)
