import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { startRowEvents } from '@/services/rowEvents'

/** 测试用 EventSource，允许主动触发浏览器事件。 */
class MockEventSource {
  /** 已创建的连接实例。 */
  static instances: MockEventSource[] = []
  /** 当前连接地址。 */
  readonly url: string
  /** 连接是否已关闭。 */
  closed = false
  /** 按事件名保存的监听器。 */
  private readonly listeners = new Map<string, EventListener[]>()

  /**
   * 创建测试连接。
   * @param url - SSE 地址。
   */
  constructor(url: string | URL) {
    this.url = String(url)
    MockEventSource.instances.push(this)
  }

  /**
   * 注册事件监听器。
   * @param type - 事件类型。
   * @param listener - 事件回调。
   */
  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    /** 标准化后的事件回调。 */
    const callback = typeof listener === 'function' ? listener : listener.handleEvent.bind(listener)
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), callback])
  }

  /** 关闭当前连接。 */
  close(): void {
    this.closed = true
  }

  /**
   * 主动触发指定事件。
   * @param type - 要触发的事件类型。
   */
  emit(type: string): void {
    for (const listener of this.listeners.get(type) ?? []) listener(new Event(type))
  }
}

describe('rowEvents', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('收到 invalidate 时调用回调', () => {
    /** 失效事件回调。 */
    const onInvalidate = vi.fn()
    /** 停止 SSE 的清理方法。 */
    const stop = startRowEvents(onInvalidate)

    expect(MockEventSource.instances[0]?.url).toBe('/api/v1/events')
    MockEventSource.instances[0]?.emit('invalidate')

    expect(onInvalidate).toHaveBeenCalledOnce()
    stop()
  })

  it('连接错误时关闭并有限退避重连，stop 后不再重连', () => {
    /** 停止 SSE 的清理方法。 */
    const stop = startRowEvents(vi.fn())
    /** 首次建立的连接。 */
    const first = MockEventSource.instances[0]

    first?.emit('error')
    expect(first?.closed).toBe(true)
    expect(MockEventSource.instances).toHaveLength(1)

    vi.advanceTimersByTime(999)
    expect(MockEventSource.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(MockEventSource.instances).toHaveLength(2)

    MockEventSource.instances[1]?.emit('error')
    stop()
    vi.runAllTimers()

    expect(MockEventSource.instances).toHaveLength(2)
    expect(MockEventSource.instances[1]?.closed).toBe(true)
  })
})
