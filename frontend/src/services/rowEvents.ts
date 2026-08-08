/** SSE 重连退避时长，避免连接异常时频繁请求。 */
const RECONNECT_DELAYS = [1000, 2000, 5000, 10000] as const

/** SSE 连接状态回调参数。 */
export interface RowEventsStatus {
  /** 当前是否已连接。 */
  connected: boolean
  /** 当前重连尝试次数（0 表示首次连接或已恢复）。 */
  reconnectAttempt: number
}

/**
 * 启动任务行失效事件监听。
 * @param onInvalidate - 收到 invalidate 事件后的回调。
 * @param onStatusChange - 连接状态变化时的回调（可选）。
 * @returns 停止监听并清理连接与重连定时器的方法。
 */
export function startRowEvents(
  onInvalidate: () => void,
  onStatusChange?: (status: RowEventsStatus) => void,
): () => void {
  /** 当前 SSE 连接。 */
  let source: EventSource | null = null
  /** 当前重连定时器。 */
  let reconnectTimer: ReturnType<typeof globalThis.setTimeout> | null = null
  /** 当前退避序号。 */
  let reconnectAttempt = 0
  /** 服务是否已停止。 */
  let stopped = false

  /** 通知连接状态变化。 */
  function notifyStatus(): void {
    onStatusChange?.({
      connected: source !== null && reconnectTimer === null,
      reconnectAttempt,
    })
  }

  /** 建立 SSE 连接并注册事件。 */
  function connect(): void {
    if (stopped) return

    source = new EventSource('/api/v1/events')
    source.addEventListener('open', () => {
      reconnectAttempt = 0
      notifyStatus()
    })
    source.addEventListener('invalidate', onInvalidate)
    source.addEventListener('error', () => {
      source?.close()
      source = null
      notifyStatus()
      if (stopped || reconnectTimer) return

      /** 本次重连等待时长，达到上限后保持固定间隔。 */
      const delay = RECONNECT_DELAYS[Math.min(reconnectAttempt, RECONNECT_DELAYS.length - 1)]
      reconnectAttempt += 1
      reconnectTimer = globalThis.setTimeout(() => {
        reconnectTimer = null
        connect()
      }, delay)
    })
  }

  /** 停止监听并释放全部资源。 */
  function stop(): void {
    stopped = true
    source?.close()
    source = null
    if (reconnectTimer) {
      globalThis.clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  connect()
  return stop
}
