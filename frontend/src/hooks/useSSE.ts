import { useCallback, useRef } from 'react'

interface SSEOptions {
  onChunk: (text: string) => void
  onDone?: (usage?: { prompt_tokens: number; completion_tokens: number }) => void
  onError?: (err: Error) => void
}

/**
 * useSSE：封装 SSE 流式接收逻辑
 *
 * 用法：
 *   const { send, abort } = useSSE({ onChunk, onDone, onError })
 *   send('/api/chat', { body: JSON.stringify({ message }) })
 */
export function useSSE({ onChunk, onDone, onError }: SSEOptions) {
  const abortRef = useRef<AbortController | null>(null)

  const send = useCallback(
    async (url: string, init?: RequestInit) => {
      // 取消上一个未完成的请求
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      console.log('[SSE] → sending to', url, 'body:', init?.body)

      try {
        const resp = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: controller.signal,
          ...init,
        })

        console.log('[SSE] response status:', resp.status, 'content-type:', resp.headers.get('content-type'))

        if (!resp.ok) {
          const errText = await resp.text()
          console.error('[SSE] HTTP error body:', errText)
          throw new Error(`HTTP ${resp.status}: ${errText}`)
        }
        if (!resp.body) throw new Error('No response body')

        const reader = resp.body.getReader()
        const decoder = new TextDecoder()
        let buf = ''
        let chunkCount = 0

        while (true) {
          const { done, value } = await reader.read()
          if (done) {
            console.log('[SSE] stream done, total chunks received:', chunkCount)
            break
          }

          const raw = decoder.decode(value, { stream: true })
          console.log('[SSE] raw bytes received:', JSON.stringify(raw))
          buf += raw

          const lines = buf.split('\n')
          buf = lines.pop() ?? ''

          for (const line of lines) {
            console.log('[SSE] line:', JSON.stringify(line))
            if (!line.startsWith('data: ')) continue
            try {
              const data = JSON.parse(line.slice(6))
              console.log('[SSE] parsed event:', data)
              if (data.type === 'chunk') { chunkCount++; onChunk(data.text) }
              if (data.type === 'done') onDone?.(data.usage)
            } catch (parseErr) {
              console.error('[SSE] JSON parse error on line:', line, parseErr)
            }
          }
        }
      } catch (err) {
        console.error('[SSE] error:', err)
        if ((err as Error).name !== 'AbortError') {
          onError?.(err as Error)
        }
      }
    },
    [onChunk, onDone, onError],
  )

  const abort = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  return { send, abort }
}
