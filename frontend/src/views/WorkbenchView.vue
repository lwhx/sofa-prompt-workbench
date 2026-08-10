<template>
  <div class="workbench">
    <div class="toolbar">
      <el-button
        type="primary"
        :icon="Plus"
        :loading="batchRunning"
        @click="handleCreate"
      >
        新建任务
      </el-button>
      <el-button
        :icon="Refresh"
        :loading="loading"
        @click="handleRefresh"
      >
        刷新
      </el-button>
      <el-button
        type="primary"
        plain
        :disabled="selectedRows.length === 0 || !hasRunnableSelection"
        :loading="batchRunning"
        @click="runSelectedRows"
      >
        批量运行
      </el-button>
      <el-button
        type="danger"
        plain
        :disabled="selectedRows.length === 0"
        @click="deleteSelectedRows"
      >
        批量删除
      </el-button>
      <el-button
        :icon="Delete"
        @click="openTrash"
      >
        回收站
      </el-button>
      <el-button
        :icon="Download"
        @click="exportRows('json')"
      >
        导出 JSON
      </el-button>
      <el-button
        :icon="Download"
        @click="exportRows('csv')"
      >
        导出 CSV
      </el-button>
      <!-- 任务完成通知开关 -->
      <el-tooltip
        :content="notifier.enabled.value ? '关闭完成通知' : '开启完成通知'"
        placement="bottom"
      >
        <el-button
          :type="notifier.enabled.value ? 'success' : 'default'"
          :icon="Bell"
          circle
          @click="toggleNotification"
        />
      </el-tooltip>
      <div
        class="workbench-summary"
        aria-label="任务统计"
      >
        <span><strong>{{ rows.length }}</strong> 全部任务</span>
        <span><strong>{{ activeCount }}</strong> 处理中</span>
        <span><strong>{{ completedCount }}</strong> 已完成</span>
      </div>
      <span class="paste-tip">双击名称编辑 · 选中图片格后 Ctrl+V 粘贴</span>
    </div>
    <div class="filter-bar">
      <el-input
        v-model="searchText"
        class="search-input"
        clearable
        placeholder="搜索任务名称或 ID"
        :prefix-icon="Search"
        @keyup.enter="applyFilters"
        @clear="applyFilters"
      />
      <el-select
        v-model="selectedStatuses"
        class="status-filter"
        multiple
        collapse-tags
        clearable
        placeholder="全部状态"
        @change="applyFilters"
      >
        <el-option
          v-for="option in statusOptions"
          :key="option.value"
          :label="option.label"
          :value="option.value"
        />
      </el-select>
      <el-button
        type="primary"
        :icon="Search"
        :loading="loading"
        @click="applyFilters"
      >
        查询
      </el-button>
      <el-button @click="resetFilters">
        重置
      </el-button>
      <span class="filter-result">当前 {{ rows.length }} 条</span>
    </div>
    <!-- SSE 实时连接断开提示条 -->
    <div
      v-if="!sseConnected"
      class="sse-banner"
      role="status"
      aria-live="polite"
    >
      <span class="sse-dot" />实时连接已断开，正在自动重连…
    </div>
    <!-- 初始加载骨架占位 -->
    <div
      v-if="initialLoading"
      class="grid-skeleton"
    >
      <div
        v-for="n in 5"
        :key="n"
        class="skeleton-row"
      >
        <div class="skeleton-cell skeleton-name" />
        <div class="skeleton-cell skeleton-img" />
        <div class="skeleton-cell skeleton-img" />
        <div class="skeleton-cell skeleton-status" />
        <div class="skeleton-cell skeleton-count" />
        <div class="skeleton-cell skeleton-time" />
        <div class="skeleton-cell skeleton-action" />
      </div>
    </div>
    <div
      v-show="!initialLoading"
      class="grid-container"
      @paste.prevent="onGridPaste"
    >
      <div
        class="ag-theme-quartz"
        style="width: 100%; height: 100%"
      >
        <AgGridVue
          style="width: 100%; height: 100%"
          :grid-options="gridOptions"
          :row-data="rows"
          @grid-ready="onGridReady"
          @selection-changed="onSelectionChanged"
          @row-double-clicked="onRowDoubleClick"
          @cell-value-changed="onCellValueChanged"
        />
      </div>
    </div>
    <el-dialog
      v-model="previewOpen"
      title="图片预览"
      width="min(900px, 90vw)"
      destroy-on-close
    >
      <img
        v-if="previewUrl"
        class="preview-image"
        :src="previewUrl"
        alt="图片预览"
      >
    </el-dialog>
    <PromptResultDialog
      v-model="resultOpen"
      :results="resultItems"
      :loading="resultLoading"
      :row-id="resultRowId"
      :row-revision="resultRowRevision"
      :selected-result-id="resultSelectedId"
      @changed="reloadResults"
    />
    <AssetLibraryDialog
      :visible="libraryOpen"
      :kind="libraryKind"
      @close="libraryOpen = false"
      @select="onLibrarySelect"
    />
    <el-dialog
      v-model="trashOpen"
      title="回收站"
      width="min(900px, 92vw)"
      destroy-on-close
    >
      <el-table
        v-loading="trashLoading"
        :data="trashRows"
        empty-text="回收站为空"
        max-height="55vh"
      >
        <el-table-column
          prop="name"
          label="任务名称"
          min-width="200"
        />
        <el-table-column
          prop="status"
          label="删除前状态"
          width="130"
        >
          <template #default="scope">
            {{ scope?.row ? (STATUS_MAP[scope.row.status] ?? scope.row.status) : '' }}
          </template>
        </el-table-column>
        <el-table-column
          prop="deleted_at"
          label="删除时间"
          width="180"
        >
          <template #default="scope">
            {{ formatDateTime(scope?.row?.deleted_at) }}
          </template>
        </el-table-column>
        <el-table-column
          label="操作"
          width="120"
          fixed="right"
        >
          <template #default="scope">
            <el-button
              type="primary"
              plain
              :loading="scope?.row ? store.isMutating(scope.row.id) : false"
              @click="scope?.row && restoreTrashRow(scope.row)"
            >
              恢复
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { AgGridVue } from 'ag-grid-vue3'
import { AllCommunityModule, ModuleRegistry } from 'ag-grid-community'
import type { ColDef, GridApi, GridOptions as AGGridOptions, ICellRendererParams, ValueGetterParams } from 'ag-grid-community'
import { ElDialog, ElMessageBox, ElButton, ElMessage } from 'element-plus'
import { Bell, Delete, Download, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { buildActionCell } from '@/views/workbenchCellRenderers'
import { createVueCellRenderer, resolvePasteTarget } from '@/views/vueCellRenderer'
import ImagePasteCell from '@/components/ImagePasteCell.vue'
import PromptResultDialog from '@/components/PromptResultDialog.vue'
import AssetLibraryDialog from '@/components/AssetLibraryDialog.vue'
import { useRowsStore, type PromptResultItem, type RowItem } from '@/stores/rows'
import { api, extractApiError } from '@/services/api'
import { startRowEvents } from '@/services/rowEvents'
import { useTaskNotifier } from '@/composables/useTaskNotifier'
import { h } from 'vue'

ModuleRegistry.registerModules([AllCommunityModule])

const store = useRowsStore()
const { rows, loading } = storeToRefs(store)
/** 当前选中的任务行。 */
const selectedRows = ref<RowItem[]>([])
/** 搜索输入框文本。 */
const searchText = ref('')
/** 当前选中的任务状态。 */
const selectedStatuses = ref<string[]>([])
/** 回收站弹窗是否打开。 */
const trashOpen = ref(false)
/** 回收站任务列表。 */
const trashRows = ref<RowItem[]>([])
/** 回收站列表是否正在加载。 */
const trashLoading = ref(false)
/** 批量运行是否正在执行。 */
const batchRunning = ref(false)
/** SSE 实时连接是否正常。 */
const sseConnected = ref(true)
/** 可由批量运行处理的状态。 */
const RUNNABLE_STATES = new Set(['READY', 'NEEDS_REVIEW', 'COMPLETED', 'FAILED', 'CANCELED'])
/** 当前选区是否包含可运行任务。 */
const hasRunnableSelection = computed(() => selectedRows.value.some(row => RUNNABLE_STATES.has(row.status)))
const previewUrl = ref('')
const previewOpen = computed({ get: () => Boolean(previewUrl.value), set: v => { if (!v) previewUrl.value = '' } })
const resultOpen = ref(false)
const resultLoading = ref(false)
const resultItems = ref<PromptResultItem[]>([])
const resultRowId = ref<string | null>(null)
const resultRowRevision = ref(1)
const resultSelectedId = ref<string | null>(null)
/** 最近一次结果列表请求的递增序号。 */
let resultRequestId = 0
const libraryOpen = ref(false)
const libraryKind = ref<'scene_reference' | 'sofa_product'>('scene_reference')
const libraryTargetRow = ref<RowItem | null>(null)
const gridApi = ref<GridApi | null>(null)
const _POLLING_STATES = new Set(['QUEUED', 'ANALYZING', 'VALIDATING', 'REPAIRING', 'DEBOUNCING', 'CANCELING', 'UPLOADING'])
const activeCount = computed(() => rows.value.filter(row => _POLLING_STATES.has(row.status)).length)
const completedCount = computed(() => rows.value.filter(row => row.status === 'COMPLETED').length)
/** 是否为首次加载（用于显示骨架屏）。 */
const initialLoading = ref(true)

/** 任务完成通知。 */
const notifier = useTaskNotifier()

/**
 * 切换通知开关。
 * 首次开启时请求桌面通知权限。
 */
async function toggleNotification(): Promise<void> {
  if (notifier.enabled.value) {
    notifier.enabled.value = false
    notifier.stopTitleFlash()
    ElMessage.info('已关闭任务完成通知')
    return
  }
  notifier.enabled.value = true
  ElMessage.success('已开启任务完成通知')
  if ('Notification' in globalThis && Notification.permission === 'default') {
    await notifier.requestPermission()
    if (notifier.permission.value === 'granted') {
      ElMessage.success('桌面通知已授权')
    } else if (notifier.permission.value === 'denied') {
      ElMessage.info('桌面通知被拒绝，将仅使用标题闪烁提醒')
    }
  }
  /** 立即用当前状态初始化快照，避免开启时误报。 */
  notifier.checkAndNotify(rows.value)
}

/** 是否有运行中任务（用于决定是否启动计时器）。 */
const hasActiveRowsForTimer = computed(() => rows.value.some(r => ACTIVE_STATUS_TYPES.has(r.status)))

/** 启动/停止每秒计时器，仅在有运行中任务时运行。 */
watch(hasActiveRowsForTimer, (active) => {
  if (active && !_nowTimer) {
    now.value = Date.now()
    _nowTimer = globalThis.setInterval(() => {
      now.value = Date.now()
      // 强制 AG Grid 刷新状态列，使运行中任务的耗时每秒更新
      gridApi.value?.refreshCells({ columns: ['status'], force: true })
    }, 1000)
  } else if (!active && _nowTimer) {
    globalThis.clearInterval(_nowTimer)
    _nowTimer = null
    /** 最后更新一次，确保终态耗时准确。 */
    now.value = Date.now()
    gridApi.value?.refreshCells({ columns: ['status'], force: true })
  }
})

/** 保存 Grid API 并初始化列配置。 */
function onGridReady(params: { api: GridApi }) {
  gridApi.value = params.api
  params.api.setGridOption('columnDefs', columnDefs.value)
  params.api.sizeColumnsToFit()
}

/** 同步 AG Grid 当前选中行。 */
function onSelectionChanged(): void {
  selectedRows.value = gridApi.value?.getSelectedRows() ?? []
}

function onRowDoubleClick(params: { data: RowItem; column?: { getColId(): string } }) {
  const api = gridApi.value
  const colId = params.column?.getColId()
  if (api && colId === 'name') {
    const rowNode = (api as unknown as { getRowNode?: (id: string) => { rowIndex: number } | undefined })
      .getRowNode?.(params.data.id)
    const startEditingCell = (api as unknown as {
      startEditingCell?: (position: { rowIndex: number; colKey: string }) => void
    }).startEditingCell
    startEditingCell?.({ rowIndex: rowNode?.rowIndex ?? 0, colKey: 'name' })
    return
  }
  if (['NEEDS_REVIEW', 'COMPLETED'].includes(params.data.status)) openResults(params.data)
}
async function onCellValueChanged(params: { data: RowItem; newValue: unknown; oldValue: unknown; colDef: { field?: string } }) {
  if (params.colDef.field !== 'name') return
  const newVal = String(params.newValue ?? '').trim()
  if (newVal && newVal !== params.oldValue) {
    try {
      await api.patch(`/api/v1/rows/${params.data.id}`, { expected_revision: params.data.row_revision, name: newVal })
      await store.fetchRows()
    } catch (error) {
      /** 版本冲突时静默刷新，其他错误提示用户。 */
      const status = (error as { response?: { status?: number } }).response?.status
      if (status !== 409) {
        ElMessage.error(extractApiError(error, '重命名失败'))
      }
      await store.fetchRows()
    }
  }
}

const defaultColDef = { resizable: true, sortable: true, flex: 1, minWidth: 80 }
const getRowId = (params: { data: { id: string } }) => params.data.id

const gridOptions: AGGridOptions = {
  defaultColDef,
  getRowId,
  theme: 'legacy',
  rowHeight: 96,
  headerHeight: 40,
  rowSelection: { mode: 'multiRow', checkboxes: true, headerCheckbox: true, enableClickSelection: true },
  selectionColumnDef: { width: 48, minWidth: 48, maxWidth: 48, pinned: 'left', sortable: false, resizable: false },
  animateRows: true,
  stopEditingWhenCellsLoseFocus: true,
  columnDefs: [],
  /** 空状态中文引导文案。 */
  overlayNoRowsTemplate: '<div style="padding:32px;text-align:center;color:#8a94a3;">暂无任务，点击上方「新建任务」开始创建</div>',
}

/** 图片单元格渲染：接收响应式 data 和 params，返回 ImagePasteCell vnode */
function renderImageCell(data: unknown, params: ICellRendererParams) {
  const row = data as RowItem
  const field = params.colDef?.field ?? ''
  const kind = field === 'scene_asset' ? 'scene_reference' : 'sofa_product'
  return h(ImagePasteCell, {
    label: params.colDef?.headerName ?? '',
    asset: row[field as 'scene_asset' | 'sofa_asset'],
    assetKind: kind,
    loading: store.isMutating(row.id, kind),
    onUpload: (file: globalThis.File) => store.uploadAndAttach(row, kind, file),
    onPreview: (url: string) => { previewUrl.value = url },
    onRemove: () => store.detachAsset(row, kind),
    onPickFromLibrary: () => openLibrary(row, kind),
    onDropAsset: (assetId: string, assetKind: string) => {
      if (assetKind === kind) {
        store.attachExistingAsset(row, kind, assetId).catch((error: unknown) => {
          ElMessage.error(extractApiError(error, '拖拽绑定图片失败'))
        })
      }
    },
  })
}

const STATUS_MAP: Record<string, string> = {
  DRAFT: '草稿', WAITING_IMAGES: '等待图片', UPLOADING: '上传中', READY: '就绪',
  DEBOUNCING: '防抖中', QUEUED: '排队中', ANALYZING: '分析中', VALIDATING: '校验中',
  REPAIRING: '修复中', NEEDS_REVIEW: '待审核', COMPLETED: '已完成', FAILED: '失败',
  CANCELING: '取消中', CANCELED: '已取消', DIRTY: '输入已变更',
}
/** 状态筛选选项。 */
const statusOptions = Object.entries(STATUS_MAP).map(([value, label]) => ({ value, label }))
/** 进行中状态集合（蓝色 + 脉冲动画）。 */
const ACTIVE_STATUS_TYPES = new Set(['UPLOADING', 'DEBOUNCING', 'QUEUED', 'ANALYZING', 'VALIDATING', 'REPAIRING', 'CANCELING'])
/** 状态 → 视觉类型映射。进行中=primary，完成=success，失败=danger，待审核=warning。 */
const STATUS_TYPE: Record<string, string> = {
  COMPLETED: 'success', FAILED: 'danger', DIRTY: 'warning', NEEDS_REVIEW: 'warning',
  READY: 'info',
}
/** 终态集合：有固定耗时。 */
const TERMINAL_STATES = new Set(['COMPLETED', 'FAILED', 'NEEDS_REVIEW', 'CANCELED'])
/** 当前时间 ref，运行中任务每秒刷新实时计时。 */
const now = ref(Date.now())
let _nowTimer: ReturnType<typeof globalThis.setInterval> | null = null

/**
 * 计算任务耗时（秒）。
 * @param row - 任务行数据。
 * @param currentTime - 当前时间戳（毫秒）。
 * @returns 耗时秒数，无法计算时返回 null。
 */
function calcDuration(row: RowItem, currentTime: number): number | null {
  if (!row.job_started_at) return null
  const startTime = parseIsoToTs(row.job_started_at)
  if (startTime === null) return null
  const isTerminal = TERMINAL_STATES.has(row.status)
  if (isTerminal) {
    // 终态任务必须有完成时间才能计算固定耗时，否则不显示
    if (!row.job_completed_at) return null
    const endTime = parseIsoToTs(row.job_completed_at)
    if (endTime === null) return null
    return Math.max(0, Math.round((endTime - startTime) / 1000))
  }
  // 运行中任务用当前时间实时计时
  return Math.max(0, Math.round((currentTime - startTime) / 1000))
}

/**
 * 将 ISO 字符串安全解析为时间戳。
 * 兼容有时区后缀和无时区后缀两种格式，无时区时按 UTC 处理。
 * @param iso - ISO 格式时间字符串。
 * @returns 毫秒时间戳，解析失败返回 null。
 */
function parseIsoToTs(iso: string): number | null {
  const ts = new Date(iso).getTime()
  return Number.isNaN(ts) ? null : ts
}

/**
 * 格式化耗时为可读文本。
 * @param seconds - 耗时秒数。
 * @returns 形如 "1分23秒" 或 "45秒"。
 */
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}秒`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return s > 0 ? `${m}分${s}秒` : `${m}分钟`
}

/** 状态单元格渲染 */
function renderStatusCell(data: unknown) {
  const row = data as RowItem
  const status = String(row?.status ?? '')
  const label = STATUS_MAP[status] ?? status
  const isActive = ACTIVE_STATUS_TYPES.has(status)
  const type = isActive ? 'primary' : (STATUS_TYPE[status] ?? 'info')
  const pulseClass = isActive ? ' status-pulse' : ''
  const duration = calcDuration(row, now.value)
  const durationText = duration !== null ? formatDuration(duration) : ''
  const children = [h('span', { class: `status-tag status-${type}${pulseClass}` }, label)]
  if (durationText) {
    children.push(h('span', { class: 'status-duration' }, durationText))
  }
  return h('div', { class: 'status-cell' }, children)
}

/** 操作单元格渲染 */
function renderActionCell(data: unknown) {
  return buildActionCell({ data: data as RowItem } as ICellRendererParams, {
    runRow: store.runRow,
    cancelRow,
    openResults,
    removeRow,
    openErrorDetail,
  })
}

async function cancelRow(row: RowItem): Promise<void> {
  try {
    await ElMessageBox.confirm('确定取消当前任务吗？', '取消任务', { type: 'warning' })
    await store.cancelRow(row)
    ElMessage.success('已提交取消请求')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(extractApiError(error, '取消任务失败'))
  }
}

const columnDefs = computed<ColDef[]>(() => [
  { headerName: '产品名称', field: 'name', editable: true, minWidth: 160, width: 200, suppressMovable: true },
  { headerName: '场景参考图', field: 'scene_asset', cellRenderer: createVueCellRenderer(renderImageCell), width: 136, flex: 0 },
  { headerName: '沙发白底图', field: 'sofa_asset', cellRenderer: createVueCellRenderer(renderImageCell), width: 136, flex: 0 },
  { headerName: '状态', field: 'status', cellRenderer: createVueCellRenderer(renderStatusCell), width: 96, flex: 0 },
  { headerName: '结果数', field: 'results_count', width: 72, flex: 0 },
  {
    headerName: '创建时间', field: 'created_at', width: 140, flex: 0,
    valueGetter: (params: ValueGetterParams) => {
      const val = params.data?.created_at as string | null
      return val ? val.replace('T', ' ').slice(0, 19) : ''
    },
  },
  { headerName: '操作', cellRenderer: createVueCellRenderer(renderActionCell), width: 300, flex: 0, sortable: false, resizable: false, pinned: 'right' },
])

/** 新建任务行。 */
async function handleCreate(): Promise<void> {
  try {
    await store.createRow()
    ElMessage.success('已创建新任务')
  } catch (error) {
    ElMessage.error(extractApiError(error, '创建任务失败'))
  }
}

/** 手动刷新任务行。 */
async function handleRefresh(): Promise<void> {
  try {
    await store.fetchRows()
  } catch (error) {
    ElMessage.error(extractApiError(error, '刷新失败'))
  }
}

/** 应用搜索与状态筛选条件。 */
async function applyFilters(): Promise<void> {
  try {
    await store.fetchRows({ search: searchText.value, status: selectedStatuses.value })
  } catch (error) {
    ElMessage.error(extractApiError(error, '筛选任务失败'))
  }
}

/** 清空搜索与状态筛选条件。 */
async function resetFilters(): Promise<void> {
  searchText.value = ''
  selectedStatuses.value = []
  await applyFilters()
}

/**
 * 导出当前筛选结果。
 * @param format - 导出文件格式。
 */
async function exportRows(format: 'json' | 'csv'): Promise<void> {
  try {
    await store.exportRows(format)
    ElMessage.success(`已导出 ${format.toUpperCase()} 文件`)
  } catch (error) {
    ElMessage.error(extractApiError(error, '导出任务失败'))
  }
}

/** 加载并打开回收站。 */
async function openTrash(): Promise<void> {
  trashOpen.value = true
  trashLoading.value = true
  try {
    const response = await api.get('/api/v1/rows', { params: { only_deleted: true } })
    trashRows.value = response.data?.data ?? []
  } catch (error) {
    ElMessage.error(extractApiError(error, '加载回收站失败'))
  } finally {
    trashLoading.value = false
  }
}

/**
 * 恢复回收站任务并刷新两个列表。
 * @param row - 要恢复的软删除任务。
 */
async function restoreTrashRow(row: RowItem): Promise<void> {
  try {
    await store.restoreRow(row)
    trashRows.value = trashRows.value.filter(item => item.id !== row.id)
    ElMessage.success('任务已恢复')
  } catch (error) {
    ElMessage.error(extractApiError(error, '恢复任务失败'))
  }
}

/**
 * 格式化 ISO 时间用于表格展示。
 * @param value - ISO 时间字符串。
 * @returns 本地可读时间，空值返回短横线。
 */
function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

/** 串行运行选区内所有可运行任务，逐条容错并汇总。 */
async function runSelectedRows(): Promise<void> {
  /** 本次批量运行时可处理的选中行快照。 */
  const runnableRows = selectedRows.value.filter(row => RUNNABLE_STATES.has(row.status))
  if (runnableRows.length === 0) return
  batchRunning.value = true
  let succeeded = 0
  let failed = 0
  for (const row of runnableRows) {
    try {
      /** READY 首次运行，其余可运行状态强制重新生成。 */
      await store.runRow(row, row.status !== 'READY')
      succeeded++
    } catch {
      failed++
    }
  }
  batchRunning.value = false
  if (failed === 0) {
    ElMessage.success(`已提交 ${succeeded} 个任务`)
  } else {
    ElMessage.warning(`成功 ${succeeded} 个，失败 ${failed} 个`)
  }
}

/** 单次确认后串行删除全部选中任务，逐条容错并汇总。 */
async function deleteSelectedRows(): Promise<void> {
  /** 本次批量删除的选中行快照。 */
  const rowsToDelete = [...selectedRows.value]
  await ElMessageBox.confirm(`将删除选中的 ${rowsToDelete.length} 个任务，确定继续吗？`, '批量删除', { type: 'warning' })
  let succeeded = 0
  let failed = 0
  for (const row of rowsToDelete) {
    try {
      await store.deleteRow(row)
      succeeded++
    } catch {
      failed++
    }
  }
  selectedRows.value = []
  if (failed === 0) {
    ElMessage.success(`已删除 ${succeeded} 个任务`)
  } else {
    ElMessage.warning(`成功删除 ${succeeded} 个，失败 ${failed} 个`)
  }
}

/** 打开图片库弹窗 */
function openLibrary(row: RowItem, kind: 'scene_reference' | 'sofa_product') {
  libraryTargetRow.value = row
  libraryKind.value = kind
  libraryOpen.value = true
}

/** 图片库选中后绑定到目标行 */
async function onLibrarySelect(assetId: string) {
  if (!libraryTargetRow.value) return
  try {
    await store.attachExistingAsset(libraryTargetRow.value, libraryKind.value, assetId)
  } catch (error) {
    ElMessage.error(extractApiError(error, '绑定图片失败'))
  }
  libraryTargetRow.value = null
}

async function removeRow(row: RowItem) {
  await ElMessageBox.confirm('删除后任务将移入回收站，确定继续吗？', '删除任务', { type: 'warning' })
  try {
    await store.deleteRow(row)
    ElMessage.success('已删除任务')
  } catch (error) {
    ElMessage.error(extractApiError(error, '删除任务失败'))
  }
}
async function openResults(row: RowItem) {
  const requestId = ++resultRequestId
  resultRowId.value = row.id
  resultRowRevision.value = row.row_revision
  resultSelectedId.value = row.selected_result_id ?? null
  resultOpen.value = true
  resultItems.value = []
  resultLoading.value = true
  try {
    const latestResults = await store.fetchResults(row.id)
    if (requestId === resultRequestId && resultRowId.value === row.id) resultItems.value = latestResults
  } finally {
    if (requestId === resultRequestId) resultLoading.value = false
  }
}
/** 删除结果后刷新结果列表和行数据（结果数列同步更新） */
async function reloadResults() {
  if (!resultRowId.value) return
  resultLoading.value = true
  try {
    resultItems.value = await store.fetchResults(resultRowId.value)
    await store.fetchRows()
    const currentRow = rows.value.find(row => row.id === resultRowId.value)
    if (currentRow) {
      resultRowRevision.value = currentRow.row_revision
      resultSelectedId.value = currentRow.selected_result_id ?? null
    }
  } finally { resultLoading.value = false }
}

/** 展示失败任务的错误详情。 */
function openErrorDetail(row: RowItem): void {
  const message = row.error_message || '任务执行失败，未提供具体错误信息'
  ElMessageBox.alert(message, `${row.name} — 失败原因`, { confirmButtonText: '知道了', type: 'error' })
}

/**
 * 全局粘贴处理器。
 * 读取 AG Grid 当前焦点单元格，若为图片列（scene_asset / sofa_asset），
 * 则从剪贴板提取图片并路由到对应行的上传逻辑。
 * @param event - 浏览器剪贴板事件。
 */
function onGridPaste(event: globalThis.ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files ?? [])
  if (files.length === 0) return

  const focused = gridApi.value?.getFocusedCell()
  if (!focused) return

  const colId = focused.column.getColId()
  const rowNode = gridApi.value?.getDisplayedRowAtIndex(focused.rowIndex)
  const rowData = rowNode?.data as RowItem | undefined
  if (!rowData) return

  const target = resolvePasteTarget(files, { colId, rowId: rowData.id })
  if (!target) return

  store.uploadAndAttach(rowData, target.kind, target.file).catch((error: unknown) => {
    ElMessage.error(extractApiError(error, '粘贴上传失败'))
  })
}

/** 停止 SSE 监听的方法。 */
let _stopRowEvents: (() => void) | null = null
onMounted(async () => {
  try {
    await store.fetchRows()
  } catch (error) {
    ElMessage.error(extractApiError(error, '加载任务列表失败'))
  } finally {
    initialLoading.value = false
  }
  _stopRowEvents = startRowEvents(
    () => { void store.fetchRows() },
    (status) => { sseConnected.value = status.connected },
  )
})

let _timer: ReturnType<typeof globalThis.setInterval> | null = null
function _hasActiveRows() { return rows.value.some(r => _POLLING_STATES.has(r.status)) }
function _stopPolling() { if (_timer) { globalThis.clearInterval(_timer); _timer = null } }

/**
 * 启动轮询。
 * 立即执行一次 fetchRows，然后每 3 秒持续轮询，直到没有活跃行。
 */
function _startPolling() {
  if (_timer) return
  /** 首次立即执行，避免等待 3 秒延迟 */
  store.fetchRows().catch(() => undefined)
  _timer = globalThis.setInterval(async () => {
    await store.fetchRows().catch(() => undefined)
    if (!_hasActiveRows()) _stopPolling()
  }, 3000)
}

watch(() => _hasActiveRows(), active => { if (active) { _startPolling() } else { _stopPolling() } })

/** 监听行数据变化，自动检测任务完成并触发通知。 */
watch(rows, (newRows) => {
  notifier.checkAndNotify(newRows)
}, { deep: false })

onUnmounted(() => {
  _stopPolling()
  if (_nowTimer) { globalThis.clearInterval(_nowTimer); _nowTimer = null }
  _stopRowEvents?.()
  _stopRowEvents = null
})
</script>

<style>
@import 'ag-grid-community/styles/ag-grid.css';
@import 'ag-grid-community/styles/ag-theme-quartz.css';

.workbench {
  display: flex; flex-direction: column; height: 100%; min-height: 0;
  padding: 14px 18px 16px; background: transparent;
}
.toolbar {
  display: flex; align-items: center; gap: 10px; padding: 13px 16px;
  border: 1px solid var(--sofa-line); border-bottom: 0; border-radius: 16px 16px 0 0;
  background: rgb(255 253 248 / 94%); flex-shrink: 0;
  box-shadow: 0 10px 30px rgb(62 50 38 / 6%);
}
.filter-bar {
  display: flex; align-items: center; gap: 10px; padding: 10px 16px;
  border: 1px solid var(--sofa-line); border-top-color: #ebe5da;
  background: rgb(250 247 240 / 96%); flex-shrink: 0;
}
.search-input { width: 280px; }
.status-filter { width: 220px; }
.filter-result { margin-left: 4px; color: var(--sofa-muted); font-size: 12px; }
.workbench-summary { display: flex; align-items: center; gap: 7px; margin-left: 4px; color: #64716b; font-size: 11px; }
.workbench-summary span { padding: 6px 10px; border: 1px solid #e5dfd4; border-radius: 8px; background: #f9f6ef; white-space: nowrap; }
.workbench-summary strong { margin-right: 3px; color: var(--sofa-green); font-size: 15px; font-variant-numeric: tabular-nums; }
.paste-tip { margin-left: auto; color: #8d928e; font-size: 11px; white-space: nowrap; }

/* SSE 断连提示条 */
.sse-banner {
  display: flex; align-items: center; gap: 8px; padding: 7px 16px;
  background: #fbf3df; border: 1px solid #e7cf98; border-top: 0;
  color: #8a611f; font-size: 13px;
}
.sse-dot { width: 8px; height: 8px; border-radius: 50%; background: #faad14; animation: pulse-dot 1.5s ease-in-out infinite; }
@keyframes pulse-dot { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

/* 骨架屏 */
.grid-skeleton { flex: 1; padding: 12px 0 0; overflow: hidden; }
.skeleton-row { display: flex; gap: 8px; padding: 12px; border-bottom: 1px solid #e3e6ea; height: 72px; align-items: center; }
.skeleton-cell { background: linear-gradient(90deg, #f0f2f5 25%, #e6e8ec 50%, #f0f2f5 75%); background-size: 200% 100%; animation: shimmer 1.5s infinite; border-radius: 4px; height: 32px; }
.skeleton-name { width: 160px; } .skeleton-img { width: 100px; height: 60px; }
.skeleton-status { width: 72px; } .skeleton-count { width: 48px; } .skeleton-time { width: 100px; } .skeleton-action { flex: 1; }
@keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

.grid-container { flex: 1; padding-top: 12px; overflow: hidden; min-height: 0; }
.grid-container .ag-theme-quartz {
  width: 100%; height: 100%; overflow: hidden; border: 1px solid var(--sofa-line);
  border-radius: 14px; background: var(--sofa-paper); box-shadow: var(--sofa-shadow);
  --ag-font-family: "Noto Sans SC", "Microsoft YaHei", "PingFang SC", sans-serif;
  --ag-font-size: 12px;
  --ag-header-background-color: #f3eee4;
  --ag-header-foreground-color: #4d5b54;
  --ag-border-color: #e4ded3;
  --ag-row-hover-color: #f8f5ee;
  --ag-selected-row-background-color: #e8f0eb;
  --ag-checkbox-checked-color: #315f4c;
  --ag-input-focus-border-color: #315f4c;
}
.grid-container :deep(.ag-header-cell-label) { font-weight: 700; letter-spacing: .03em; }
.grid-container :deep(.ag-cell) { display: flex; align-items: center; color: #303844; }
.grid-container :deep(.ag-row) { transition: background-color .16s ease; }
.grid-container :deep(.ag-cell .ag-cell-wrapper) { width: 100%; }
.grid-container :deep(.ag-cell .ag-cell-inline-editing-wrapper) { height: 100%; }
.grid-container :deep(.ag-cell-inline-editing) { padding: 0 8px; }
.grid-container :deep(.ag-cell-edit-wrapper input) { height: 28px; line-height: 28px; padding: 0 8px; border-radius: 3px; border-color: #2878c7; }
.grid-container :deep(.ag-row-pinned) { color: #303844; }
.preview-image { display: block; max-width: 100%; max-height: 72vh; margin: 0 auto; object-fit: contain; }

.action-cell { display: flex; align-items: center; gap: 6px; flex-wrap: nowrap; }
.action-cell :deep(.el-button + .el-button) { margin-left: 0; }
.action-cell :deep(.el-button) { padding: 5px 9px; font-size: 12px; }
.action-cell :deep(.el-button .el-icon) { margin-right: 4px; }
.status-tag { display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 12px; font-weight: 600; white-space: nowrap; }
/* 加深灰色文字以提升对比度至 WCAG AA（≥4.5:1） */
.status-info { background: #eeece7; color: #5c665f; }
.status-success { background: #e4eee7; color: #315f4c; }
.status-warning { background: #f7edd8; color: #906420; }
.status-danger { background: #f7e7e3; color: #a3483d; }
/* 进行中状态：蓝色 + 脉冲动画 */
.status-primary { background: #e2ebe6; color: #2f6650; }
.status-pulse { animation: status-breathe 2s ease-in-out infinite; }
@keyframes status-breathe { 0%, 100% { opacity: 1; } 50% { opacity: 0.65; } }
/* 状态单元格容器 */
.status-cell { display: flex; flex-direction: column; gap: 2px; }
/* 耗时文本 */
.status-duration { font-size: 11px; color: #8a94a3; font-variant-numeric: tabular-nums; }

@media (max-width: 820px) {
  .workbench { padding: 8px; }
  .toolbar { gap: 8px; padding: 10px; flex-wrap: wrap; }
  .filter-bar { padding: 8px; flex-wrap: wrap; }
  .search-input, .status-filter { width: 100%; }
  .workbench-summary span { padding: 4px 6px; }
  .paste-tip { display: none; }
  .grid-container { padding-top: 8px; overflow-x: auto; }
}

@media (prefers-reduced-motion: reduce) {
  .sse-dot, .skeleton-cell, .status-pulse { animation: none; }
}
</style>
