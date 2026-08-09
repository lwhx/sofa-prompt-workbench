import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api } from '@/services/api'
import { useRowsStore, type RowItem } from '@/stores/rows'

vi.mock('@/services/api', () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

const row: RowItem = {
  id: 'row-1', name: '产品', status: 'WAITING_IMAGES', row_revision: 1, results_count: 0,
  sort_key: 10, auto_run: false, created_at: null,
}

describe('rows store image attachment', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('uses the latest server revision after external image upload', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { data: { id: 'asset-1' } } })
    vi.mocked(api.get).mockResolvedValue({
      data: { data: [{ ...row, row_revision: 2 }] },
    })
    vi.mocked(api.patch).mockResolvedValue({ data: { data: { ...row, row_revision: 3 } } })
    const store = useRowsStore()

    await store.uploadAndAttach(row, 'sofa_product', new File(['x'], 'sofa.png', { type: 'image/png' }))

    expect(api.patch).toHaveBeenCalledWith('/api/v1/rows/row-1', {
      expected_revision: 2,
      sofa_asset_id: 'asset-1',
    })
  })

  it('uses the latest revision when reusing a sofa asset after the scene changed', async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: { data: [{ ...row, row_revision: 2 }] } })
      .mockResolvedValueOnce({ data: { data: [{ ...row, row_revision: 3 }] } })
    vi.mocked(api.patch).mockResolvedValue({ data: { data: { ...row, row_revision: 3 } } })
    const store = useRowsStore()

    await store.attachExistingAsset(row, 'sofa_product', 'sofa-asset-1')

    expect(api.patch).toHaveBeenCalledWith('/api/v1/rows/row-1', {
      expected_revision: 2,
      sofa_asset_id: 'sofa-asset-1',
    })
  })

  it('serializes two image operations for the same row', async () => {
    vi.mocked(api.post)
      .mockResolvedValueOnce({ data: { data: { id: 'scene-1' } } })
      .mockResolvedValueOnce({ data: { data: { id: 'sofa-1' } } })
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: { data: [{ ...row, row_revision: 1 }] } })
      .mockResolvedValueOnce({ data: { data: [{ ...row, row_revision: 2 }] } })
      .mockResolvedValue({ data: { data: [{ ...row, row_revision: 3 }] } })
    vi.mocked(api.patch).mockResolvedValue({ data: { data: {} } })
    const store = useRowsStore()

    await Promise.all([
      store.uploadAndAttach(row, 'scene_reference', new File(['a'], 'scene.png', { type: 'image/png' })),
      store.uploadAndAttach(row, 'sofa_product', new File(['b'], 'sofa.png', { type: 'image/png' })),
    ])

    expect(vi.mocked(api.patch).mock.calls[0]?.[1]).toMatchObject({ expected_revision: 1 })
    expect(vi.mocked(api.patch).mock.calls[1]?.[1]).toMatchObject({ expected_revision: 3 })
  })

  it('deletes the uploaded asset when row binding fails', async () => {
    const bindingError = new Error('绑定失败')
    vi.mocked(api.post).mockResolvedValue({ data: { data: { id: 'asset-orphan' } } })
    vi.mocked(api.get).mockResolvedValue({ data: { data: [{ ...row, row_revision: 2 }] } })
    vi.mocked(api.patch).mockRejectedValue(bindingError)
    vi.mocked(api.delete).mockResolvedValue({ data: { data: null } })
    const store = useRowsStore()

    await expect(store.uploadAndAttach(
      row,
      'scene_reference',
      new File(['x'], 'scene.png', { type: 'image/png' }),
    )).rejects.toBe(bindingError)

    expect(api.delete).toHaveBeenCalledWith('/api/v1/assets/asset-orphan')
    expect(store.isMutating(row.id, 'scene_reference')).toBe(false)
  })

  it('keeps the newest rows response when concurrent requests resolve out of order', async () => {
    let resolveFirst!: (value: { data: { data: RowItem[] } }) => void
    let resolveSecond!: (value: { data: { data: RowItem[] } }) => void
    vi.mocked(api.get)
      .mockReturnValueOnce(new Promise(resolve => { resolveFirst = resolve }))
      .mockReturnValueOnce(new Promise(resolve => { resolveSecond = resolve }))
    const store = useRowsStore()

    const firstRequest = store.fetchRows()
    const secondRequest = store.fetchRows()
    resolveSecond({ data: { data: [{ ...row, name: '最新数据' }] } })
    await secondRequest
    resolveFirst({ data: { data: [{ ...row, name: '旧数据' }] } })
    await firstRequest

    expect(store.rows[0]?.name).toBe('最新数据')
    expect(store.loading).toBe(false)
  })

  it('cleans mutation state after a rejected operation and accepts the next operation', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { data: [{ ...row, row_revision: 2 }] } })
    vi.mocked(api.patch)
      .mockRejectedValueOnce(new Error('首次绑定失败'))
      .mockResolvedValueOnce({ data: { data: {} } })
    const store = useRowsStore()

    await expect(store.attachExistingAsset(row, 'sofa_product', 'asset-1')).rejects.toThrow('首次绑定失败')
    await store.attachExistingAsset(row, 'sofa_product', 'asset-2')

    expect(api.patch).toHaveBeenCalledTimes(2)
    expect(store.isMutating(row.id, 'sofa_product')).toBe(false)
  })

  it('sends search, status and trash filters to the rows endpoint', async () => {
    vi.mocked(api.get).mockResolvedValue({ data: { data: [] } })
    const store = useRowsStore()

    await store.fetchRows({ search: ' 云朵 ', status: ['COMPLETED'], onlyDeleted: true })

    expect(api.get).toHaveBeenCalledWith('/api/v1/rows', {
      params: { search: '云朵', status: ['COMPLETED'], only_deleted: true },
    })
  })

  it('restores a soft-deleted row with its current revision', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: { data: {} } })
    vi.mocked(api.get).mockResolvedValue({ data: { data: [] } })
    const store = useRowsStore()
    const trashedRow = { ...row, row_revision: 4, deleted_at: '2026-08-10T00:00:00Z' }

    await store.restoreRow(trashedRow)

    expect(api.post).toHaveBeenCalledWith('/api/v1/rows/row-1/restore', undefined, {
      params: { expected_revision: 4 },
    })
  })

  it('downloads a CSV export using the server-provided filename', async () => {
    const blob = new Blob(['id,name\n1,沙发'], { type: 'text/csv' })
    vi.mocked(api.get).mockResolvedValue({
      data: blob,
      headers: { 'content-disposition': "attachment; filename*=UTF-8''%E4%BB%BB%E5%8A%A1.csv" },
    })
    const createObjectURL = vi.fn(() => 'blob:export')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const store = useRowsStore()

    await store.exportRows('csv')

    expect(api.get).toHaveBeenCalledWith('/api/v1/rows/export', {
      params: { format: 'csv' }, responseType: 'blob',
    })
    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:export')
  })
})
