import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'workbench',
      component: () => import('@/views/WorkbenchView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/admin',
      name: 'admin',
      component: () => import('@/views/AdminView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
  ],
})

/**
 * 全局路由守卫。
 * 通过检查 CSRF cookie 是否存在来判断登录态，未登录用户访问受保护页面时重定向到登录页。
 * 这是一种轻量级前端预检，最终的认证由后端 API + axios 401 拦截器保障。
 */
router.beforeEach((to) => {
  if (!to.meta.requiresAuth) return true
  const csrfCookie = document.cookie
    .split('; ')
    .find(row => row.startsWith('spw_csrf='))
  if (!csrfCookie) {
    return { name: 'login' }
  }
  return true
})

export default router
