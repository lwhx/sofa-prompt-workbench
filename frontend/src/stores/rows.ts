import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/services/api'

export interface RowItem {
  id: string
  name: string
  status: string
  row_revision: number
  /** 该任务行的反推提示词结果数量 */
  results_count: number
  selected_result_id?: string | null
  sort_key: number
  auto_run: boolean
  created_at: string | null
  /** 软删除时间，非空时表示任务位于回收站。 */
  deleted_at?: string | null
  error_message?: string | null
  /** 最近一次任务开始时间（ISO 字符串）。 */
  job_started_at?: string | null
  /** 最近一次任务完成时间（ISO 字符串）。 */
  job_completed_at?: string | null
  scene_asset_id?: string | null
  sofa_asset_id?: string | null
  scene_asset?: AssetSummary | null
  sofa_asset?: AssetSummary | null
}

/** 任务行列表与导出的服务端筛选条件。 */
export interface RowFilters {
  /** 按任务名称或任务 ID 模糊搜索。 */
  search?: string
  /** 按任务状态筛选。 */
  status?: string[]
  /** 是否仅查询软删除任务。 */
  onlyDeleted?: boolean
}

export interface AssetSummary {
  id: string
  filename: string
  thumbnail_url: string
  public_url: string
  width?: number | null
  height?: number | null
  mime_type?: string | null
}

export interface AssetItem {
  id: string
  kind: string
  original_filename: string
  thumbnail_url: string
  public_url: string
  width?: number | null
  height?: number | null
  file_size?: number | null
  created_at?: string | null
}

export interface PromptResultItem {
  id: string
  version: number
  positive_prompt: string
  negative_prompt: string
  review_status: string
  review: { required?: boolean; reasons?: string[] }
  sofa_view?: { view_type?: string; near_end?: string; far_end?: string }
  warnings: string[]
  is_stale: boolean
  created_at?: string | null
  source?: string
  schema_version?: number
  selected_at?: string | null
}

