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
  sort_key: number
  auto_run: boolean
  created_at: string | null
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
  /** 正在执行整行写操作（运行/删除等）的任务行 ID 集合。 */
  const mutatingRowIds = ref<Set<string>>(new Set())
  /** 正在执行单元格写操作（上传/解绑图片等）的 key 集合，格式 `${rowId}:${kind}`。 */
  const mutatingCellKeys = ref<Set<string>>(new Set())
  /** 是否有任意行正在执行写操作。 */
  const mutating = computed(() => mutatingRowIds.value.size > 0 || mutatingCellKeys.value.size > 0)
  const rowMutations = new Map<string, Promise<void>>()

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

  async function fetchRows() {
    loading.value = true
    try {
      const res = await api.get('/api/v1/rows')
      rows.value = res.data?.data ?? []
    } finally {
      loading.value = false
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
    const response = await api.get('/api/v1/rows')
    const latestRows = (response.data?.data ?? []) as RowItem[]
    rows.value = latestRows
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
    mutation.finally(() => {
      if (rowMutations.get(rowId) === mutation) rowMutations.delete(rowId)
    })
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
      await api.patch(`/api/v1/rows/${row.id}`, {
        expected_revision: latest.row_revision,
        [field]: assetId,
      })
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

  async function deleteRow(row: RowItem) {
    return enqueueMutation(row.id, async () => {
      const latest = await getLatestRow(row.id)
      await api.delete(`/api/v1/rows/${row.id}`, {
        params: { expected_revision: latest.row_revision },
      })
      await fetchRows()
    })
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
    rows, loading, mutating, mutatingRowIds, mutatingCellKeys, isMutating,
    fetchRows, createRow, uploadAndAttach, detachAsset,
    runRow, deleteRow, fetchResults, fetchAssets, attachExistingAsset,
  }
})
