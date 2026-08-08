import { describe, expect, it } from 'vitest'
import { h, nextTick, type VNode } from 'vue'
import type { ICellRendererParams } from 'ag-grid-community'
import { createVueCellRenderer, resolvePasteTarget } from '@/views/vueCellRenderer'

/**
 * AG Grid class-based Vue 单元格渲染器测试。
 * 验证 init/getGui/refresh/destroy 生命周期正确性。
 */
describe('createVueCellRenderer', () => {
  /** 简单渲染函数：显示 data 中的 text 字段 */
  function simpleRenderer(data: unknown): VNode {
    return h('span', { class: 'test-cell' }, String((data as { text?: string })?.text ?? ''))
  }

  it('init creates a GUI element with mounted content', () => {
    const RendererClass = createVueCellRenderer(simpleRenderer)
    const instance = new RendererClass()
    const params = { data: { text: 'hello' } } as unknown as ICellRendererParams

    instance.init(params)
    const gui = instance.getGui()

    expect(gui).toBeInstanceOf(HTMLElement)
    expect(gui.querySelector('.test-cell')?.textContent).toBe('hello')
  })

  it('refresh updates reactive data and re-renders', async () => {
    const RendererClass = createVueCellRenderer(simpleRenderer)
    const instance = new RendererClass()
    instance.init({ data: { text: 'old' } } as unknown as ICellRendererParams)

    instance.refresh({ data: { text: 'new' } } as unknown as ICellRendererParams)
    await nextTick()

    expect(instance.getGui().querySelector('.test-cell')?.textContent).toBe('new')
  })

  it('destroy unmounts the Vue app without errors', () => {
    const RendererClass = createVueCellRenderer(simpleRenderer)
    const instance = new RendererClass()
    instance.init({ data: { text: 'bye' } } as unknown as ICellRendererParams)

    expect(() => instance.destroy()).not.toThrow()
  })
})

/**
 * 粘贴路由逻辑测试。
 * 验证根据 AG Grid 焦点单元格和剪贴板内容，正确推导上传目标。
 */
describe('resolvePasteTarget', () => {
  const imageFile = new File(['img'], 'paste.png', { type: 'image/png' })
  const textFile = new File(['txt'], 'note.txt', { type: 'text/plain' })

  it('routes image paste to scene_asset column', () => {
    const result = resolvePasteTarget([imageFile], { colId: 'scene_asset', rowId: 'r1' })
    expect(result).toEqual({ kind: 'scene_reference', file: imageFile, rowId: 'r1' })
  })

  it('routes image paste to sofa_asset column', () => {
    const result = resolvePasteTarget([imageFile], { colId: 'sofa_asset', rowId: 'r2' })
    expect(result).toEqual({ kind: 'sofa_product', file: imageFile, rowId: 'r2' })
  })

  it('returns null when no cell is focused', () => {
    const result = resolvePasteTarget([imageFile], null)
    expect(result).toBeNull()
  })

  it('returns null for non-image files', () => {
    const result = resolvePasteTarget([textFile], { colId: 'scene_asset', rowId: 'r1' })
    expect(result).toBeNull()
  })

  it('returns null for non-image columns', () => {
    const result = resolvePasteTarget([imageFile], { colId: 'name', rowId: 'r1' })
    expect(result).toBeNull()
  })
})
