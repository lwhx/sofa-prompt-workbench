import { ref, onMounted, onUnmounted } from 'vue'
import type { RowItem } from '@/stores/rows'

/** 进行中状态集合：这些状态的任务完成时需要通知。 */
const ACTIVE_STATES = new Set([
  'QUEUED', 'ANALYZING', 'VALIDATING', 'REPAIRING',
  'DEBOUNCING', 'CANCELING', 'UPLOADING',
])

/** 值得通知的终态集合。 */
const NOTIFY_STATES = new Set(['COMPLETED', 'FAILED', 'NEEDS_REVIEW'])

/** 终态对应的中文标签。 */
const STATUS_LABELS: Record<string, string> = {
  COMPLETED: '已完成',
  FAILED: '失败',
  NEEDS_REVIEW: '待审核',
}

/** 状态转换检测结果。 */
export interface TaskTransition {
  /** 任务行 ID。 */
  id: string
  /** 任务名称。 */
  name: string
  /** 新状态。 */
  status: string
}

/**
 * 纯函数：检测从进行中到终态的转换。
 * @param prevStatusMap - 上一次的状态快照（rowId → status）。
 * @param currentRows - 当前任务行列表。
 * @returns 发生了完成转换的任务列表。
 */
export function detectCompletedTransitions(
  prevStatusMap: Map<string, string>,
  currentRows: RowItem[],
): TaskTransition[] {
  const transitions: TaskTransition[] = []
  for (const row of currentRows) {
    const prevStatus = prevStatusMap.get(row.id)
    /** 仅当之前处于进行中、当前已到达终态时才通知。 */
    if (prevStatus && ACTIVE_STATES.has(prevStatus) && NOTIFY_STATES.has(row.status)) {
      transitions.push({ id: row.id, name: row.name, status: row.status })
    }
  }
  return transitions
}

/**
 * 任务完成通知 composable。
 *
 * 同时支持两种通知方式：
 * 1. 浏览器桌面通知（Notification API，需用户授权）。
 * 2. 标签页标题闪烁（无需授权，用户切换标签页时可感知）。
 *
 * @returns 通知控制接口。
 */
export function useTaskNotifier() {
  /** 是否启用通知。 */
  const enabled = ref(false)
  /** 桌面通知权限状态。 */
  const permission = ref<NotificationPermission>('default')
  /** 上一次的状态快照。 */
  const prevStatusMap = ref<Map<string, string>>(new Map())
  /** 原始标签页标题。 */
  const originalTitle = ref('')
  /** 标题闪烁定时器。 */
  let flashTimer: ReturnType<typeof globalThis.setInterval> | null = null
  /** 闪烁切换标志。 */
  let flashToggle = false

  /**
   * 请求桌面通知权限。
   */
  async function requestPermission(): Promise<void> {
    if (!('Notification' in globalThis)) return
    if (Notification.permission === 'granted') {
      permission.value = 'granted'
      return
    }
    if (Notification.permission !== 'denied') {
      const result = await Notification.requestPermission()
      permission.value = result
    } else {
      permission.value = 'denied'
    }
  }

  /**
   * 恢复标签页标题。
   */
  function stopTitleFlash(): void {
    if (flashTimer) {
      globalThis.clearInterval(flashTimer)
      flashTimer = null
    }
    if (originalTitle.value) {
      document.title = originalTitle.value
    }
  }

  /**
   * 开始标签页标题闪烁。
   * @param count - 未查看的完成数量。
   */
  function startTitleFlash(count: number): void {
    /** 记录原始标题（仅首次）。 */
    if (!originalTitle.value) {
      originalTitle.value = document.title
    }
    if (flashTimer) return
    flashToggle = false
    flashTimer = globalThis.setInterval(() => {
      flashToggle = !flashToggle
      document.title = flashToggle
        ? `🔔 ${count} 个任务完成`
        : originalTitle.value
    }, 1000)
  }

  /**
   * 发送桌面通知。
   * @param transitions - 完成转换的任务列表。
   */
  function sendDesktopNotification(transitions: TaskTransition[]): void {
    if (!('Notification' in globalThis) || Notification.permission !== 'granted') return
    const count = transitions.length
    const first = transitions[0]
    const title = count === 1
      ? `${first.name} ${STATUS_LABELS[first.status] ?? first.status}`
      : `${count} 个任务已完成`
    const body = transitions
      .slice(0, 3)
      .map((t) => `${t.name} → ${STATUS_LABELS[t.status] ?? t.status}`)
      .join('\n')
    const notification = new Notification(title, {
      body: count > 3 ? `${body}\n…还有 ${count - 3} 个` : body,
      icon: '/favicon.ico',
      tag: 'task-completion',
    })
    /** 点击通知聚焦窗口。 */
    notification.onclick = () => {
      globalThis.focus()
      notification.close()
    }
  }

  /**
   * 检查任务列表并触发通知。
   * 应在每次 fetchRows 后调用。
   * @param rows - 最新任务行列表。
   */
  function checkAndNotify(rows: RowItem[]): void {
    if (!enabled.value) {
      prevStatusMap.value = buildStatusMap(rows)
      return
    }
    const transitions = detectCompletedTransitions(prevStatusMap.value, rows)
    if (transitions.length > 0) {
      sendDesktopNotification(transitions)
      startTitleFlash(transitions.length)
    }
    prevStatusMap.value = buildStatusMap(rows)
  }

  /**
   * 用户查看页面后停止标题闪烁。
   */
  function onWindowFocus(): void {
    stopTitleFlash()
  }

  onMounted(() => {
    originalTitle.value = document.title
    globalThis.addEventListener('focus', onWindowFocus)
  })

  onUnmounted(() => {
    stopTitleFlash()
    globalThis.removeEventListener('focus', onWindowFocus)
  })

  return {
    enabled,
    permission,
    requestPermission,
    checkAndNotify,
    stopTitleFlash,
  }
}

/**
 * 构建行状态快照。
 * @param rows - 任务行列表。
 * @returns rowId → status 的 Map。
 */
function buildStatusMap(rows: RowItem[]): Map<string, string> {
  const map = new Map<string, string>()
  for (const row of rows) {
    map.set(row.id, row.status)
  }
  return map
}
