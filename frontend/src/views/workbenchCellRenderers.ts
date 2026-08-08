// AG Grid 单元格渲染工具。提供测试可访问的渲染逻辑，避免 <script setup> 限制。
import { h, type VNode } from 'vue'
import type { ICellRendererParams } from 'ag-grid-community'
import { ElButton } from 'element-plus'
import { Delete, RefreshRight, View, WarningFilled } from '@element-plus/icons-vue'

import type { RowItem } from '@/stores/rows'

// 收集 vnode 树中按钮的可见文本（包括渲染函数返回值与 title），供测试断言按钮文字。
export function collectCellLabels(node: unknown): string[] {
  const labels: string[] = []
  const visit = (value: unknown) => {
    if (!value) return
    if (Array.isArray(value)) { value.forEach(visit); return }
    if (typeof value !== 'object') return
    const obj = value as {
      children?: unknown
      props?: { title?: unknown; label?: unknown }
    }
    // 渲染函数：Element Plus 的 h(ElButton, props, () => '文字')
    if (typeof obj.children === 'function') {
      try {
        const rendered = (obj.children as () => unknown)()
        if (typeof rendered === 'string') labels.push(rendered)
        else if (Array.isArray(rendered)) rendered.forEach(visit)
        else visit(rendered)
      } catch (error) {
        // 渲染函数可能引用了组件作用域，调用失败时跳过。
        void error
      }
    }
    if (typeof obj.children === 'string') labels.push(obj.children)
    if (Array.isArray(obj.children)) obj.children.forEach(visit)
    if (typeof obj.props?.title === 'string') labels.push(obj.props.title)
    if (typeof obj.props?.label === 'string') labels.push(obj.props.label)
  }
  visit(node)
  return labels
}

type ActionHandlers = {
  runRow: (row: RowItem, force?: boolean) => Promise<unknown>
  openResults: (row: RowItem) => Promise<void>
  removeRow: (row: RowItem) => Promise<void>
  openErrorDetail: (row: RowItem) => void
}

// 纯函数：构造操作单元格，不依赖外部 store，便于测试断言。
export function buildActionCell(
  params: ICellRendererParams,
  handlers: ActionHandlers,
): VNode {
  const row = params.data as RowItem
  const buttons: VNode[] = []
  if (row.status === 'READY') {
    buttons.push(
      h(ElButton, {
        size: 'small',
        type: 'primary',
        onClick: () => handlers.runRow(row),
      }, '运行'),
    )
  }
  if (['NEEDS_REVIEW', 'COMPLETED', 'FAILED', 'CANCELED'].includes(row.status)) {
    buttons.push(
      h(ElButton, {
        size: 'small',
        icon: RefreshRight,
        title: '重新运行',
        onClick: () => handlers.runRow(row, true),
      }, '重新运行'),
    )
  }
  if (['NEEDS_REVIEW', 'COMPLETED'].includes(row.status)) {
    buttons.push(
      h(ElButton, {
        size: 'small',
        icon: View,
        title: '查看提示词',
        onClick: () => handlers.openResults(row),
      }, '查看提示词'),
    )
  }
  // 失败状态展示错误详情入口
  if (row.status === 'FAILED') {
    buttons.push(
      h(ElButton, {
        size: 'small',
        icon: WarningFilled,
        title: '查看失败原因',
        type: 'danger',
        onClick: () => handlers.openErrorDetail(row),
      }, '查看错误'),
    )
  }
  buttons.push(
    h(ElButton, {
      size: 'small',
      icon: Delete,
      title: '删除任务',
      type: 'danger',
      plain: true,
      onClick: () => handlers.removeRow(row),
    }, '删除任务'),
  )
  return h('div', { class: 'action-cell' }, buttons)
}

export { Delete, RefreshRight, View, WarningFilled }
