export type WorkflowStatus = 'running' | 'waiting_for_confirmation' | 'completed' | 'succeeded' | 'rejected' | 'conflict' | 'failed'
export type Decision = 'confirm' | 'reject'
export type Data = Record<string, unknown>
export interface Evidence {
  id: number
  tool_call_id: string
  result: {
    status: 'success' | 'not_found' | 'invalid_argument' | 'forbidden' | 'temporarily_unavailable'
    source: string
    data: Data | Data[] | null
    request_id: string
    queried_at: string
    error: { code: string; message: string } | null
  }
}
export interface FinalResponse {
  kind: 'answer' | 'clarify' | 'reject'
  status: 'ok' | 'partial' | 'unconfirmed' | 'clarify' | 'rejected'
  text: string
  evidence: Evidence[]
  errors: { code: string; tool_call_id?: string | null }[]
  question: string | null
  reason: string | null
}
export interface Receipt {
  status: 'succeeded' | 'rejected' | 'conflict' | 'failed'
  code: string
  operation_id: string
  order_id?: string
  refund_id?: string
  refund_status?: string
  quantity?: number
  amount?: string
  currency?: string
}
export interface Draft {
  operation_id: string
  operation_type: 'request_order_cancellation' | 'create_refund_request'
  actor: string
  target: { order_id: string; order_no: string; order_item_id?: string }
  parameters: { order_no: string; reason: string; order_item_id?: string; quantity?: number; amount?: string }
  current_state: Data
  expected_change: Data
  confirmation_summary: string
}
export interface Workflow {
  thread_id: string
  request_id: string
  confirmation: Decision | null
  status: WorkflowStatus
  operation_id: string | null
  draft: Draft | null
  result: FinalResponse | Receipt | null
}
export interface Turn {
  key: string
  message: string
  threadId?: string
  clarificationThreadId?: string
  workflow?: Workflow
  error?: string
  decision?: Decision
  busy?: 'sending' | 'executing' | 'refreshing'
  unavailable?: boolean
}
export interface Session { id: string; title: string; turns: Turn[] }
export interface ServiceStatus {
  api: 'ok'
  database: 'ok'
  agent_provider: 'fake' | 'configured' | 'not_configured'
  embedding_provider: 'fake' | 'configured' | 'not_configured'
  user: { id: string; display_name: string }
}