export const useRowsStore = defineStore('rows', () => {
  const rows = ref<RowItem[]>([])
  const loading = ref(false)
  /** 当前任务行筛选条件。 */
  const filters = ref<RowFilters>({})
  /** 正在执行整行写操作（运行/删除等）的任务行 ID 集合。 */
  const mutatingRowIds = ref<Set<string>>(new Set())
  /** 正在执行单元格写操作（上传/解绑图片等）的 key 集合，格式 `${rowId}:${kind}`。 */
  const mutatingCellKeys = ref<Set<string>>(new Set())
  /** 是否有任意行正在执行写操作。 */
  const mutating = computed(() => mutatingRowIds.value.size > 0 || mutatingCellKeys.value.size > 0)
  const rowMutations = new Map<string, Promise<void>>()
  /** 最近一次任务行列表请求的递增序号。 */
  let rowsRequestId = 0

  /**
   * 判断指定行（或其某个图片格子）是否正在执行写操作。
   * @param rowId - 任务行 ID。
   * @param kind - 可选，图片类型。传入时仅判断该格子是否在操作；不传时判断整行是否有任意操作。
   * @returns 是否正在操作中。
   */
  function isMutating(rowId: string, kind?: 'scene_reference' | 'sofa_product'): boolean {
    if (kind) {
      return mutatingRowIds.value.has(rowId) || mutatingCellKeys.value.has(`${rowId}:${kind}`)
    }
    if (mutatingRowIds.value.has(rowId)) return true
    for (const key of mutatingCellKeys.value) {
      if (key.startsWith(`${rowId}:`)) return true
    }
    return false
  }

  /**
   * 转换当前筛选条件为后端查询参数。
   * @param source - 要转换的筛选条件。
   * @returns 可直接传给 axios 的查询参数。
   */
  function buildFilterParams(source: RowFilters = filters.value): Record<string, string | string[] | boolean> {
    const params: Record<string, string | string[] | boolean> = {}
    const search = source.search?.trim()
    if (search) params.search = search
    if (source.status?.length) params.status = source.status
    if (source.onlyDeleted) params.only_deleted = true
    return params
  }

  /**
   * 拉取当前筛选条件下的任务行。
   * @param nextFilters - 可选的新筛选条件，传入后同步替换当前条件。
   * @returns 请求完成的 Promise。
   */
  async function fetchRows(nextFilters?: RowFilters): Promise<void> {
    if (nextFilters) filters.value = { ...nextFilters }
    const requestId = ++rowsRequestId
    loading.value = true
    try {
      const res = await api.get('/api/v1/rows', { params: buildFilterParams() })
      if (requestId === rowsRequestId) rows.value = res.data?.data ?? []
    } finally {
      if (requestId === rowsRequestId) loading.value = false
    }
  }

  async function createRow(name: string = '新建产品') {
    const res = await api.post('/api/v1/rows', { name })
    if (res.status === 201 || res.status === 200) {
      await fetchRows()
    } else {
      throw new Error(`创建任务失败（HTTP ${res.status}）`)
    }
  }

  async function getLatestRow(rowId: string): Promise<RowItem> {
    const response = await api.get('/api/v1/rows', { params: { include_deleted: true } })
    const latestRows = (response.data?.data ?? []) as RowItem[]
    const latest = latestRows.find(item => item.id === rowId)
    if (!latest) throw new Error('任务行不存在或已删除')
    return latest
  }

  /**
   * 将操作串行化到同一行的 mutation 队列中。
   * 防止并发写操作导致 expected_revision 乐观锁冲突。
   * @param rowId - 目标行 ID。
   * @param fn - 要执行的操作函数。
   * @param kind - 可选，图片类型。传入时按单元格粒度标记 loading，仅对应格子显示处理中。
   */
  function enqueueMutation(
    rowId: string,
    fn: () => Promise<void>,
    kind?: 'scene_reference' | 'sofa_product',
  ): Promise<void> {
    const previous = rowMutations.get(rowId) ?? Promise.resolve()
    const mutation = previous.catch(() => undefined).then(async () => {
      // 按 kind 决定标记粒度：有 kind 标记到单元格，否则标记到整行
      if (kind) {
        mutatingCellKeys.value = new Set(mutatingCellKeys.value).add(`${rowId}:${kind}`)
      } else {
        mutatingRowIds.value = new Set(mutatingRowIds.value).add(rowId)
      }
      try {
        await fn()
      } finally {
        if (kind) {
          const nextCells = new Set(mutatingCellKeys.value)
          nextCells.delete(`${rowId}:${kind}`)
          mutatingCellKeys.value = nextCells
        } else {
          const nextRows = new Set(mutatingRowIds.value)
          nextRows.delete(rowId)
          mutatingRowIds.value = nextRows
        }
      }
    })
    rowMutations.set(rowId, mutation)
    void mutation.finally(() => {
      if (rowMutations.get(rowId) === mutation) rowMutations.delete(rowId)
    }).catch(() => undefined)
    return mutation
  }

  async function uploadAndAttach(row: RowItem, kind: 'scene_reference' | 'sofa_product', file: File) {
    return enqueueMutation(row.id, async () => {
      const form = new FormData()
      form.append('kind', kind)
      form.append('file', file)
      const uploaded = await api.post('/api/v1/assets/upload', form)
      const assetId = uploaded.data?.data?.id
      if (!assetId) throw new Error('图片上传失败：未获取到资产 ID')
      let latest: RowItem
      try {
        latest = await getLatestRow(row.id)
      } catch (error) {
        // 补偿：行已删除，清理刚上传的孤儿资产
        try { await api.delete(`/api/v1/assets/${assetId}`) } catch { /* 资产可能已随行删除 */ }
        throw error
      }
      const field = kind === 'scene_reference' ? 'scene_asset_id' : 'sofa_asset_id'
      try {
        await api.patch(`/api/v1/rows/${row.id}`, {
          expected_revision: latest.row_revision,
          [field]: assetId,
        })
      } catch (error) {
        try { await api.delete(`/api/v1/assets/${assetId}`) } catch { /* 资产可能已被其他流程清理 */ }
        throw error
      }
      await fetchRows()
    }, kind)
  }

  async function runRow(row: RowItem, forceRegenerate: boolean = false) {
    return enqueueMutation(row.id, async () => {
      const latest = await getLatestRow(row.id)
      await api.post(`/api/v1/rows/${row.id}/run`, {
        expected_revision: latest.row_revision,
        force_regenerate: forceRegenerate,
      })
      await fetchRows()
    })
  }

  async function cancelRow(row: RowItem) {
    return enqueueMutation(row.id, async () => {
      const latest = await getLatestRow(row.id)
      await api.post(`/api/v1/rows/${row.id}/cancel`, {
        expected_revision: latest.row_revision,
      })
      await fetchRows()
    })
  }

  async function deleteRow(row: RowItem) {
    return enqueueMutation(row.id, async () => {
      const latest = await getLatestRow(row.id)
      await api.delete(`/api/v1/rows/${row.id}`, {
        params: { expected_revision: latest.row_revision },
      })
      await fetchRows()
    })
  }

  /**
   * 恢复回收站中的软删除任务行。
   * @param row - 要恢复的任务行。
   * @returns 恢复完成的 Promise。
   */
  async function restoreRow(row: RowItem): Promise<void> {
    return enqueueMutation(row.id, async () => {
      await api.post(`/api/v1/rows/${row.id}/restore`, undefined, {
        params: { expected_revision: row.row_revision },
      })
      await fetchRows()
    })
  }

  /**
   * 导出当前筛选结果并触发浏览器下载。
   * @param format - 导出格式。
   * @returns 下载完成的 Promise。
   */
  async function exportRows(format: 'json' | 'csv'): Promise<void> {
    const response = await api.get('/api/v1/rows/export', {
      params: { ...buildFilterParams(), format },
      responseType: 'blob',
    })
    const contentDisposition = String(response.headers?.['content-disposition'] ?? '')
    const encodedName = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
    const filename = encodedName ? decodeURIComponent(encodedName) : `任务数据.${format}`
    const downloadUrl = URL.createObjectURL(response.data as Blob)
    const anchor = document.createElement('a')
    anchor.href = downloadUrl
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(downloadUrl)
  }

  async function detachAsset(row: RowItem, kind: 'scene_reference' | 'sofa_product') {
    return enqueueMutation(row.id, async () => {
      const latest = await getLatestRow(row.id)
      const field = kind === 'scene_reference' ? 'clear_scene_asset' : 'clear_sofa_asset'
      await api.patch(`/api/v1/rows/${row.id}`, {
        expected_revision: latest.row_revision,
        [field]: true,
      })
      await fetchRows()
    }, kind)
  }

  async function fetchAssets(kind?: 'scene_reference' | 'sofa_product'): Promise<AssetItem[]> {
    const res = await api.get('/api/v1/assets', { params: kind ? { kind } : {} })
    return res.data?.data ?? []
  }

  /**
   * 将已存在的资产绑定到任务行（复用已有图片）。
   */
  async function attachExistingAsset(
    row: RowItem,
    kind: 'scene_reference' | 'sofa_product',
    assetId: string,
  ) {
    return enqueueMutation(row.id, async () => {
      const latest = await getLatestRow(row.id)
      const field = kind === 'scene_reference' ? 'scene_asset_id' : 'sofa_asset_id'
      await api.patch(`/api/v1/rows/${row.id}`, {
        expected_revision: latest.row_revision,
        [field]: assetId,
      })
      await fetchRows()
    }, kind)
  }

  async function fetchResults(rowId: string): Promise<PromptResultItem[]> {
    const response = await api.get(`/api/v1/rows/${rowId}/results`)
    return response.data?.data ?? []
  }

  return {
    rows, loading, filters, mutating, mutatingRowIds, mutatingCellKeys, isMutating,
    fetchRows, createRow, uploadAndAttach, detachAsset,
    runRow, cancelRow, deleteRow, restoreRow, exportRows,
    fetchResults, fetchAssets, attachExistingAsset,
  }
})
