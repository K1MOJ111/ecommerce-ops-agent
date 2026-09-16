<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import EvidenceCard from './components/EvidenceCard.vue'
import ConfirmationCard from './components/ConfirmationCard.vue'
import { useAgent } from './useAgent.ts'
import { answerText, businessEvidence, displayEvidence, evidenceTurn, finalResponse, isBusinessEvidence, label, pendingOperation, toolLabels } from './presentation.ts'
import type { Turn } from './types.ts'

const { history, currentId, current, status, connection, health, connectionError, storageWarning, connecting,
  busy, pending, newSession, selectSession, connect, send, refresh, retry, resume } = useAgent()
const input = ref('')
const selectedKey = ref('')
const selectedEvidence = ref<number>()
const conversation = ref<HTMLElement>()
const composer = ref<HTMLTextAreaElement>()
const operation = computed(() => pendingOperation(current.value?.turns || []))
const operationTarget = computed(() => !operation.value?.unavailable ? operation.value?.workflow?.draft?.target : undefined)
const selectedTurn = computed(() => evidenceTurn(current.value?.turns || [], selectedKey.value))
const evidence = computed(() => !status.value || connecting.value || current.value?.turns.some(t => t.busy === 'refreshing')
  ? [] : displayEvidence(selectedTurn.value, operation.value))
const examples = ['查询商品 纯棉短袖', '查询 SKU 纯棉短袖', '查询库存 纯棉短袖 白色 M', '查询订单 SEED-O003', '查询物流 SEED-O003', '查询七天无理由退货政策']

async function submit() {
  if (!input.value.trim() || busy.value || pending.value || !status.value) return
  const message = input.value
  input.value = ''
  const task = send(message)
  selectedKey.value = ''
  selectedEvidence.value = undefined
  await task
  await nextTick()
  composer.value?.focus()
}
function edit(message: string) { input.value = message; nextTick(() => composer.value?.focus()) }
function keydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit() }
}
function showEvidence(turn: Turn, id: number) {
  if (operation.value) return
  selectedKey.value = turn.key
  selectedEvidence.value = id
  nextTick(() => document.getElementById(`evidence-${turn.key}-${id}`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }))
}
watch(currentId, () => { selectedKey.value = ''; selectedEvidence.value = undefined })
watch(() => current.value?.turns.map(t => [t.busy, t.workflow?.status]), async () => {
  await nextTick()
  conversation.value?.scrollTo({ top: conversation.value.scrollHeight, behavior: 'smooth' })
}, { deep: true })
onMounted(connect)
</script>

