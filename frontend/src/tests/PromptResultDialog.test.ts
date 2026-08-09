import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import PromptResultDialog from '@/components/PromptResultDialog.vue'

describe('PromptResultDialog', () => {
  it('displays reverse positive and negative prompts with copy actions', () => {
    const wrapper = mount(PromptResultDialog, {
      props: {
        modelValue: true,
        results: [{
          id: 'r1', version: 3, positive_prompt: '完整即梦反推提示词',
          negative_prompt: '不要镜像', review_status: 'PASSED',
          review: { required: false, reasons: [] }, warnings: [], is_stale: false,
        }],
        loading: false,
        rowId: 'row-1',
        rowRevision: 1,
        selectedResultId: null,
      },
      global: {
        stubs: { ElDialog: { template: '<div><slot /></div>' }, ElButton: { template: '<button><slot /></button>' } },
        directives: { loading: () => undefined },
      },
    })

    expect(wrapper.find('textarea[aria-label="即梦完整提示词"]').attributes('value')).toBe('完整即梦反推提示词')
    expect(wrapper.find('textarea[aria-label="反向提示词"]').attributes('value')).toBe('不要镜像')
    expect(wrapper.text()).toContain('复制正向提示词')
    expect(wrapper.text()).toContain('复制反向提示词')
    expect(wrapper.text()).toContain('版本 3')
  })

  it('copies the selected prompt', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    const wrapper = mount(PromptResultDialog, {
      props: {
        modelValue: true,
        results: [{
          id: 'r1', version: 1, positive_prompt: '正向', negative_prompt: '反向',
          review_status: 'PASSED', review: {}, warnings: [], is_stale: false,
        }],
        loading: false,
        rowId: 'row-1',
        rowRevision: 1,
        selectedResultId: null,
      },
      global: {
        stubs: { ElDialog: { template: '<div><slot /></div>' }, ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' } },
        directives: { loading: () => undefined },
      },
    })

    await wrapper.findAll('button')[0].trigger('click')
    expect(writeText).toHaveBeenCalledWith('正向')
  })

  it('selects a result as the formal version', async () => {
    const api = await import('@/services/api')
    const post = vi.spyOn(api.api, 'post').mockResolvedValue({ data: { data: {} } })
    const wrapper = mount(PromptResultDialog, {
      props: {
        modelValue: true,
        results: [{
          id: 'r1', version: 1, positive_prompt: '正向', negative_prompt: '反向',
          review_status: 'PASSED', review: {}, warnings: [], is_stale: false,
        }],
        loading: false,
        rowId: 'row-1',
        rowRevision: 3,
        selectedResultId: null,
      },
      global: {
        stubs: {
          ElDialog: { template: '<div><slot /><slot name="footer" /></div>' },
          ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
          ElTag: { template: '<span><slot /></span>' },
          ElForm: { template: '<form><slot /></form>' },
          ElFormItem: { template: '<div><slot /></div>' },
          ElInput: { template: '<input />' },
        },
        directives: { loading: () => undefined },
      },
    })

    const button = wrapper.findAll('button').find(item => item.text() === '选为正式版')
    await button?.trigger('click')

    expect(post).toHaveBeenCalledWith('/api/v1/rows/row-1/results/r1/select', { expected_revision: 3 })
    expect(wrapper.emitted('changed')?.length).toBeGreaterThanOrEqual(1)
  })
})
