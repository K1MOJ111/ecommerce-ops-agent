import test from 'node:test'
import assert from 'node:assert/strict'
import { api, ApiError, validateWorkflow } from '../src/api.ts'
import { answerText, businessEvidence, displayEvidence, evidenceTurn, isBusinessEvidence, receiptText } from '../src/presentation.ts'
import type { Evidence, FinalResponse, Turn, Workflow } from '../src/types.ts'

test('request and resume payloads use only public API fields', async () => {
  const calls: { url: string; body: unknown }[] = []
  const original = globalThis.fetch
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), body: JSON.parse(init?.body as string) })
    return new Response(JSON.stringify({ status: 'running', thread_id: 'thread-1', request_id: 'request-1' }))
  }
  try {
    await api.start('same-key', '取消订单')
    await api.start('same-key', '取消订单')
    await api.resume('thread-1', 'op-1', 'confirm')
    await api.resume('thread-1', 'op-1', 'reject')
    await api.start('follow-up-key', 'SEED-O001', 'clarify-thread')
    assert.deepEqual(calls[0].body, { request_key: 'same-key', message: '取消订单' })
    assert.deepEqual(calls[0], calls[1])
    assert.deepEqual(calls[2].body, { operation_id: 'op-1', decision: 'confirm' })
    assert.deepEqual(calls[3].body, { operation_id: 'op-1', decision: 'reject' })
    assert.match(calls[2].url, /threads\/thread-1\/resume$/)
    assert.deepEqual(calls[4].body, { request_key: 'follow-up-key', message: 'SEED-O001', clarification_thread_id: 'clarify-thread' })
  } finally { globalThis.fetch = original }
})

test('incomplete confirmation or success response is never accepted as completed', () => {
  assert.throws(() => validateWorkflow({ status: 'succeeded', thread_id: 't', request_id: 'r' } as Workflow), /尚未确认/)
  assert.throws(() => validateWorkflow({ status: 'waiting_for_confirmation', thread_id: 't', request_id: 'r' } as Workflow), /尚未确认/)
})

test('HTTP failures never expose exception bodies', async () => {
  const original = globalThis.fetch
  try {
    for (const status of [401, 403, 404, 409, 422, 500, 503]) {
      globalThis.fetch = async () => new Response('private SQL traceback secret', { status })
      await assert.rejects(api.get('thread'), (e: ApiError) => e.status === status && !e.message.includes('private'))
    }
    globalThis.fetch = async () => { throw new DOMException('private', 'TimeoutError') }
    await assert.rejects(api.get('thread'), /执行结果尚未确认/)
  } finally { globalThis.fetch = original }
})

test('answer retains warnings and links evidence without dumping structured data', () => {
  const data = { id: 'order-3', order_no: 'SEED-O003', status: 'shipped' }
  const result = { kind: 'answer', status: 'partial', text: '已查询到资料。\n资料 [1] get_order（查询时间 now）：\n' + JSON.stringify(data, null, 2) + '\n本次查询未完整完成，剩余信息无法确认。',
    // PostgreSQL JSONB can reorder keys when a persisted workflow is read back.
    evidence: [{ id: 1, result: { status: 'success', source: 'get_order', data: { status: 'shipped', order_no: 'SEED-O003', id: 'order-3' } } }] } as FinalResponse
  assert.equal(answerText(result), '已查询到资料。\n请查看资料 [1]。\n本次查询未完整完成，剩余信息无法确认。')
  assert.match(receiptText({ status: 'conflict', code: 'business_state_changed', operation_id: 'op' }), /未执行/)
  assert.doesNotMatch(receiptText({ status: 'failed', code: 'business_write_failed', operation_id: 'op' }), /已取消/)
})

test('evidence remains linked after clarification and never crosses unavailable turns or sessions', () => {
  const product = { key: 'product', workflow: { result: { kind: 'answer', evidence: [{ id: 1, result: { status: 'success', source: 'get_product', data: { id: 'p1', name: '测试商品', product_code: 'P1' } } }] } } } as Turn
  const order = { key: 'order', workflow: { result: { kind: 'answer', evidence: [{ id: 1, result: { status: 'success', source: 'get_order', data: { id: 'o1', order_no: 'O1' } } }] } } } as Turn
  const clarify = { key: 'clarify', workflow: { result: { kind: 'clarify', evidence: [] } } } as unknown as Turn
  assert.equal(evidenceTurn([product, order, clarify], ''), order)
  assert.equal(evidenceTurn([product, order, clarify], 'product'), product)
  order.unavailable = true
  assert.equal(evidenceTurn([product, order, clarify], 'order'), product)
  assert.equal(evidenceTurn([clarify], 'product'), undefined)
  assert.equal(evidenceTurn([], 'product'), undefined)
})