<template>
  <div class="workspace" :class="{ 'has-evidence': status && evidence.length }">
    <aside class="sidebar" aria-label="会话历史">
      <div class="brand"><span class="brand-mark">O</span><div>电商运营助手<small>OPS ASSISTANT</small></div></div>
      <button class="new-session" :disabled="busy || !status" @click="newSession(); input = ''; selectedKey = ''">＋ 新建会话</button>
      <p class="sidebar-heading">当前浏览器会话</p>
      <nav class="session-list">
        <p v-if="!history.length" class="history-empty">发送消息后，会话会保存在这里。</p>
        <button v-for="session in history" :key="session.id" :class="{ active: currentId === session.id }" :disabled="busy" @click="selectSession(session.id); selectedKey = ''">
          <span class="session-icon">◷</span><span class="session-title">{{ session.title }}</span>
          <span v-if="session.turns.some(t => t.workflow?.status === 'waiting_for_confirmation')" class="pending-dot" title="等待确认"></span>
        </button>
      </nav>
      <div class="sidebar-bottom"><span class="avatar">{{ status?.user.display_name.slice(-1) || '·' }}</span><div>{{ status?.user.display_name || '身份未连接' }}<small>当前用户 · 服务端提供</small></div></div>
    </aside>

    <main class="main-panel">
      <header class="topbar"><div><span class="eyebrow">工作空间</span><h1>Agent 会话</h1></div>
        <div class="connection"><span v-if="status?.agent_provider === 'fake'" class="provider-badge">开发 · Fake Provider</span><span :class="['connection-dot', { online: status }]"></span><span class="connection-label">{{ connection }}</span><button class="icon-button" aria-label="刷新连接" :disabled="busy" @click="connect">↻</button></div>
      </header>
      <div v-if="connectionError" class="connection-error" role="alert">{{ connectionError }}</div>
      <div v-if="storageWarning" class="connection-error" role="alert">{{ storageWarning }}</div>
      <div v-if="status?.agent_provider === 'not_configured'" class="connection-error">模型尚未配置，暂时无法完成 Agent 请求。</div>

      <section ref="conversation" class="conversation" aria-label="聊天消息" aria-live="polite" aria-relevant="additions text">
        <div v-if="!current?.turns.length" class="empty-chat">
          <div class="assistant-mark">O</div><h2>今天需要处理什么？</h2>
          <p>查商品、库存和订单，或处理取消与退款申请。</p>
          <div class="suggestions"><button v-for="example in examples" :key="example" :disabled="!status || busy" @click="edit(example)">{{ example }} <span>↗</span></button></div>
          <p class="note">写入操作会先生成草稿，等待你确认。</p>
        </div>
        <template v-if="status">
          <article v-for="turn in current?.turns" :key="turn.key" class="turn">
            <div class="message user-message"><span class="message-role">你</span><p>{{ turn.message }}</p></div>
            <div class="message agent-message">
              <span class="message-role">OPS AGENT</span>
              <p v-if="turn.busy" class="loading" role="status">{{ turn.busy === 'sending' ? '正在发送并等待 Agent 处理…' : turn.busy === 'executing' ? '正在执行，等待后端回执…' : '正在刷新请求状态…' }}</p>
              <div v-if="turn.error" class="error-box" role="alert"><strong>System / 请求未完成</strong><p>{{ turn.error }}</p></div>
              <template v-if="turn.workflow && !turn.unavailable">
                <span v-if="finalResponse(turn.workflow) && !['ok', 'clarify'].includes(finalResponse(turn.workflow)!.status)" class="badge">{{ label(finalResponse(turn.workflow)?.status) }}</span>
                <template v-if="finalResponse(turn.workflow)">
                  <p class="answer">{{ answerText(finalResponse(turn.workflow)!) }}</p>
                  <div v-if="finalResponse(turn.workflow)?.kind === 'clarify'" class="clarify-help">
                    <button v-if="turn === current?.turns.at(-1)" class="text-button" :disabled="busy || pending" @click="edit('')">补充信息 ↗</button><span class="note">直接回复补充信息即可，系统会继续原请求</span>
                  </div>
                  <div v-if="businessEvidence(finalResponse(turn.workflow)).length" class="evidence-links"><button v-for="item in businessEvidence(finalResponse(turn.workflow))" :key="item.id" :disabled="!!operation" @click="showEvidence(turn, item.id)">资料 [{{ item.id }}] · {{ toolLabels[item.result.source] || item.result.source }}</button></div>
                </template>
                <ConfirmationCard :turn="turn" :disabled="busy" @decide="resume(turn, $event)" />
                <p v-if="turn.workflow.status === 'running'" class="note">服务端仍在处理。刷新可查看状态；若处理曾中断，可重试原请求。</p>
                <details class="request-details"><summary>技术详情</summary>
                  <details v-if="finalResponse(turn.workflow)?.evidence.length" class="tool-details">
                    <summary>Tool · 查看 {{ finalResponse(turn.workflow)?.evidence.length }} 条返回记录</summary>
                    <div v-for="item in finalResponse(turn.workflow)?.evidence" :key="item.id" class="tool-row"><code>Called {{ item.result.source }}</code><span>{{ label(item.result.status) }}</span><button v-if="isBusinessEvidence(item)" class="text-button" :disabled="!!operation" @click="showEvidence(turn, item.id)">结构化结果 ↗</button><details class="tool-record"><summary>返回记录 [{{ item.id }}]</summary><pre>{{ JSON.stringify(item.result, null, 2) }}</pre></details></div>
                    <p class="note">仅显示接口返回的工具证据；接口未提供实时事件及耗时。</p>
                  </details>
                  <p v-for="(error, index) in finalResponse(turn.workflow)?.errors" :key="index" class="note">{{ error.code }}</p>
                  <dl><dt>thread_id</dt><dd class="identifier">{{ turn.workflow.thread_id }}</dd><dt>request_id</dt><dd class="identifier">{{ turn.workflow.request_id }}</dd><dt>工作流状态</dt><dd>{{ turn.workflow.status }}</dd></dl>
                </details>
              </template>
              <div class="request-actions">
                <button v-if="turn.threadId && (turn.error || turn.unavailable || ['running', 'waiting_for_confirmation'].includes(turn.workflow?.status || ''))" class="text-button" :disabled="busy" @click="refresh(turn)">刷新请求状态</button>
                <button v-if="!turn.workflow || turn.error || turn.workflow.status === 'running'" class="text-button" :disabled="busy || turn.unavailable" @click="retry(turn)">重试原请求</button>
              </div>
            </div>
          </article>
        </template>
      </section>

      <form class="composer" @submit.prevent="submit">
        <div v-if="pending && !busy" class="note">当前请求尚未结束，请先处理确认或刷新状态；也可新建会话。</div>
        <label for="message" class="sr-only">消息</label>
        <textarea id="message" ref="composer" v-model="input" placeholder="输入问题或操作请求…" rows="2" maxlength="10000" :disabled="busy || pending || !status" @keydown="keydown"></textarea>
        <div class="composer-bottom"><span>Enter 发送 · Shift + Enter 换行</span><button type="submit" class="primary" :disabled="busy || pending || !status || !input.trim()">发送 ↑</button></div>
      </form>
    </main>

    <aside class="evidence-panel" aria-label="证据详情">
      <header><span class="eyebrow">查询依据</span><h2>业务资料 <span class="count">{{ evidence.length }}</span></h2><p v-if="operationTarget && status" class="operation-target">当前操作目标：{{ operationTarget.order_no }}</p><p v-if="evidence.length && selectedTurn && status" class="evidence-context">来自：{{ selectedTurn.message }}</p><p v-else-if="!operation">查询结果与来源</p></header>
      <div v-if="!evidence.length || !status" class="empty-evidence"><span>▤</span><p v-if="operation">暂无关联业务资料</p><p v-else>查询后在这里查看<br>商品、订单和政策资料</p></div>
      <template v-else><div v-for="item in evidence" :id="`evidence-${selectedTurn?.key}-${item.id}`" :key="`${selectedTurn?.key}-${item.id}`" :class="{ 'selected-evidence': selectedEvidence === item.id }"><EvidenceCard :evidence="item" /></div></template>
      <footer class="service-info"><p>API · {{ health.api ? 'Connected' : 'Unavailable' }}</p><p>Database · {{ health.database ? 'Connected' : 'Unavailable' }}</p><p>LLM · {{ status?.agent_provider === 'fake' ? 'Fake Provider' : status?.agent_provider === 'configured' ? '已配置（未探测）' : 'Not Configured' }}</p><p>Embedding · {{ status?.embedding_provider === 'fake' ? 'Fake Provider' : status?.embedding_provider === 'configured' ? '已配置（未探测）' : 'Not Configured' }}</p></footer>
    </aside>
  </div>
</template>
