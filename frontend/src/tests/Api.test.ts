import type { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'
import { isAuthenticationRedirectRequired } from '@/services/api'

/**
 * 创建认证异常测试数据。
 * @param url - 请求地址。
 * @param status - HTTP 状态码。
 * @returns Axios 异常测试对象。
 */
function createAxiosError(url: string, status: number): AxiosError {
  return {
    config: { url },
    response: { status },
  } as AxiosError
}

describe('API authentication redirect', () => {
  it('does not redirect when the login request itself returns 401', () => {
    expect(isAuthenticationRedirectRequired(createAxiosError('/api/v1/auth/login', 401))).toBe(false)
  })

  it('redirects when another API request returns 401', () => {
    expect(isAuthenticationRedirectRequired(createAxiosError('/api/v1/rows', 401))).toBe(true)
  })
})
