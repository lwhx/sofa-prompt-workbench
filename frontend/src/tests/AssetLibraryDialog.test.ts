import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AssetLibraryDialog from '@/components/AssetLibraryDialog.vue'
import { useRowsStore, type AssetItem } from '@/stores/rows'

/** 创建资产库测试数据。 */
function createAsset(id: string, filename: string): AssetItem {
  return {
    id,
    kind: 'scene_reference',
    original_filename: filename,
    thumbnail_url: `/thumb/${id}`,
    public_url: `/asset/${id}`,
  }
}

describe('AssetLibraryDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('clears old assets immediately when reopened and waits for fresh data', async () => {
    let resolveSecond!: (assets: AssetItem[]) => void
    const store = useRowsStore()
    vi.spyOn(store, 'fetchAssets')
      .mockResolvedValueOnce([createAsset('old', '旧图片.png')])
      .mockReturnValueOnce(new Promise(resolve => { resolveSecond = resolve }))
    const wrapper = mount(AssetLibraryDialog, {
      props: { visible: false, kind: 'scene_reference' },
    })
    await wrapper.setProps({ visible: true })
    await vi.waitFor(() => expect(wrapper.text()).toContain('旧图片.png'))

    await wrapper.setProps({ visible: false })
    await wrapper.setProps({ visible: true })
    await nextTick()

    expect(wrapper.text()).not.toContain('旧图片.png')
    expect(wrapper.text()).toContain('加载中')
    resolveSecond([createAsset('new', '新图片.png')])
    await vi.waitFor(() => expect(wrapper.text()).toContain('新图片.png'))
  })
})
