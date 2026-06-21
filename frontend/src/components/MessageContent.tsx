/**
 * MessageContent
 *
 * 渲染 LLM 返回的消息内容：
 * 1. 将 [[页面名]] 替换为行内角标 [1][2]...，hover 时显示标题 tooltip
 * 2. 渲染完整 Markdown（加粗、列表、代码块等）
 * 3. 气泡底部引用列表：编号 + 标题，点击调用 onOpenRef
 */

import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Ref {
  index: number
  title: string   // 页面名（不含 .md）
}

interface Props {
  content: string
  streaming?: boolean
  onOpenRef?: (title: string) => void
}

/** 从消息文本中提取所有 [[页面名]]，去重，按首次出现顺序排列 */
function extractRefs(text: string): Ref[] {
  const seen = new Map<string, number>()
  const pattern = /\[\[([^\]]+)\]\]/g
  let match: RegExpExecArray | null
  let counter = 1
  while ((match = pattern.exec(text)) !== null) {
    const title = match[1].trim()
    if (!seen.has(title)) {
      seen.set(title, counter++)
    }
  }
  return Array.from(seen.entries()).map(([title, index]) => ({ index, title }))
}

/** 把 [[页面名]] 替换为 %%REF:1:页面名%% 占位符，供后续 Markdown 组件处理 */
function replaceWikiLinks(text: string, refMap: Map<string, number>): string {
  return text.replace(/\[\[([^\]]+)\]\]/g, (_, title) => {
    const idx = refMap.get(title.trim())
    return idx !== undefined ? `%%REF:${idx}:${title.trim()}%%` : title.trim()
  })
}

export default function MessageContent({ content, streaming, onOpenRef }: Props) {
  const { refs, processedText } = useMemo(() => {
    const refs = extractRefs(content)
    const refMap = new Map(refs.map((r) => [r.title, r.index]))
    const processedText = replaceWikiLinks(content, refMap)
    return { refs, processedText }
  }, [content])

  return (
    <div className="message-content">
      {/* ── Markdown 区域 ───────────────────────── */}
      <div className={`message-md${streaming ? ' streaming' : ''}`}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            // 把占位符 %%REF:n:title%% 渲染为角标
            p({ children }) {
              return <p>{renderWithRefs(children, onOpenRef)}</p>
            },
            li({ children }) {
              return <li>{renderWithRefs(children, onOpenRef)}</li>
            },
            // 行内代码保持 mono
            code({ children, className }) {
              const isBlock = className?.startsWith('language-')
              if (isBlock) {
                return (
                  <div className="code-block">
                    <code className={className}>{children}</code>
                  </div>
                )
              }
              return <code className="inline-code">{children}</code>
            },
          }}
        >
          {processedText}
        </ReactMarkdown>
      </div>

      {/* ── 引用列表 ─────────────────────────────── */}
      {refs.length > 0 && !streaming && (
        <>
          <div className="ref-divider" />
          <div className="ref-list">
            {refs.map((r) => (
              <button
                key={r.index}
                className="ref-item"
                onClick={() => onOpenRef?.(r.title)}
                title={`打开 ${r.title}`}
              >
                <span className="ref-badge">{r.index}</span>
                <span className="ref-title">{r.title}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// ── 工具函数：递归把 React children 里的占位符替换为角标 ──────────

function renderWithRefs(
  children: React.ReactNode,
  onOpenRef?: (title: string) => void,
): React.ReactNode {
  if (typeof children === 'string') {
    return splitByRefs(children, onOpenRef)
  }
  if (Array.isArray(children)) {
    return children.map((child, i) => (
      <span key={i}>{renderWithRefs(child, onOpenRef)}</span>
    ))
  }
  return children
}

function splitByRefs(
  text: string,
  _onOpenRef?: (title: string) => void,
): React.ReactNode {
  const parts = text.split(/(%%REF:\d+:[^%]+%%)/g)
  return parts.map((part, i) => {
    const m = part.match(/^%%REF:(\d+):(.+)%%$/)
    if (m) {
      const idx = Number(m[1])
      const title = m[2]
      return (
        <sup key={i} className="wiki-ref" title={title}>
          {idx}
        </sup>
      )
    }
    return part
  })
}
