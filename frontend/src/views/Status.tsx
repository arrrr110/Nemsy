import { useEffect, useState } from 'react'

interface StatusData {
  vault: {
    path: string
    exists: boolean
    raw_sources_dir: string | null
  }
  wiki: {
    path: string
    exists: boolean
    total_notes: number
    sources_count: number
    queries_count: number
  }
  llm: {
    api_key_set: boolean
    base_url: string
    default_model: string
    reasoning_model: string
  }
  token_usage: {
    total_prompt: number
    total_completion: number
    total_calls: number
    by_model: Record<string, { prompt: number; completion: number; calls: number }>
  }
}

function fmtNum(n: number) {
  return n.toLocaleString('zh-CN')
}

function fmtPath(p: string) {
  // 截短超长路径：显示后 50 个字符
  return p.length > 48 ? '…' + p.slice(-46) : p
}

export default function Status() {
  const [data, setData] = useState<StatusData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/status')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json() as Promise<StatusData>
      })
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  if (error)  return <div className="error-text">无法加载状态：{error}</div>
  if (!data)  return <div className="loading-text">加载中…</div>

  const usage = data.token_usage
  const totalTokens = usage.total_prompt + usage.total_completion

  return (
    <div className="status-view">
      <h1>系统状态</h1>

      <div className="status-grid">
        {/* ── Vault ──────────────────────────────── */}
        <div className="status-card">
          <div className="status-card-title">Vault</div>
          <div className="status-row">
            <span className="status-label">根目录</span>
            <span className="status-value" title={data.vault.path}>
              {fmtPath(data.vault.path)}
            </span>
          </div>
          <div className="status-row">
            <span className="status-label">目录存在</span>
            <span className="status-value">
              <span className={`status-badge ${data.vault.exists ? 'badge-green' : 'badge-red'}`}>
                {data.vault.exists ? '✓ 是' : '✗ 否'}
              </span>
            </span>
          </div>
          <div className="status-row">
            <span className="status-label">原始资料目录</span>
            <span className="status-value" title={data.vault.raw_sources_dir ?? '未配置'}>
              {data.vault.raw_sources_dir ? fmtPath(data.vault.raw_sources_dir) : '—'}
            </span>
          </div>
        </div>

        {/* ── Wiki ──────────────────────────────── */}
        <div className="status-card">
          <div className="status-card-title">Wiki</div>
          <div className="status-row">
            <span className="status-label">知识图谱路径</span>
            <span className="status-value" title={data.wiki.path}>
              {fmtPath(data.wiki.path)}
            </span>
          </div>
          <div className="status-row">
            <span className="status-label">索引可用</span>
            <span className="status-value">
              <span className={`status-badge ${data.wiki.exists ? 'badge-green' : 'badge-red'}`}>
                {data.wiki.exists ? '✓ 是' : '✗ 否'}
              </span>
            </span>
          </div>
          <div className="status-row">
            <span className="status-label">总笔记数</span>
            <span className="status-value">{fmtNum(data.wiki.total_notes)}</span>
          </div>
          <div className="status-row">
            <span className="status-label">Source 摘要</span>
            <span className="status-value">{fmtNum(data.wiki.sources_count)}</span>
          </div>
          <div className="status-row">
            <span className="status-label">Query 笔记</span>
            <span className="status-value">{fmtNum(data.wiki.queries_count)}</span>
          </div>
        </div>

        {/* ── LLM ──────────────────────────────── */}
        <div className="status-card">
          <div className="status-card-title">LLM</div>
          <div className="status-row">
            <span className="status-label">API Key</span>
            <span className="status-value">
              <span className={`status-badge ${data.llm.api_key_set ? 'badge-green' : 'badge-red'}`}>
                {data.llm.api_key_set ? '✓ 已配置' : '✗ 未配置'}
              </span>
            </span>
          </div>
          <div className="status-row">
            <span className="status-label">接入点</span>
            <span className="status-value" title={data.llm.base_url}>
              {fmtPath(data.llm.base_url)}
            </span>
          </div>
          <div className="status-row">
            <span className="status-label">默认模型</span>
            <span className="status-value">{data.llm.default_model}</span>
          </div>
          <div className="status-row">
            <span className="status-label">推理模型</span>
            <span className="status-value">{data.llm.reasoning_model}</span>
          </div>
        </div>

        {/* ── Token 用量 ──────────────────────────────── */}
        <div className="status-card">
          <div className="status-card-title">Token 用量（累计）</div>
          <div className="status-row">
            <span className="status-label">总调用次数</span>
            <span className="status-value">{fmtNum(usage.total_calls)}</span>
          </div>
          <div className="status-row">
            <span className="status-label">输入 tokens</span>
            <span className="status-value">{fmtNum(usage.total_prompt)}</span>
          </div>
          <div className="status-row">
            <span className="status-label">输出 tokens</span>
            <span className="status-value">{fmtNum(usage.total_completion)}</span>
          </div>
          <div className="status-row">
            <span className="status-label">合计 tokens</span>
            <span className="status-value">
              <span className="status-badge badge-blue">{fmtNum(totalTokens)}</span>
            </span>
          </div>
        </div>

        {/* ── 按模型明细 ──────────────────────────────── */}
        {Object.keys(usage.by_model).length > 0 && (
          <div className="status-card" style={{ gridColumn: '1 / -1' }}>
            <div className="status-card-title">按模型明细</div>
            {Object.entries(usage.by_model).map(([model, m]) => (
              <div className="status-row" key={model}>
                <span className="status-label">{model}</span>
                <span className="status-value">
                  {fmtNum(m.prompt + m.completion)} tokens · {fmtNum(m.calls)} 次
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
