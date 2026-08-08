import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ImagePasteCell from '@/components/ImagePasteCell.vue'

describe('ImagePasteCell', () => {
  it('empty cell: click opens file picker', async () => {
    const wrapper = mount(ImagePasteCell, { props: { label: '场景参考图' } })
    const input = wrapper.find('input[type="file"]')
    const clickSpy = vi.spyOn(input.element as HTMLInputElement, 'click')

    await wrapper.find('.image-cell').trigger('click')

    expect(clickSpy).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('粘贴')
    expect(wrapper.text()).toContain('从图片库选择')
  })

  it('cell with asset: click does NOT open file picker', async () => {
    const wrapper = mount(ImagePasteCell, {
      props: {
        label: '沙发白底图',
        asset: {
          id: 'a1', filename: 'sofa.png', thumbnail_url: 'https://img/thumb.png',
          public_url: 'https://img/full.png', width: 1200, height: 900,
        },
      },
    })
    const input = wrapper.find('input[type="file"]')
    const clickSpy = vi.spyOn(input.element as HTMLInputElement, 'click')

    await wrapper.find('.image-cell').trigger('click')

    expect(clickSpy).not.toHaveBeenCalled()
  })

  it('cell with asset: replace button opens file picker', async () => {
    const wrapper = mount(ImagePasteCell, {
      props: {
        label: '沙发白底图',
        asset: {
          id: 'a1', filename: 'sofa.png', thumbnail_url: 'https://img/thumb.png',
          public_url: 'https://img/full.png', width: 1200, height: 900,
        },
      },
    })
    const input = wrapper.find('input[type="file"]')
    const clickSpy = vi.spyOn(input.element as HTMLInputElement, 'click')

    const buttons = wrapper.findAll('button')
    const replaceBtn = buttons.find(b => b.text() === '替换')
    expect(replaceBtn).toBeTruthy()
    await replaceBtn!.trigger('click')

    expect(clickSpy).toHaveBeenCalledOnce()
  })

  it('accepts an image via drag-and-drop', async () => {
    const wrapper = mount(ImagePasteCell, { props: { label: '场景参考图' } })
    const file = new File(['image'], 'dropped.png', { type: 'image/png' })

    await wrapper.find('.image-cell').trigger('drop', {
      dataTransfer: {
        files: [file],
        getData: () => '',
        types: ['Files'],
      },
    })

    expect(wrapper.emitted('upload')?.[0]?.[0]).toBe(file)
  })

  it('emits dropAsset when an existing asset is dragged in', async () => {
    const wrapper = mount(ImagePasteCell, {
      props: { label: '场景参考图', assetKind: 'scene_reference' },
    })

    await wrapper.find('.image-cell').trigger('drop', {
      dataTransfer: {
        files: [],
        getData: (key: string) =>
          key === 'application/x-asset-id' ? 'asset-42' : 'scene_reference',
        types: ['application/x-asset-id'],
      },
    })

    expect(wrapper.emitted('dropAsset')?.[0]?.[0]).toBe('asset-42')
  })

  it('emits remove when delete button clicked', async () => {
    const wrapper = mount(ImagePasteCell, {
      props: {
        label: '沙发白底图',
        asset: {
          id: 'a1', filename: 'sofa.png', thumbnail_url: 'https://img/thumb.png',
          public_url: 'https://img/full.png', width: 1200, height: 900,
        },
      },
    })

    await wrapper.find('button.danger').trigger('click')

    expect(wrapper.emitted('remove')).toHaveLength(1)
  })

  it('shows the uploaded thumbnail, filename and dimensions', () => {
    const wrapper = mount(ImagePasteCell, {
      props: {
        label: '沙发白底图',
        asset: {
          id: 'a1', filename: 'sofa.png', thumbnail_url: 'https://img/thumb.png',
          public_url: 'https://img/full.png', width: 1200, height: 900,
        },
      },
    })

    expect(wrapper.find('img').attributes('src')).toBe('https://img/thumb.png')
    expect(wrapper.text()).toContain('sofa.png')
    expect(wrapper.text()).toContain('1200×900')
    expect(wrapper.text()).toContain('替换')
    expect(wrapper.text()).toContain('移除')
  })
})
