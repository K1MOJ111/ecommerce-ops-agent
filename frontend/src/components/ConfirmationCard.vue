<script setup lang="ts">
import type { Decision, Turn } from '../types.ts'
import { label, receiptText } from '../presentation.ts'
defineProps<{ turn: Turn; disabled: boolean }>()
defineEmits<{ decide: [decision: Decision] }>()
</script>

<template>
  <section v-if="turn.workflow?.draft" class="confirmation-card" aria-label="操作确认">
    <div class="eyebrow">HITL · 人工确认</div>
    <h3>{{ turn.workflow.draft.operation_type === 'request_order_cancellation' ? '取消订单' : '创建退款申请' }}</h3>
    <span class="badge" role="status">{{ label(turn.workflow.status) }}</span>
    <p>{{ turn.workflow.draft.confirmation_summary }}</p>
    <dl>
      <dt>订单</dt><dd>{{ turn.workflow.draft.target.order_no }}</dd>
      <dt>目标资源</dt><dd>{{ turn.workflow.draft.target.order_item_id ? '订单明细' : '订单' }}</dd>
      <template v-if="turn.workflow.draft.target.order_item_id"><dt>明细编号</dt><dd class="identifier">{{ turn.workflow.draft.target.order_item_id }}</dd></template>
      <dt>草稿时订单状态</dt><dd>{{ label(turn.workflow.draft.current_state.order_status) }}</dd>
      <dt>付款状态</dt><dd>{{ label(turn.workflow.draft.current_state.payment_status) }}</dd>
      <template v-if="turn.workflow.draft.parameters.quantity"><dt>申请数量</dt><dd>{{ turn.workflow.draft.parameters.quantity }}</dd></template>
      <template v-if="turn.workflow.draft.parameters.amount"><dt>申请金额</dt><dd>{{ turn.workflow.draft.parameters.amount }} {{ turn.workflow.draft.current_state.currency }}</dd></template>
      <dt>原因</dt><dd>{{ turn.workflow.draft.parameters.reason }}</dd>
      <dt>操作编号</dt><dd class="identifier">{{ turn.workflow.operation_id }}</dd>
    </dl>
    <p v-if="turn.busy === 'executing'" role="status">已提交{{ turn.decision === 'confirm' ? '确认' : '拒绝' }}选择，正在等待后端处理结果…</p>
    <template v-else-if="turn.workflow.status === 'waiting_for_confirmation'">
      <p class="note">确认后服务端会重新校验。只有收到成功回执，才会显示完成。</p>
      <p v-if="turn.decision" class="note">已选择{{ turn.decision === 'confirm' ? '确认' : '拒绝' }}；如响应中断，只能重试同一选择。</p>
      <div class="actions">
        <button class="primary" :disabled="disabled || turn.decision === 'reject'" @click="$emit('decide', 'confirm')">确认执行 / Confirm</button>
        <button :disabled="disabled || turn.decision === 'confirm'" @click="$emit('decide', 'reject')">拒绝 / Reject</button>
      </div>
    </template>
    <p v-if="turn.workflow.result && !('kind' in turn.workflow.result)" class="receipt" role="status">{{ receiptText(turn.workflow.result) }}</p>
  </section>
</template>
