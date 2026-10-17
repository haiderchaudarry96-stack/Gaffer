/**
 * Chat with the agent (contract in web/README.md, "Backend API"):
 *   POST /api/chat  { match_id, question, history }  ->  { answer, citations, trace_id }
 * Without VITE_API_URL this throws ApiNotConfigured; the UI then says the agent is not connected.
 */
import { apiPost, type ApiOptions } from './api'
import { arr, obj, str } from './validate'

export interface ChatTurn {
  role: 'user' | 'assistant'
  text: string
}

export interface ChatRequest {
  match_id: string
  question: string
  history: ChatTurn[]
}

export interface ChatAnswer {
  answer: string
  /** refs or ids the answer cites, e.g. "R2", "evt_003" */
  citations: string[]
  trace_id: string | null
}

export async function sendChat(req: ChatRequest, opts?: ApiOptions): Promise<ChatAnswer> {
  const question = req.question.trim()
  if (!question) throw new Error('empty question')
  const r = obj(await apiPost('/api/chat', { ...req, question }, 'Chat', opts), 'chat')
  return {
    answer: str(r.answer, 'chat.answer'),
    citations: r.citations === undefined ? [] : arr(r.citations, 'chat.citations').map((c, i) => str(c, `chat.citations[${i}]`)),
    trace_id: typeof r.trace_id === 'string' ? r.trace_id : null,
  }
}
