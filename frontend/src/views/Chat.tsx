import { useState, useRef, useEffect, useCallback } from 'react'
import { useSSE } from '../hooks/useSSE'
import MessageContent from '../components/MessageContent'

type Mode = 'chat' | 'wiki'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
}

let msgCounter = 0
const uid = () => `m${++msgCounter}`

export default function Chat() {
  const [mode, setMode] = useState<Mode>('chat')
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  const bottomRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // ── Auto-scroll ──────────────────────────────────────────────
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // ── Auto-resize textarea ─────────────────────────────────────
  useEffect(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`
  }, [input])

  // ── SSE callbacks ────────────────────────────────────────────
  const onChunk = useCallback((text: string) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (last?.role === 'assistant' && last.streaming) {
        return [
          ...prev.slice(0, -1),
          { ...last, content: last.content + text },
        ]
      }
      return prev
    })
  }, [])

  const onDone = useCallback(() => {
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (last?.streaming) return [...prev.slice(0, -1), { ...last, streaming: false }]
      return prev
    })
    setLoading(false)
  }, [])

  const onError = useCallback((err: Error) => {
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (last?.streaming) {
        return [
          ...prev.slice(0, -1),
          { ...last, content: last.content + `\n\n⚠️ 错误：${err.message}`, streaming: false },
        ]
      }
      return prev
    })
    setLoading(false)
  }, [])

  const { send, abort } = useSSE({ onChunk, onDone, onError })

  // ── Send message ─────────────────────────────────────────────
  const sendMessage = useCallback(async () => {
    const text = input.trim()
    if (!text || loading) return

    const userMsg: Message = { id: uid(), role: 'user', content: text }
    const assistantMsg: Message = { id: uid(), role: 'assistant', content: '', streaming: true }

    // 构建历史（排除当前正在 streaming 的占位符）
    const history = messages
      .filter((m) => !m.streaming && m.content)
      .map((m) => ({ role: m.role, content: m.content }))

    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setInput('')
    setLoading(true)

    // Wiki 模式走 /api/query，Chat 模式走 /api/chat（携带多轮历史）
    const endpoint = mode === 'wiki' ? '/api/query' : '/api/chat'
    const body = mode === 'wiki'
      ? JSON.stringify({ question: text })
      : JSON.stringify({ message: text, history })
    send(endpoint, { body })
  }, [input, loading, mode, messages, send])

  // ── Keyboard shortcut ────────────────────────────────────────
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  // ── Stop generation ──────────────────────────────────────────
  const handleStop = () => {
    abort()
    setMessages((prev) => {
      const last = prev[prev.length - 1]
      if (last?.streaming) return [...prev.slice(0, -1), { ...last, streaming: false }]
      return prev
    })
    setLoading(false)
  }

  return (
    <div className="view">
      {/* Header */}
      <div className="chat-header">
        <h2>对话</h2>
        <div className="mode-toggle">
          <button
            className={`mode-btn${mode === 'chat' ? ' active' : ''}`}
            onClick={() => setMode('chat')}
          >
            Chat
          </button>
          <button
            className={`mode-btn${mode === 'wiki' ? ' active' : ''}`}
            onClick={() => setMode('wiki')}
          >
            Wiki
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <div className="empty-title">Nemsy</div>
            <div className="empty-sub">
              {mode === 'wiki' ? '在 Wiki 模式下，回答将基于你的知识图谱。' : '开始一段新对话吧。'}
            </div>
          </div>
        ) : (
          messages.map((msg) => (
            <div key={msg.id} className={`message ${msg.role}`}>
              <div className="message-avatar">
                {msg.role === 'user' ? 'U' : 'N'}
              </div>
              <div className="message-body">
                <div className="message-bubble">
                  {msg.role === 'user' ? (
                    // 用户消息：纯文本
                    msg.content
                  ) : (
                    // Assistant 消息：Markdown + Wiki 引用
                    <MessageContent
                      content={msg.content || (msg.streaming ? '' : '…')}
                      streaming={msg.streaming}
                      onOpenRef={(title) => {
                        // 通过后端接口获取文件路径后打开
                        fetch(`/api/wiki/resolve?title=${encodeURIComponent(title)}`)
                          .then((r) => r.ok ? r.json() : null)
                          .then((d) => { if (d?.abs_path) window.open(`/api/file?path=${encodeURIComponent(d.abs_path)}`, '_blank') })
                          .catch(() => {})
                      }}
                    />
                  )}
                </div>
              </div>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div className="chat-input-area">
        <div className="chat-input-row">
          <textarea
            ref={textareaRef}
            className="chat-textarea"
            rows={1}
            placeholder={mode === 'wiki' ? '向知识图谱提问…' : '发送消息…'}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={loading}
          />
          {loading ? (
            <button className="chat-send-btn" onClick={handleStop} title="停止生成">
              ■
            </button>
          ) : (
            <button
              className="chat-send-btn"
              onClick={sendMessage}
              disabled={!input.trim()}
              title="发送 (Enter)"
            >
              ↑
            </button>
          )}
        </div>
        <div className="chat-hint">Enter 发送 · Shift+Enter 换行</div>
      </div>
    </div>
  )
}
