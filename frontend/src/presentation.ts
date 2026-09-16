import type { Data, Evidence, FinalResponse, Receipt, Turn, Workflow } from './types.ts'

export function finalResponse(workflow?: Workflow): FinalResponse | undefined {
  return workflow?.result && 'kind' in workflow.result ? workflow.result : undefined
}
export function isBusinessEvidence(evidence: Evidence): boolean {
  const { status, source, data, error } = evidence.result
  if (status !== 'success' || error || !data) return false
  const fields = (row: Data, ...keys: string[]) => keys.every(key => typeof row[key] === 'string' && (row[key] as string).trim())
  const records = (value: unknown, valid: (row: Data) => boolean): boolean => Array.isArray(value) && value.length > 0
    && value.every(row => row && typeof row === 'object' && valid(row))
  const valid = (row: Data): boolean => {
    switch (source) {
      case 'search_products': case 'get_product': return fields(row, 'id', 'product_code', 'name')
      case 'list_product_skus': return fields(row, 'id', 'sku_code')
      case 'get_order': return fields(row, 'id', 'order_no')
      case 'get_inventory': return fields(row, 'sku_id') && records(row.stocks, stock => fields(stock, 'warehouse_code') && typeof stock.available === 'number' && Number.isFinite(stock.available))
      case 'get_logistics': return fields(row, 'order_id') && records(row.packages, parcel => fields(parcel, 'id', 'status'))
      case 'search_after_sales_policy': return fields(row, 'document_id', 'chunk_id', 'title', 'content', 'locator', 'citation', 'source_uri') && Number.isInteger(row.version) && Number(row.version) > 0
      default: return false
    }
  }
  // Successful empty lookups are still tool records, not business cards.
  return records(Array.isArray(data) ? data : [data], valid)
}
export const businessEvidence = (result?: FinalResponse) => result?.evidence.filter(isBusinessEvidence) || []
export const pendingOperation = (turns: Turn[]) => [...turns].reverse().find(turn => turn.workflow?.status === 'waiting_for_confirmation')
export function displayEvidence(turn?: Turn, operation?: Turn): Evidence[] {
  if (!turn || turn.unavailable) return []
  const evidence = businessEvidence(finalResponse(turn.workflow))
  if (!operation) return evidence
  const target = operation.unavailable ? undefined : operation.workflow?.draft?.target
  if (!target?.order_id || !target.order_no) return []
  // Only backend order evidence with the draft's identity may accompany confirmation.
  return evidence.filter(item => item.result.source === 'get_order' && !Array.isArray(item.result.data)
    && item.result.data?.id === target.order_id && item.result.data?.order_no === target.order_no)
}
export function evidenceTurn(turns: Turn[], selectedKey: string): Turn | undefined {
  const operation = pendingOperation(turns)
  const available = (turn: Turn) => displayEvidence(turn, operation).length > 0
  return (!operation ? turns.find(turn => turn.key === selectedKey && available(turn)) : undefined)
    || [...turns].reverse().find(available)
}
export const statusLabels: Record<string, string> = {
  running: '处理中', waiting_for_confirmation: '等待人工确认', completed: '请求完成',
  succeeded: '执行成功', rejected: '已拒绝', conflict: '业务状态冲突', failed: '执行失败',
  ok: '已回复', partial: '部分结果', unconfirmed: '证据不足', clarify: '需要补充信息',
  success: '成功', not_found: '未找到资料', forbidden: '无权访问', invalid_argument: '参数无效',
  temporarily_unavailable: '服务暂不可用', pending_payment: '待付款', unpaid: '未付款',
  paid: '已付款', partially_refunded: '部分退款', cancelled: '已取消', pending_fulfillment: '待发货',
  partially_shipped: '部分发货', shipped: '已发货', in_transit: '运输中', delivered: '已送达',
  requested: '已提交申请', pending: '待处理',
}
export const label = (value: unknown) => value == null ? '未提供' : statusLabels[String(value)] || String(value)
export const toolLabels: Record<string, string> = {
  search_products: '商品', get_product: '商品详情', list_product_skus: '商品规格', get_inventory: '库存',
  get_order: '订单', get_logistics: '物流', search_after_sales_policy: '售后政策',
}
export function answerText(result: FinalResponse): string {
  // Match the backend renderer's complete top-level JSON blocks; JSONB reorders object keys on replay.
  return result.text.replace(
    /^资料 \[(\d+)\] ([a-z_]+)（查询时间 [^\n]+）：\n(\[\]|\{\}|\[[\s\S]*?^\]|\{[\s\S]*?^\})/gm,
    (block, id: string, source: string, data: string) => {
      if (!result.evidence.some(e => e.id === Number(id) && e.result.source === source && e.result.status === 'success')) return block
      try { JSON.parse(data) } catch { return block }
      return businessEvidence(result).some(e => e.id === Number(id))
        ? `请查看资料 [${id}]。` : `返回记录 [${id}] 见技术详情。`
    },
  )
}
export function receiptText(result: Receipt): string {
  if (result.status === 'succeeded' && result.code === 'order_cancelled') return '订单已取消。后端已完成执行。'
  if (result.status === 'succeeded' && result.code === 'refund_request_created') return `退款申请已创建，状态：待处理。申请金额 ${result.amount} ${result.currency}，数量 ${result.quantity}。尚未审批或打款。`
  if (result.status === 'rejected') return '已拒绝本次操作，未执行取消或退款申请。'
  if (result.status === 'conflict') return '订单或可申请额度已变化，本次操作未执行。请重新查询，再发起新的申请。'
  return '本次操作执行失败。请核对状态后再处理。'
}
