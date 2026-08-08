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
      },
      global: {
        stubs: { ElDialog: { template: '<div><slot /></div>' }, ElButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' } },
        directives: { loading: () => undefined },
      },
    })

    await wrapper.findAll('button')[0].trigger('click')
    expect(writeText).toHaveBeenCalledWith('正向')
  })
})