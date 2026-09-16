import type { Decision, ServiceStatus, Workflow } from './types.ts'

export const API_BASE = (import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const errors: Record<number, string> = {
  401: '尚未配置可用身份，请检查后端的本地用户设置。',
  403: '无权访问该请求或资源，无法确认其是否存在。',
  404: '未找到该接口或请求，请检查 API 地址。',
  409: '请求或业务状态已变化，请刷新状态后核对。',
  422: '请求参数不完整或格式有误，请检查后重试。',
  500: '服务暂时出错，请稍后刷新请求状态。',
  503: '服务暂时不可用，请检查连接并刷新请求状态。',
}
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}
export async function request<T>(path: string, body?: unknown): Promise<T> {
  try {
    const response = await fetch(API_BASE + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(100_000), cache: 'no-store', credentials: 'omit',
    })
    if (!response.ok) throw new ApiError(response.status, errors[response.status] || '请求失败，请稍后重试。')
    return await response.json() as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && ['TimeoutError', 'AbortError'].includes(error.name)) {
      throw new ApiError(0, '等待响应超时，执行结果尚未确认。请刷新或重试原请求，不要重复创建操作。')
    }
    throw new ApiError(0, '无法连接服务或响应无效。请检查 API 连接，再刷新或重试原请求。')
  }
}
export const api = {
  live: () => request<{ api: 'ok' }>('/health/live'),
  health: () => request<{ api: 'ok'; database: 'ok' | 'unavailable' }>('/health'),
  status: () => request<ServiceStatus>('/status'),
  start: (key: string, message: string, clarificationThreadId?: string) => request<Workflow>('/agent/requests', {
    request_key: key, message, ...(clarificationThreadId ? { clarification_thread_id: clarificationThreadId } : {}),
  }).then(validateWorkflow),
  get: (thread: string) => request<Workflow>(`/agent/threads/${encodeURIComponent(thread)}`).then(validateWorkflow),
  resume: (thread: string, operation: string, decision: Decision) => request<Workflow>(`/agent/threads/${encodeURIComponent(thread)}/resume`, { operation_id: operation, decision }).then(validateWorkflow),
}

export function validateWorkflow(value: Workflow): Workflow {
  const invalid = () => { throw new ApiError(0, '服务响应格式不完整，执行结果尚未确认，请刷新状态。') }
  if (!value || typeof value.thread_id !== 'string' || typeof value.request_id !== 'string'
    || !['running', 'waiting_for_confirmation', 'completed', 'succeeded', 'rejected', 'conflict', 'failed'].includes(value.status)) invalid()
  if (value.status === 'waiting_for_confirmation' && (!value.operation_id || !value.draft
    || value.draft.operation_id !== value.operation_id || !value.draft.target?.order_no
    || !value.draft.parameters || !value.draft.current_state)) invalid()
  if (value.result && 'kind' in value.result) {
    if (typeof value.result.text !== 'string' || !Array.isArray(value.result.evidence) || !Array.isArray(value.result.errors)) invalid()
  } else if (['succeeded', 'rejected', 'conflict', 'failed'].includes(value.status)) {
    if (!value.result || value.result.status !== value.status || value.result.operation_id !== value.operation_id) invalid()
  }
  return value
}
