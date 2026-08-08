import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createRouter, createMemoryHistory } from 'vue-router'

vi.mock('@/services/api', () => ({
  api: { post: vi.fn().mockResolvedValue({ data: { data: { username: 'admin' } } }) },
}))

describe('LoginView', () => {
  it('renders username password and login action', async () => {
    const LoginView = (await import('@/views/LoginView.vue')).default
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/', component: { template: '<div />' } }],
    })
    const wrapper = mount(LoginView, {
      global: { plugins: [router] },
    })

    expect(wrapper.text()).toContain('管理员登录')
    expect(wrapper.find('input[name="username"]').element).toHaveProperty('value', '')
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.find('button').text()).toContain('登录')
  })
})