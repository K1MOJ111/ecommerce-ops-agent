import { computed, ref, watch } from 'vue'
import { api, API_BASE, ApiError } from './api.ts'
import { finalResponse } from './presentation.ts'
import type { Decision, Session, ServiceStatus, Turn } from './types.ts'

export function useAgent() {
  const sessions = ref<Session[]>([])
  const currentId = ref('')
  const status = ref<ServiceStatus>()
  const connection = ref('正在连接')
  const health = ref({ api: false, database: false })
  const connectionError = ref('')
  const storageWarning = ref('')
  const connecting = ref(false)
  const current = computed(() => sessions.value.find(s => s.id === currentId.value))
  const history = computed(() => sessions.value.filter(s => s.turns.length))
  const busy = computed(() => connecting.value || sessions.value.some(s => s.turns.some(t => t.busy)))
  const pending = computed(() => current.value?.turns.some(t => !t.workflow || ['running', 'waiting_for_confirmation'].includes(t.workflow.status)))
  const storageKey = `ops-session:${API_BASE}`
  let owner = ''

  function save() {
    if (!owner) return
    try {
      // Cache request references only; reload always reauthorizes and fetches server evidence.
      sessionStorage.setItem(storageKey, JSON.stringify({ owner, currentId: currentId.value,
        sessions: history.value.map(s => ({ id: s.id, title: s.title, turns: s.turns.map(t => ({
          key: t.key, message: t.message, threadId: t.threadId, decision: t.decision, clarificationThreadId: t.clarificationThreadId,
        })) })),
      }))
    } catch { storageWarning.value = '浏览器无法保存会话，请保持当前页面打开。' }
  }
  watch([sessions, currentId], save, { deep: true })

  function newSession() {
    const empty = sessions.value.find(s => !s.turns.length)
    if (empty) { currentId.value = empty.id; return }
    const session: Session = { id: crypto.randomUUID(), title: '新会话', turns: [] }
    sessions.value.push(session)
    currentId.value = session.id
  }

  async function execute(turn: Turn, action: 'start' | 'get' | 'resume', decision?: Decision) {
    if (turn.busy || !status.value) return
    turn.busy = action === 'start' ? 'sending' : action === 'resume' ? 'executing' : 'refreshing'
    turn.error = undefined
    if (action === 'get') turn.unavailable = true
    if (decision) turn.decision = decision
    save() // Persist the first local choice before any response can be lost.
    try {
      const workflow = action === 'start' ? await api.start(turn.key, turn.message, turn.clarificationThreadId)
        : action === 'get' ? await api.get(turn.threadId!)
        : await api.resume(turn.threadId!, turn.workflow!.operation_id!, turn.decision!)
      turn.workflow = workflow
      turn.threadId = workflow.thread_id
      turn.decision = workflow.confirmation || turn.decision
      turn.unavailable = false
    } catch (error) {
      turn.error = error instanceof ApiError ? error.message : '无法读取请求状态，请刷新后重试。'
      if (action === 'get' || (error instanceof ApiError && [401, 403].includes(error.status))) {
        turn.unavailable = true
        turn.workflow = undefined
      }
    } finally { turn.busy = undefined; save() }
  }

  async function selectSession(id: string) {
    currentId.value = id
    for (const turn of current.value?.turns || []) {
      if (turn.threadId) await execute(turn, 'get')
    }
  }
  async function connect() {
    if (connecting.value) return
    connecting.value = true
    status.value = undefined
    health.value = { api: false, database: false }
    connectionError.value = ''
    try {
      await api.live()
      health.value.api = true
      await api.health()
      health.value.database = true
      connection.value = 'API / 数据库已连接'
      const next = await api.status()
      status.value = next
      if (owner && owner !== next.user.id) sessions.value = []
      owner = next.user.id
      if (!sessions.value.length) {
        try {
          const saved = JSON.parse(sessionStorage.getItem(storageKey) || 'null')
          if (saved?.owner === owner && Array.isArray(saved.sessions)) {
            sessions.value = saved.sessions.filter((s: Session) => typeof s.id === 'string' && typeof s.title === 'string' && Array.isArray(s.turns))
              .map((s: Session) => ({ id: s.id, title: s.title, turns: s.turns.filter(t => typeof t.key === 'string' && typeof t.message === 'string')
                .map(t => ({ key: t.key, message: t.message, threadId: typeof t.threadId === 'string' ? t.threadId : undefined,
                  clarificationThreadId: typeof t.clarificationThreadId === 'string' ? t.clarificationThreadId : undefined,
                  decision: ['confirm', 'reject'].includes(t.decision || '') ? t.decision : undefined })) }))
              .filter((s: Session) => s.turns.length)
              .map((s: Session) => ({ ...s, title: s.turns[0].message.replace(/\s+/g, ' ').slice(0, 24) }))
            currentId.value = saved.currentId
          }
        } catch { storageWarning.value = '未能恢复浏览器会话，请重新发起查询。' }
        if (!sessions.value.length) newSession()
        if (!current.value) newSession()
      }
      await selectSession(currentId.value)
    } catch (error) {
      connection.value = health.value.database ? '服务已连接，身份不可用' : health.value.api ? 'API 已连接，数据库不可用' : 'API 连接不可用'
      connectionError.value = error instanceof Error ? error.message : '无法连接服务。'
      for (const session of sessions.value) for (const turn of session.turns) { turn.workflow = undefined; turn.unavailable = true }
    } finally { connecting.value = false }
  }
  async function send(message: string) {
    if (busy.value || pending.value || !status.value || !message.trim() || message.trim().length > 10000) return
    if (!current.value) newSession()
    const previous = current.value!.turns.at(-1)
    const clarificationThreadId = previous && !previous.unavailable && finalResponse(previous.workflow)?.kind === 'clarify'
      ? previous.threadId : undefined
    current.value!.turns.push({ key: crypto.randomUUID(), message: message.trim(), clarificationThreadId })
    current.value!.title = current.value!.turns[0].message.replace(/\s+/g, ' ').slice(0, 24)
    await execute(current.value!.turns.at(-1)!, 'start')
  }
  const refresh = (turn: Turn) => execute(turn, turn.threadId ? 'get' : 'start')
  const retry = (turn: Turn) => execute(turn, turn.decision && turn.workflow?.operation_id ? 'resume' : 'start')
  const resume = (turn: Turn, decision: Decision) => {
    if (turn.workflow?.status !== 'waiting_for_confirmation' || turn.unavailable || (turn.decision && turn.decision !== decision)) return
    return execute(turn, 'resume', decision)
  }
  return { history, currentId, current, status, connection, health, connectionError, storageWarning, connecting,
    busy, pending, newSession, selectSession, connect, send, refresh, retry, resume }
}
