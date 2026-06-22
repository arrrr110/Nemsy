/**
 * FileLibrary — 文件库视图
 *
 * 布局：左侧双栏列表（Sources / Wiki），右侧文件内容预览面板
 *
 * Sources 栏：原始资料，每条显示摄取状态 badge（new/done/changed/empty）
 *             点击「未摄取」/「已更新」badge → 弹出确认对话框 → 摄取为 Wiki
 * Wiki 栏：知识图谱笔记，每条显示类型 badge（source/query/insight/entity/concept）
 * 右侧：选中文件的 Markdown 原始内容（只读）
 */

import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// ── 类型定义 ───────────────────────────────────────────────

interface SourceFile {
  path: string
  abs_path: string
  status: 'new' | 'done' | 'changed' | 'empty'
  last_ingested: string | null
}

interface WikiFile {
  rel_path: string
  abs_path: string
  type: string
  title: string
  date: string
  tags: string[]
}

interface SelectedFile {
  abs_path: string
  display_name: string
}

// ── Badge 颜色映射 ─────────────────────────────────────────

const SOURCE_STATUS_CLASS: Record<string, string> = {
  done:    'badge-green',
  changed: 'badge-yellow',
  new:     'badge-blue',
  empty:   'badge-muted',
}

const SOURCE_STATUS_LABEL: Record<string, string> = {
  done:    '已摄取',
  changed: '已更新',
  new:     '未摄取',
  empty:   '空文件',
}

const WIKI_TYPE_CLASS: Record<string, string> = {
  source:  'badge-teal',
  query:   'badge-blue',
  insight: 'badge-purple',
  entity:  'badge-yellow',
  concept: 'badge-green',
}

// ── 文件路径简化 ──────────────────────────────────────────

function basename(p: string) {
  return p.replace(/\\/g, '/').split('/').pop() ?? p
}

function dirpart(p: string) {
  const parts = p.replace(/\\/g, '/').split('/')
  parts.pop()
  return parts.join('/') || ''
}

// ── 主组件 ────────────────────────────────────────────────

