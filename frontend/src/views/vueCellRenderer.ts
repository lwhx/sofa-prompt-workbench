/**
 * AG Grid class-based Vue 单元格渲染器。
 *
 * 解决三个问题：
 * 1. AG Grid 刷新行数据时 Vue 组件不响应更新 —— 通过 ref 包裹 data，refresh() 时更新触发响应式重渲染。
 * 2. Vue 应用内存泄漏 —— 实现 destroy() 生命周期，AG Grid 销毁单元格时正确卸载。
 * 3. 粘贴事件被 AG Grid 焦点拦截 —— 提供 resolvePasteTarget 纯函数，配合 WorkbenchView 全局 paste 监听使用。
 */
import { createApp, ref, type App, type Ref, type VNode } from 'vue'
import type { ICellRendererParams } from 'ag-grid-community'

/**
 * 创建 AG Grid class-based Vue 单元格渲染器类。
 *
 * @param renderer - 渲染函数，接收 (data, params)，返回 VNode。
 * @returns AG Grid 兼容的 class-based renderer 类，包含 init/getGui/refresh/destroy。
 */
export function createVueCellRenderer(
  renderer: (data: unknown, params: ICellRendererParams) => VNode,
) {
  return class VueCellRenderer {
    /** 根 DOM 元素，AG Grid 通过 getGui() 获取并挂载 */
    private gui!: HTMLElement
    /** Vue 应用实例，destroy 时卸载 */
    private app: App | null = null
    /** 原始 params，用于传递 colDef 等非 data 信息 */
    private params!: ICellRendererParams
    /** 响应式数据引用，refresh 时更新以触发 Vue 重新渲染 */
    private dataRef!: Ref<unknown>
    /** 强制刷新计数器，refresh 时递增以确保 render 重新执行 */
    private tick!: Ref<number>

    /**
     * AG Grid 初始化回调。
     * @param params - 单元格参数，包含 data、colDef 等。
     */
    init(params: ICellRendererParams) {
      this.params = params
      this.dataRef = ref(params.data)
      this.tick = ref(0)
      this.gui = document.createElement('div')
      this.gui.style.height = '100%'
      this.gui.style.display = 'flex'
      this.gui.style.alignItems = 'center'
      this.gui.style.padding = '4px'
      this.app = createApp({
        render: () => {
          // 读取 tick 建立响应式依赖，确保 force refresh 时重新执行
          void this.tick.value
          return renderer(this.dataRef.value, this.params)
        },
      })
      this.app.mount(this.gui)
    }

    /**
     * 返回单元格 DOM 根元素。
     * @returns HTMLElement 根元素。
     */
    getGui(): HTMLElement {
      return this.gui
    }

    /**
     * AG Grid 刷新回调。
     * 更新响应式数据引用，Vue 自动触发重新渲染。
     * @param params - 新的单元格参数。
     * @returns true 表示刷新成功。
     */
    refresh(params: ICellRendererParams): boolean {
      this.params = params
      this.dataRef.value = params.data
      // 递增 tick 强制 Vue render 重新执行，即使 data 引用未变
      this.tick.value++
      return true
    }

    /**
     * AG Grid 销毁回调。
     * 卸载 Vue 应用，防止内存泄漏。
     */
    destroy() {
      this.app?.unmount()
      this.app = null
    }
  }
}

/** 粘贴目标的列 ID 到资产类型的映射 */
const PASTE_COL_MAP: Record<string, 'scene_reference' | 'sofa_product'> = {
  scene_asset: 'scene_reference',
  sofa_asset: 'sofa_product',
}

/** 粘贴路由结果 */
export interface PasteTarget {
  /** 资产类型：场景参考图或沙发白底图 */
  kind: 'scene_reference' | 'sofa_product'
  /** 粘贴的图片文件 */
  file: File
  /** 目标行 ID */
  rowId: string
}

/**
 * 从剪贴板文件列表和 AG Grid 焦点信息中推导粘贴目标。
 *
 * 纯函数，不依赖 DOM 或 AG Grid 实例，便于单元测试。
 *
 * @param files - 剪贴板中的文件列表。
 * @param focusedCell - 当前焦点单元格信息（colId + rowId），无焦点时传 null。
 * @returns 匹配到图片列时返回 PasteTarget，否则返回 null。
 */
export function resolvePasteTarget(
  files: File[],
  focusedCell: { colId: string; rowId: string } | null,
): PasteTarget | null {
  if (!focusedCell) return null
  const kind = PASTE_COL_MAP[focusedCell.colId]
  if (!kind) return null
  const file = files.find(f => f.type.startsWith('image/'))
  if (!file) return null
  return { kind, file, rowId: focusedCell.rowId }
}
