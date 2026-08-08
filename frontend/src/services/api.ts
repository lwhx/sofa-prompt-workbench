import axios from 'axios'
import type { AxiosError, AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

export const api = axios.create({
  baseURL: '/',
  withCredentials: true,
  xsrfCookieName: 'spw_csrf',
  xsrfHeaderName: 'X-CSRF-Token',
  timeout: 30000,
})

/** 需要更长超时的接口路径片段（AI 运行等耗时操作）。 */
const LONG_TIMEOUT_PATTERNS = ['/run']

/**
 * 根据请求路径自动放宽超时。
 * AI 运行等耗时接口后端超时可达 240s，前端需匹配。
 */
api.interceptors.request.use((config) => {
  const url = config.url ?? ''
  if (LONG_TIMEOUT_PATTERNS.some((p) => url.includes(p))) {
    config.timeout = 300000
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      window.location.href = '/login'
      return Promise.reject(error)
    }
    /** 对非 401 的常见错误统一提示一次，业务层可不再重复处理。 */
    if (error.response?.status === 403) {
      ElMessage.error('没有权限执行此操作')
    } else if (error.code === 'ECONNABORTED') {
      ElMessage.error('请求超时，请检查网络后重试')
    } else if (error.code === 'ERR_NETWORK') {
      ElMessage.error('网络连接失败，请检查网络后重试')
    }
    return Promise.reject(error)
  },
)

/**
 * 从 axios 错误或普通错误中提取用户可读的消息。
 * @param reason - 捕获到的异常对象。
 * @param fallback - 无法提取具体原因时的兜底文案。
 * @returns 适合展示给用户的错误消息。
 */
export function extractApiError(reason: unknown, fallback: string): string {
  const err = reason as {
    response?: { data?: { error?: { message?: string }; message?: string } }
    message?: string
  }
  return (
    err?.response?.data?.error?.message
    || err?.response?.data?.message
    || fallback
  )
}

export type { AxiosRequestConfig }
