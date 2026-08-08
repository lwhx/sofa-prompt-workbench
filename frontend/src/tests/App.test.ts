import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import App from '@/App.vue'

/**
 * 创建 App 导航测试路由。
 * @returns 内存模式路由实例。
 */
function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div>工作台页面</div>' } },
      { path: '/admin', component: { template: '<div>管理页面</div>' } },
      { path: '/login', component: { template: '<div>登录页面</div>' } },
    ],
  })
}

describe('App', () => {
  it('hides primary navigation on the login page', async () => {
    /** App 导航测试路由。 */
    const router = createTestRouter()
    await router.push('/login')
    await router.isReady()
    const wrapper = mount(App, {
      global: { plugins: [router] },
    })
    /** 顶部导航链接。 */
    const links = wrapper.findAll('.app-nav a')

    expect(wrapper.text()).toContain('沙发场景提示词工作台')
    expect(links).toHaveLength(0)
    expect(wrapper.text()).toContain('登录页面')
  })

  it('shows primary navigation on authenticated pages', async () => {
    const router = createTestRouter()
    await router.push('/')
    await router.isReady()
    const wrapper = mount(App, { global: { plugins: [router] } })
    const links = wrapper.findAll('.app-nav a')

    expect(links.map(link => link.text())).toEqual(['工作台', '系统管理'])
    expect(links.map(link => link.attributes('href'))).toEqual(['/', '/admin'])
  })
})
