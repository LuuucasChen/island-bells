/**
 * 岛屿铃钱记 — API 请求 hook
 */

import { useAuthStore } from '../stores/authStore'

const API_BASE = '/v1'

/** 统一处理响应：检查 401 自动登出，检查其他错误抛出异常 */
async function handleResponse(res: Response) {
  if (res.status === 401) {
    useAuthStore.getState().logout()
    throw new Error('登录已过期，请重新登录')
  }
  const data = await res.json()
  if (!res.ok) {
    throw new Error(data.detail || data.message || `请求失败 (${res.status})`)
  }
  return data
}

export function useApi() {
  const token = useAuthStore((s) => s.token)

  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }

  const get = async (url: string) => {
    const res = await fetch(`${API_BASE}${url}`, { headers })
    return handleResponse(res)
  }

  const post = async (url: string, data?: any) => {
    const res = await fetch(`${API_BASE}${url}`, {
      method: 'POST',
      headers,
      body: data ? JSON.stringify(data) : undefined,
    })
    return handleResponse(res)
  }

  const patch = async (url: string, data?: any) => {
    const res = await fetch(`${API_BASE}${url}`, {
      method: 'PATCH',
      headers,
      body: data ? JSON.stringify(data) : undefined,
    })
    return handleResponse(res)
  }

  const del = async (url: string) => {
    const res = await fetch(`${API_BASE}${url}`, { method: 'DELETE', headers })
    return handleResponse(res)
  }

  return { get, post, patch, del }
}