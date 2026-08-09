import { flushPromises, mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/** 管理接口 GET mock。 */
const get = vi.fn()
/** 管理接口 POST mock。 */
const post = vi.fn()
/** 管理接口 PUT mock。 */
const put = vi.fn()
/** 管理接口 DELETE mock。 */
const deleteRequest = vi.fn()

vi.mock('@/services/api', () => ({
  api: { get, post, put, delete: deleteRequest },
  /** 提取 API 错误消息的 mock：直接返回兜底文案。 */
  extractApiError: vi.fn((reason: unknown, fallback: string) => {
    const err = reason as { response?: { data?: { error?: { message?: string } } } }
    return err?.response?.data?.error?.message || fallback
  }),
}))

/** Element Plus 消息提示 mock。 */
const message = vi.hoisted(() => ({
  success: vi.fn(),
  warning: vi.fn(),
  error: vi.fn(),
}))
/** Element Plus 确认框 mock。 */
const messageBox = vi.hoisted(() => ({ confirm: vi.fn() }))

vi.mock('element-plus', async (importOriginal) => {
  /** Element Plus 原始模块。 */
  const original = await importOriginal<typeof import('element-plus')>()
  return { ...original, ElMessage: message, ElMessageBox: messageBox }
})

/** 提示词模板测试数据。 */
const template = {
  id: 'template-1',
  name: '正式模板',
  version: 3,
  is_active: false,
  created_at: '2026-08-05T10:00:00Z',
}

/**
 * 挂载管理页面。
 * @returns 管理页面测试包装器。
 */
async function mountAdminView() {
  const AdminView = (await import('@/views/AdminView.vue')).default
  /** 管理页面测试包装器。 */
  const wrapper = mount(AdminView, {
    global: {
      plugins: [ElementPlus],
      stubs: {
        ElTag: false,
        ElInput: false,
        ElFormItem: false,
        ElForm: false,
        ElOption: false,
        ElSelect: false,
        ElTableColumn: false,
        ElTable: false,
      },
    },
  })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  get.mockReset()
  post.mockReset()
  put.mockReset()
  deleteRequest.mockReset()
  messageBox.confirm.mockReset()
  Object.values(message).forEach(mock => mock.mockReset())
  get.mockResolvedValue({ data: { data: [template] } })
  post.mockResolvedValue({ data: { data: {} } })
  put.mockResolvedValue({ data: { data: {} } })
  deleteRequest.mockResolvedValue({ data: { data: {} } })
  messageBox.confirm.mockResolvedValue(undefined)
})

describe('AdminView', () => {
  it('renders three admin tabs and loads prompt templates', async () => {
    const wrapper = await mountAdminView()

    expect(wrapper.text()).toContain('提示词模板')
    expect(wrapper.text()).toContain('AI 能力')
    expect(wrapper.text()).toContain('审计日志')
    expect(wrapper.text()).toContain('正式模板')
    expect(wrapper.text()).toContain('v3')
    expect(get).toHaveBeenCalledWith('/api/v1/admin/prompt-templates')
  })

  it('activates a template and tests AI capability with expected endpoints', async () => {
    const wrapper = await mountAdminView()
    /** 页面暴露的交互方法。 */
    const view = wrapper.vm as unknown as {
      activateTemplate: (item: typeof template) => Promise<void>
      testCapability: () => Promise<void>
    }

    await view.activateTemplate(template)
    await view.testCapability()

    expect(post).toHaveBeenCalledWith('/api/v1/admin/prompt-templates/template-1/activate')
    expect(post).toHaveBeenCalledWith('/api/v1/admin/ai-capability/test')
    expect(message.success).toHaveBeenCalled()
  })

  it('saves editable AI capability configuration with expected contract', async () => {
    const wrapper = await mountAdminView()
    /** 页面暴露的配置表单与保存方法。 */
    const view = wrapper.vm as unknown as {
      capability: { api_key_configured: boolean }
      capabilityForm: {
        provider: string
        baseUrl: string
        apiKey: string
        model: string
        chatPath: string
        timeoutSeconds: number
      }
      saveCapability: () => Promise<void>
    }
    view.capability.api_key_configured = false
    Object.assign(view.capabilityForm, {
      provider: 'openai-compatible',
      baseUrl: 'https://api.example.com/v1',
      apiKey: 'secret-key',
      model: 'vision-model',
      chatPath: '/chat/completions',
      timeoutSeconds: 180,
    })

    await view.saveCapability()

    expect(put).toHaveBeenCalledWith('/api/v1/admin/ai-capability', {
      provider: 'openai-compatible',
      base_url: 'https://api.example.com/v1',
      api_key: 'secret-key',
      model: 'vision-model',
      chat_path: '/chat/completions',
      timeout_seconds: 180,
    })
    expect(message.success).toHaveBeenCalledWith('AI 配置已保存并立即生效')
  })

  it('deletes AI capability configuration after confirmation', async () => {
    const wrapper = await mountAdminView()
    const view = wrapper.vm as unknown as { deleteCapability: () => Promise<void> }

    await view.deleteCapability()

    expect(messageBox.confirm).toHaveBeenCalled()
    expect(deleteRequest).toHaveBeenCalledWith('/api/v1/admin/ai-capability')
    expect(message.success).toHaveBeenCalledWith('AI 配置已删除')
  })

  it('reports unavailable AI connection as failure', async () => {
    post.mockResolvedValueOnce({ data: { data: { status: 'UNAVAILABLE', details: { http_status: 401 } } } })
    const wrapper = await mountAdminView()
    const view = wrapper.vm as unknown as { testCapability: () => Promise<void> }

    await view.testCapability()

    expect(message.error).toHaveBeenCalledWith('AI 连接测试失败：HTTP 401')
    expect(message.success).not.toHaveBeenCalledWith('AI 连接测试成功')
  })

  it('shows API errors through ElMessage', async () => {
    get.mockRejectedValueOnce({ response: { data: { error: { message: '无权访问管理功能' } } } })

    await mountAdminView()

    expect(message.error).toHaveBeenCalledWith('无权访问管理功能')
  })
})