test('HITL never falls back to another order, and normal selection resumes after rejection', () => {
  const other = { key: 'other', workflow: { result: { kind: 'answer', evidence: [{ id: 1, result: {
    status: 'success', source: 'get_order', data: { id: 'order-3', order_no: 'SEED-O003' },
  } }] } } } as Turn
  const waiting = { key: 'cancel', workflow: { status: 'waiting_for_confirmation', draft: {
    target: { order_id: 'order-1', order_no: 'SEED-O001' },
  } } } as Turn
  assert.equal(evidenceTurn([other, waiting], 'other'), undefined)
  assert.deepEqual(displayEvidence(other, waiting), [])
  const matching = structuredClone(other)
  matching.key = 'matching'
  const entity = (matching.workflow!.result as FinalResponse).evidence[0].result.data as { id: string; order_no: string }
  entity.id = 'order-1'
  entity.order_no = 'SEED-O001'
  assert.equal(evidenceTurn([matching, other, waiting], 'other'), matching)
  assert.equal(displayEvidence(matching, waiting).length, 1)
  entity.id = 'wrong-id'
  assert.deepEqual(displayEvidence(matching, waiting), [])
  entity.id = 'order-1'
  matching.unavailable = true
  assert.equal(evidenceTurn([matching, other, waiting], ''), undefined)
  matching.unavailable = false
  waiting.unavailable = true
  assert.equal(evidenceTurn([matching, other, waiting], ''), undefined)
  waiting.unavailable = false
  assert.equal(evidenceTurn([waiting], 'matching'), undefined)
  waiting.workflow!.status = 'rejected'
  assert.equal(evidenceTurn([other, waiting], 'other'), other)
})

test('business cards accept entities and citations, excluding failed, empty and insufficient records', () => {
  const record = (source: string, data: unknown, status = 'success', error: unknown = null) => ({ id: 1, result: { source, data, status, error } }) as Evidence
  const product = record('search_products', [{ id: 'p1', name: '测试商品', product_code: 'P1' }])
  const valid = [product, record('get_product', product.result.data![0]),
    record('list_product_skus', [{ id: 's1', sku_code: 'S1' }]), record('get_order', { id: 'o1', order_no: 'O1' }),
    record('get_inventory', { sku_id: 's1', stocks: [{ warehouse_code: 'W1', available: 0 }] }),
    record('get_logistics', { order_id: 'o1', packages: [{ id: 'parcel1', status: 'pending' }] }),
    record('search_after_sales_policy', [{ document_id: 'd1', chunk_id: 'c1', title: '测试政策', content: '测试原文', locator: '段落1', citation: '测试引用', source_uri: 'fixture://policy', version: 1 }])]
  for (const item of valid) assert.equal(isBusinessEvidence(item), true, item.result.source)
  const invalid = ['not_found', 'forbidden', 'invalid_argument', 'temporarily_unavailable', 'evidence_insufficient']
    .map(status => record('search_products', product.result.data, status))
  invalid.push(record('search_products', product.result.data, 'success', { code: 'evidence_insufficient' }))
  for (const data of [null, [], {}, [{ message: '没有找到资料' }], [null]]) invalid.push(record('search_products', data))
  invalid.push(record('get_inventory', { sku_id: 's1', stocks: [] }), record('get_logistics', { order_id: 'o1', packages: [] }),
    record('search_after_sales_policy', [{ title: '没有找到政策', citation: '' }]))
  for (const item of invalid) assert.equal(isBusinessEvidence(item), false, JSON.stringify(item))
  const response = { kind: 'answer', status: 'partial', evidence: [...valid, ...invalid] } as FinalResponse
  assert.deepEqual(businessEvidence(response), valid)
  assert.equal(response.evidence.length, valid.length + invalid.length) // Technical records remain intact.
  const empty = { ...response, evidence: [record('search_products', [])], text: '资料 [1] search_products（查询时间 now）：\n[]' }
  assert.equal(answerText(empty), '返回记录 [1] 见技术详情。')
  assert.equal(evidenceTurn([{ key: 'empty', workflow: { result: empty } } as Turn], ''), undefined)
})
