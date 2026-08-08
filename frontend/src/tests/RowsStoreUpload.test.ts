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
})