export default function FileLibrary() {
  const [tab, setTab] = useState<'sources' | 'wiki'>('sources')

  // Sources 数据
  const [sources, setSources] = useState<SourceFile[]>([])
  const [sourcesRoot, setSourcesRoot] = useState('')
  const [sourcesLoading, setSourcesLoading] = useState(true)
  const [sourcesError, setSourcesError] = useState<string | null>(null)

  // Wiki 数据
  const [wikiFiles, setWikiFiles] = useState<WikiFile[]>([])
  const [wikiLoading, setWikiLoading] = useState(true)
  const [wikiError, setWikiError] = useState<string | null>(null)

  // 选中预览
  const [selected, setSelected] = useState<SelectedFile | null>(null)
  const [previewContent, setPreviewContent] = useState<string | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)

  // Sources 搜索
  const [sourcesFilter, setSourcesFilter] = useState('')
  // Wiki 搜索
  const [wikiFilter, setWikiFilter] = useState('')

  // 摄取确认对话框
  const [confirmTarget, setConfirmTarget] = useState<SourceFile | null>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)

  // 摄取状态：abs_path → 'ingesting' | 'error'
  const [ingestingMap, setIngestingMap] = useState<Record<string, 'ingesting' | 'error'>>({})

  // 加载 Sources
  useEffect(() => {
    fetch('/api/sources')
      .then((r) => r.json())
      .then((d) => {
        setSources(d.files ?? [])
        setSourcesRoot(d.root ?? '')
        setSourcesLoading(false)
      })
      .catch((e) => { setSourcesError(e.message); setSourcesLoading(false) })
  }, [])

  // 加载 Wiki
  useEffect(() => {
    fetch('/api/wiki')
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d) => {
        // 兼容旧格式（files 为字符串数组）和新格式（files 为对象数组）
        const raw: unknown[] = d.files ?? []
        const normalized: WikiFile[] = raw.map((item) =>
          typeof item === 'string'
            ? { rel_path: item, abs_path: '', type: '', title: item, date: '', tags: [] }
            : (item as WikiFile)
        )
        setWikiFiles(normalized)
        setWikiLoading(false)
      })
      .catch((e) => { setWikiError(e.message); setWikiLoading(false) })
  }, [])

  // 对话框打开/关闭同步
  useEffect(() => {
    const dlg = dialogRef.current
    if (!dlg) return
    if (confirmTarget) {
      dlg.showModal()
    } else {
      dlg.close()
    }
  }, [confirmTarget])

  // 加载文件内容
  function openFile(abs_path: string, display_name: string) {
    if (!abs_path) {
      setSelected({ abs_path: '', display_name })
      setPreviewContent(null)
      setPreviewError('后端服务需要重启才能加载文件内容（请执行 nemsy web）')
      setPreviewLoading(false)
      return
    }
    setSelected({ abs_path, display_name })
    setPreviewContent(null)
    setPreviewError(null)
    setPreviewLoading(true)
    fetch(`/api/file?path=${encodeURIComponent(abs_path)}`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((d) => { setPreviewContent(d.content); setPreviewLoading(false) })
      .catch((e) => { setPreviewError(e.message); setPreviewLoading(false) })
  }

  // 点击 badge → 打开确认框（仅 new/changed）
  function handleBadgeClick(e: React.MouseEvent, f: SourceFile) {
    e.stopPropagation()
    if (f.status !== 'new' && f.status !== 'changed') return
    if (!f.abs_path) return
    setConfirmTarget(f)
  }

  // 确认摄取
  async function confirmIngest() {
    const f = confirmTarget
    if (!f) return
    setConfirmTarget(null)
    setIngestingMap((prev) => ({ ...prev, [f.abs_path]: 'ingesting' }))
    try {
      const res = await fetch('/api/ingest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: f.abs_path }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      // 就地更新状态
      setSources((prev) =>
        prev.map((s) =>
          s.abs_path === f.abs_path
            ? { ...s, status: 'done', last_ingested: new Date().toISOString() }
            : s
        )
      )
      setIngestingMap((prev) => {
        const next = { ...prev }
        delete next[f.abs_path]
        return next
      })
    } catch {
      setIngestingMap((prev) => ({ ...prev, [f.abs_path]: 'error' }))
      // 3s 后清除错误，允许重试
      setTimeout(() => {
        setIngestingMap((prev) => {
          const next = { ...prev }
          delete next[f.abs_path]
          return next
        })
      }, 3000)
    }
  }

  // 过滤
  const filteredSources = sources.filter((f) =>
    (f.path ?? '').toLowerCase().includes(sourcesFilter.toLowerCase())
  )
  const filteredWiki = wikiFiles.filter((f) =>
    (f.title ?? '').toLowerCase().includes(wikiFilter.toLowerCase()) ||
    (f.rel_path ?? '').toLowerCase().includes(wikiFilter.toLowerCase())
  )

  // Wiki 按 type 分组
  const wikiByType: Record<string, WikiFile[]> = {}
  for (const f of filteredWiki) {
    const t = f.type || 'other'
    if (!wikiByType[t]) wikiByType[t] = []
    wikiByType[t].push(f)
  }
  const TYPE_ORDER = ['source', 'query', 'insight', 'entity', 'concept', 'other']
  const sortedTypes = TYPE_ORDER.filter((t) => wikiByType[t])

  return (
    <div className="file-library">
      {/* ── 摄取确认对话框 ────────────────────────── */}
      <dialog ref={dialogRef} className="ingest-dialog" onClose={() => setConfirmTarget(null)}>
        <div className="ingest-dialog-body">
          <div className="ingest-dialog-icon">📥</div>
          <div className="ingest-dialog-title">摄取为 Wiki？</div>
          <div className="ingest-dialog-file">
            {confirmTarget ? basename(confirmTarget.path) : ''}
          </div>
          <div className="ingest-dialog-desc">
            该文件将被 Nemsy 阅读并整理为一篇 Wiki 笔记，保存到知识图谱中。
          </div>
          <div className="ingest-dialog-actions">
            <button
              className="ingest-dialog-btn ingest-dialog-btn--cancel"
              onClick={() => setConfirmTarget(null)}
            >
              取消
            </button>
            <button
              className="ingest-dialog-btn ingest-dialog-btn--confirm"
              onClick={confirmIngest}
            >
              确认摄取
            </button>
          </div>
        </div>
      </dialog>

      {/* ── 左侧列表面板 ───────────────────────────── */}
      <div className="fl-sidebar">
        {/* Tab 切换 */}
        <div className="fl-tabs">
          <button
            className={`fl-tab${tab === 'sources' ? ' active' : ''}`}
            onClick={() => setTab('sources')}
          >
            📄 原始资料
          </button>
          <button
            className={`fl-tab${tab === 'wiki' ? ' active' : ''}`}
            onClick={() => setTab('wiki')}
          >
            🧠 Wiki
          </button>
        </div>

        {/* Sources 面板 */}
        {tab === 'sources' && (
          <div className="fl-panel">
<div className="fl-search-wrap">
<input
className="fl-search"
placeholder="过滤文件名…"
value={sourcesFilter}
onChange={(e) => setSourcesFilter(e.target.value)}
/>
{sourcesFilter && (
  <button className="fl-search-clear" onClick={() => setSourcesFilter('')} title="清空">
    ✕
  </button>
)}
</div>
            {sourcesRoot && (
              <div className="fl-root-label" title={sourcesRoot}>
                {sourcesRoot.length > 46 ? '…' + sourcesRoot.slice(-44) : sourcesRoot}
              </div>
            )}
            {sourcesLoading && <div className="loading-text">加载中…</div>}
            {sourcesError && <div className="error-text">{sourcesError}</div>}
            {!sourcesLoading && !sourcesError && filteredSources.length === 0 && (
              <div className="fl-empty">暂无文件</div>
            )}
            <div className="fl-list">
              {filteredSources.map((f) => {
                const dir = dirpart(f.path)
                const name = basename(f.path)
                const isActive = selected?.abs_path === f.abs_path
                const ingestState = ingestingMap[f.abs_path]
                const canIngest = (f.status === 'new' || f.status === 'changed') && !!f.abs_path
                // badge 展示：摄取中时替换显示
                const badgeClass = ingestState === 'ingesting'
                  ? 'badge-dim'
                  : ingestState === 'error'
                  ? 'badge-red'
                  : SOURCE_STATUS_CLASS[f.status] ?? 'badge-muted'
                const badgeLabel = ingestState === 'ingesting'
                  ? '摄取中…'
                  : ingestState === 'error'
                  ? '摄取失败'
                  : SOURCE_STATUS_LABEL[f.status] ?? f.status
                return (
                  <button
                    key={f.abs_path}
                    className={`fl-item${isActive ? ' active' : ''}`}
                    onClick={() => openFile(f.abs_path, f.path)}
                  >
                    <div className="fl-item-top">
                      <span className="fl-item-name" title={f.path}>{name}</span>
                      <span
                        className={`fl-badge ${badgeClass}${canIngest && !ingestState ? ' fl-badge-clickable' : ''}`}
                        onClick={canIngest && !ingestState ? (e) => handleBadgeClick(e, f) : undefined}
                        title={canIngest && !ingestState ? '点击摄取为 Wiki' : undefined}
                      >
                        {badgeLabel}
                      </span>
                    </div>
                    {dir && <div className="fl-item-dir">{dir}</div>}
                    {f.last_ingested && (
                      <div className="fl-item-meta">
                        摄取于 {f.last_ingested.slice(0, 10)}
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        )}

        {/* Wiki 面板 */}
        {tab === 'wiki' && (
          <div className="fl-panel">
<div className="fl-search-wrap">
<input
className="fl-search"
placeholder="过滤标题或路径…"
value={wikiFilter}
onChange={(e) => setWikiFilter(e.target.value)}
/>
{wikiFilter && (
  <button className="fl-search-clear" onClick={() => setWikiFilter('')} title="清空">
    ✕
  </button>
)}
</div>
            <div className="fl-wiki-count">
              共 {filteredWiki.length} 条笔记
            </div>
            {wikiLoading && <div className="loading-text">加载中…</div>}
            {wikiError && <div className="error-text">{wikiError}</div>}
            {!wikiLoading && !wikiError && filteredWiki.length === 0 && (
              <div className="fl-empty">暂无笔记</div>
            )}
            <div className="fl-list">
              {sortedTypes.map((type) => (
                <div key={type} className="fl-wiki-group">
                  <div className="fl-wiki-group-header">
                    <span className={`fl-badge ${WIKI_TYPE_CLASS[type] ?? 'badge-muted'}`}>
                      {type}
                    </span>
                    <span className="fl-wiki-group-count">{wikiByType[type].length}</span>
                  </div>
                  {wikiByType[type].map((f, idx) => {
                    const isActive = selected?.abs_path !== '' && selected?.abs_path === f.abs_path
                    const itemKey = f.abs_path || `${type}-${idx}`
                    return (
                      <button
                        key={itemKey}
                        className={`fl-item${isActive ? ' active' : ''}`}
                        onClick={() => openFile(f.abs_path, f.title || f.rel_path || '')}
                      >
                        <div className="fl-item-top">
                          <span className="fl-item-name" title={f.rel_path ?? ''}>
                            {f.title || basename(f.rel_path ?? '')}
                          </span>
                          {f.date && (
                            <span className="fl-item-date">{String(f.date).slice(0, 10)}</span>
                          )}
                        </div>
                        {(f.tags ?? []).length > 0 && (
                          <div className="fl-item-tags">
                            {(f.tags ?? []).slice(0, 4).map((t) => (
                              <span key={t} className="fl-tag">{t}</span>
                            ))}
                          </div>
                        )}
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── 右侧预览面板 ──────────────────────────── */}
      <div className="fl-preview">
        {!selected && (
          <div className="fl-preview-empty">
            <div className="fl-preview-empty-icon">📄</div>
            <div>点击左侧文件查看内容</div>
          </div>
        )}
        {selected && (
          <>
            <div className="fl-preview-header">
              <span className="fl-preview-title" title={selected.abs_path}>
                {selected.display_name}
              </span>
            </div>
            <div className="fl-preview-body">
              {previewLoading && <div className="loading-text">加载中…</div>}
              {previewError && <div className="error-text">无法加载：{previewError}</div>}
              {previewContent !== null && !previewLoading && (
                <div className="fl-md">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {previewContent}
                  </ReactMarkdown>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
