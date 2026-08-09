import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRowsStore, type RowItem } from '@/stores/rows'

/** SSE 生命周期 mock，避免单元测试建立真实连接。 */
const stopRowEvents = vi.fn()
vi.mock('@/services/rowEvents', () => ({
  startRowEvents: vi.fn(() => stopRowEvents),
}))

// Mock axios
vi.mock('@/services/api', () => ({
  api: {
    get: vi.fn().mockResolvedValue({ data: { data: [] } }),
    post: vi.fn().mockResolvedValue({ status: 201 }),
  },
  extractApiError: (_error: unknown, fallback: string) => fallback,
}))

// Mock Element Plus
import { ElButton, ElDialog, ElTable, ElTableColumn, ElTag, ElTooltip } from 'element-plus'

/** 创建满足任务行类型的测试数据。 */
function createRow(id: string, status: string): RowItem {
  return {
    id, name: id, status, row_revision: 1, results_count: 0,
    sort_key: 1, auto_run: false, created_at: null,
  }
}

describe('WorkbenchView', () => {
  it('renders toolbar actions and exposes AG Grid multi-row selection config', async () => {
    setActivePinia(createPinia())
    const WorkbenchView = (await import('@/views/WorkbenchView.vue')).default
    const wrapper = mount(WorkbenchView, {
      global: {
        stubs: {
          ElButton, ElDialog, ElTable, ElTableColumn, ElTag, ElTooltip,
          AgGridVue: { template: '<div />' },
        },
        directives: { loading: () => undefined },
      },
    })

    expect(wrapper.text()).toContain('新建任务')
    expect(wrapper.text()).toContain('刷新')
    expect(wrapper.text()).toContain('批量运行')
    expect(wrapper.text()).toContain('批量删除')
    expect(wrapper.text()).toContain('回收站')
    expect(wrapper.text()).toContain('导出 JSON')
    expect(wrapper.text()).toContain('导出 CSV')
    expect(wrapper.text()).toContain('查询')
    expect(wrapper.text()).toContain('重置')
    expect((wrapper.vm as unknown as { gridOptions: { rowSelection: { mode: string }; selectionColumnDef: object } }).gridOptions)
      .toMatchObject({ rowSelection: { mode: 'multiRow', checkboxes: true }, selectionColumnDef: { pinned: 'left' } })
    expect(wrapper.text()).toContain('全部任务')
    expect(wrapper.text()).toContain('处理中')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.find('.workbench-summary').exists()).toBe(true)
  })

  it('refresh button reflects store loading and triggers fetchRows', async () => {
    setActivePinia(createPinia())
    /** 当前任务行 store。 */
    const store = useRowsStore()
    /** 行刷新方法 mock。 */
    const fetchRows = vi.spyOn(store, 'fetchRows').mockResolvedValue()
    const WorkbenchView = (await import('@/views/WorkbenchView.vue')).default
    const wrapper = mount(WorkbenchView, {
      global: {
        stubs: {
          ElButton: { inheritAttrs: false, props: ['loading'], emits: ['click'], template: '<button :data-loading="loading" @click="$emit(\'click\')"><slot /></button>' },
          AgGridVue: { template: '<div />' },
          PromptResultDialog: { template: '<div />' },
          AssetLibraryDialog: { template: '<div />' },
          ElDialog: { template: '<div><slot /></div>' },
          ElTooltip: { template: '<div><slot /></div>' },
        },
      },
    })
    fetchRows.mockClear()
    store.loading = true
    await nextTick()

    /** 工具栏中的刷新按钮。 */
    const refreshButton = wrapper.findAll('button').find(button => button.text() === '刷新')
    expect(refreshButton?.attributes('data-loading')).toBe('true')

    /** 点击前的刷新调用次数。 */
    const callsBeforeClick = fetchRows.mock.calls.length
    await refreshButton?.trigger('click')
    expect(fetchRows).toHaveBeenCalledTimes(callsBeforeClick + 1)
  })

  it('runs only runnable selected rows and confirms batch deletion once', async () => {
    setActivePinia(createPinia())
    /** 当前任务行 store。 */
    const store = useRowsStore()
    vi.spyOn(store, 'fetchRows').mockResolvedValue()
    /** 行运行方法 mock。 */
    const runRow = vi.spyOn(store, 'runRow').mockResolvedValue()
    /** 行删除方法 mock。 */
    const deleteRow = vi.spyOn(store, 'deleteRow').mockResolvedValue()
    /** 批量删除确认框 mock。 */
    const confirm = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as never)
    const WorkbenchView = (await import('@/views/WorkbenchView.vue')).default
    const wrapper = mount(WorkbenchView, {
      global: {
        stubs: {
          ElButton: { props: ['disabled'], template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
          AgGridVue: { template: '<div />' },
          PromptResultDialog: { template: '<div />' },
          AssetLibraryDialog: { template: '<div />' },
          ElDialog: { template: '<div><slot /></div>' },
          ElTooltip: { template: '<div><slot /></div>' },
        },
      },
    })
    /** 组件暴露的测试上下文。 */
    const view = wrapper.vm as unknown as {
      selectedRows: RowItem[]
      runSelectedRows: () => Promise<void>
      deleteSelectedRows: () => Promise<void>
    }
    view.selectedRows = [createRow('ready', 'READY'), createRow('draft', 'DRAFT'), createRow('failed', 'FAILED')]
    await view.runSelectedRows()

    expect(runRow).toHaveBeenCalledTimes(2)
    expect(runRow).toHaveBeenNthCalledWith(1, expect.objectContaining({ id: 'ready' }), false)
    expect(runRow).toHaveBeenNthCalledWith(2, expect.objectContaining({ id: 'failed' }), true)

    await view.deleteSelectedRows()
    expect(confirm).toHaveBeenCalledOnce()
    expect(deleteRow).toHaveBeenCalledTimes(3)
  })

  it('only opens result dialog for rows with completed results', async () => {
    setActivePinia(createPinia())
    const WorkbenchView = (await import('@/views/WorkbenchView.vue')).default
    let attachedHandlers: Record<string, (...args: unknown[]) => void> = {}
    const Stub = {
      props: ['gridOptions', 'rowData'],
      emits: ['grid-ready', 'row-double-clicked', 'cell-value-changed'],
      template: '<div />',
      mounted(this: { $emit: (event: string, payload: unknown) => void }) {
        attachedHandlers = {
          'grid-ready': (payload: unknown) => this.$emit('grid-ready', payload),
          'row-double-clicked': (payload: unknown) => this.$emit('row-double-clicked', payload),
          'cell-value-changed': (payload: unknown) => this.$emit('cell-value-changed', payload),
        }
      },
    }
    const wrapper = mount(WorkbenchView, {
      global: {
        stubs: {
          ElButton, ElDialog, ElTable, ElTableColumn, ElTag, ElTooltip,
          AgGridVue: Stub,
          PromptResultDialog: { template: '<div />' },
        },
        directives: { loading: () => undefined },
      },
    })
    attachedHandlers['grid-ready']?.({ api: { setGridOption: () => undefined, sizeColumnsToFit: () => undefined } })

    const emitRow = (data: { id: string; name: string; status: string; row_revision: number }, colId = 'name') => {
      attachedHandlers['row-double-clicked']?.({
        data,
        column: { getColId: () => colId },
        api: {
          getRowNode: () => ({ rowIndex: 0 }),
          startEditingCell: () => undefined,
        },
      })
    }

    emitRow({ id: 'r1', name: '样品', status: 'DRAFT', row_revision: 1 })
    expect((wrapper.vm as unknown as { resultOpen: boolean }).resultOpen).toBe(false)

    emitRow({ id: 'r2', name: '失败', status: 'FAILED', row_revision: 2 })
    expect((wrapper.vm as unknown as { resultOpen: boolean }).resultOpen).toBe(false)

    emitRow({ id: 'r3', name: '待审核', status: 'NEEDS_REVIEW', row_revision: 3 }, 'status')
    expect((wrapper.vm as unknown as { resultOpen: boolean }).resultOpen).toBe(true)
  })

  it('clears old result data before loading another row', async () => {
    setActivePinia(createPinia())
    const store = useRowsStore()
    vi.spyOn(store, 'fetchRows').mockResolvedValue()
    let resolveResults!: (results: Awaited<ReturnType<typeof store.fetchResults>>) => void
    vi.spyOn(store, 'fetchResults').mockReturnValue(new Promise(resolve => { resolveResults = resolve }))
    const WorkbenchView = (await import('@/views/WorkbenchView.vue')).default
    const wrapper = mount(WorkbenchView, {
      global: {
        stubs: {
          ElButton, AgGridVue: { template: '<div />' }, PromptResultDialog: { template: '<div />' },
          AssetLibraryDialog: { template: '<div />' }, ElDialog: { template: '<div><slot /></div>' },
          ElTooltip: { template: '<div><slot /></div>' },
        },
      },
    })
    const view = wrapper.vm as unknown as {
      resultItems: Awaited<ReturnType<typeof store.fetchResults>>
      openResults: (row: RowItem) => Promise<void>
    }
    view.resultItems = [{
      id: 'old', version: 1, positive_prompt: '旧结果', negative_prompt: '', review_status: 'PASSED',
      review: {}, warnings: [], is_stale: false,
    }]

    const loadingPromise = view.openResults(createRow('new-row', 'COMPLETED'))
    await nextTick()
    expect(view.resultItems).toEqual([])
    resolveResults([])
    await loadingPromise
  })

  it('reports a rejected drag-and-drop asset binding', async () => {
    setActivePinia(createPinia())
    const store = useRowsStore()
    vi.spyOn(store, 'fetchRows').mockResolvedValue()
    vi.spyOn(store, 'attachExistingAsset').mockRejectedValue(new Error('拖拽失败'))
    const showError = vi.spyOn(ElMessage, 'error').mockImplementation(() => undefined as never)
    const WorkbenchView = (await import('@/views/WorkbenchView.vue')).default
    const wrapper = mount(WorkbenchView, {
      global: {
        stubs: {
          ElButton, AgGridVue: { template: '<div />' }, PromptResultDialog: { template: '<div />' },
          AssetLibraryDialog: { template: '<div />' }, ElDialog: { template: '<div><slot /></div>' },
          ElTooltip: { template: '<div><slot /></div>' },
        },
      },
    })
    const view = wrapper.vm as unknown as {
      renderImageCell: (data: RowItem, params: { colDef: { field: string; headerName: string } }) => {
        props: { onDropAsset: (assetId: string, kind: string) => void }
      }
    }
    const cell = view.renderImageCell(createRow('row-1', 'READY'), {
      colDef: { field: 'scene_asset', headerName: '场景参考图' },
    })

    cell.props.onDropAsset('asset-1', 'scene_reference')
    await vi.waitFor(() => expect(showError).toHaveBeenCalledWith('拖拽绑定图片失败'))
  })

  it('renders action buttons with readable Chinese labels', async () => {
    const module = await import('@/views/workbenchCellRenderers')
    expect(typeof module.buildActionCell).toBe('function')

    const noop = async () => undefined
    const sample = (status: string) => module.collectCellLabels(
      module.buildActionCell(
        { data: { id: 'a', name: 'A', status, row_revision: 1 } } as never,
        { runRow: noop, cancelRow: noop, openResults: noop, removeRow: noop, openErrorDetail: () => undefined },
      ),
    )

    expect(sample('COMPLETED')).toEqual(expect.arrayContaining(['重新运行', '查看提示词', '删除任务']))
    expect(sample('FAILED')).toEqual(expect.arrayContaining(['重新运行', '查看错误', '删除任务']))
    expect(sample('READY')).toEqual(expect.arrayContaining(['运行', '删除任务']))
    expect(sample('ANALYZING')).toEqual(expect.arrayContaining(['取消', '删除任务']))
    expect(sample('DRAFT')).toEqual(expect.arrayContaining(['删除任务']))
  })
})
