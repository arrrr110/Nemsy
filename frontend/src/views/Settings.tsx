/**
 * Settings — 设置视图（只读）
 *
 * 展示 config/settings.toml 和 .env 的当前值。
 * 敏感字段（含 KEY/TOKEN/SECRET）中段自动以 * 隐藏。
 */

import { useEffect, useState } from 'react'

interface EnvPair {
  key: string
  value: string
  sensitive: boolean
}

interface SettingsData {
  toml: Record<string, unknown>
  env: EnvPair[]
  summary: {
    vault_path: string
    wiki_dir: string
    raw_sources_dir: string
    default_model: string
    reasoning_model: string
    api_key_masked: string
    base_url: string
  }
}

// ── 递归渲染 TOML 对象 ────────────────────────────────────

function TomlSection({ data, depth = 0 }: { data: Record<string, unknown>; depth?: number }) {
  return (
    <div className={`toml-section depth-${depth}`}>
      {Object.entries(data).map(([key, val]) => {
        if (val !== null && typeof val === 'object' && !Array.isArray(val)) {
          return (
            <div key={key} className="toml-group">
              <div className="toml-group-header">[{key}]</div>
              <TomlSection data={val as Record<string, unknown>} depth={depth + 1} />
            </div>
          )
        }
        const display = Array.isArray(val)
          ? val.join(', ') || '—'
          : val === '' || val === null || val === undefined
            ? '—'
            : String(val)
        return (
          <div key={key} className="toml-row">
            <span className="toml-key">{key}</span>
            <span className="toml-val" title={display}>{display}</span>
          </div>
        )
      })}
    </div>
  )
}

// ── 主组件 ────────────────────────────────────────────────

export default function Settings() {
  const [data, setData] = useState<SettingsData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/settings')
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(setData)
      .catch((e) => setError(e.message))
  }, [])

  if (error) return <div className="error-text">无法加载配置：{error}</div>
  if (!data)  return <div className="loading-text">加载中…</div>

  const hasToml    = Object.keys(data.toml).length > 0
  const hasEnv     = data.env.length > 0
  const hasApiKey  = data.summary.api_key_masked !== ''

  return (
    <div className="settings-view">
      <div className="settings-header">
        <h1>设置</h1>
        <span className="settings-readonly-badge">只读</span>
      </div>

      {/* ── 首次使用引导 Banner ──────────────── */}
      {!hasApiKey && (
        <div className="settings-onboard-banner">
          <div className="settings-onboard-title">👋 欢迎使用 Nemsy</div>
          <div className="settings-onboard-body">
            首次使用需要配置 DeepSeek API Key，才能启用 LLM 对话和知识摄取功能。
          </div>
          <ol className="settings-onboard-steps">
            <li>访问 <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer">platform.deepseek.com/api_keys</a> 创建 API Key</li>
            <li>在项目根目录创建或编辑 <code>.env</code> 文件</li>
            <li>添加一行：<code>DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx</code></li>
            <li>重启后端：<code>nemsy web</code></li>
          </ol>
        </div>
      )}

      {/* ── settings.toml ───────────────────── */}
      <section className="settings-section">
        <div className="settings-section-title">
          <span className="settings-section-icon">📄</span>
          config/settings.toml
        </div>
        {hasToml ? (
          <div className="settings-card">
            <TomlSection data={data.toml} />
          </div>
        ) : (
          <div className="settings-empty">未找到 settings.toml 文件</div>
        )}
      </section>

      {/* ── .env ────────────────────────────── */}
      <section className="settings-section">
        <div className="settings-section-title">
          <span className="settings-section-icon">🔐</span>
          .env 环境变量
          <span className="settings-section-hint">（敏感字段中段已隐藏）</span>
        </div>

        {/* 配置说明 Tips */}
        <div className="settings-env-tips">
          <div className="settings-tips-title">📝 配置说明</div>
          <ul className="settings-tips-list">
            <li><code>DEEPSEEK_API_KEY</code> — DeepSeek API 密钥，必填。从
              {' '}<a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noreferrer">platform.deepseek.com</a>{' '}
              获取，格式为 <code>sk-xxxx…</code>
            </li>
            <li>修改 <code>.env</code> 后需要重启后端（<code>nemsy web</code>）才能生效</li>
            {/* <li>该文件不会被提交到 Git（已在 <code>.gitignore</code> 中忽略）</li> */}
          </ul>
        </div>

        {hasEnv ? (
          <div className="settings-card">
            {data.env.map((pair) => (
              <div key={pair.key} className="toml-row">
                <span className="toml-key">
                  {pair.key}
                  {pair.sensitive && <span className="env-sensitive-dot" title="敏感字段" />}
                </span>
                <span className={`toml-val${pair.sensitive ? ' env-masked' : ''}`}>
                  {pair.value || '—'}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div className="settings-empty-with-guide">
            <div className="settings-empty">未找到 .env 文件或文件为空</div>
            <div className="settings-create-guide">
              <div className="settings-guide-label">快速创建：在项目根目录执行</div>
              <code className="settings-guide-code">echo 'DEEPSEEK_API_KEY=sk-你的密钥' &gt; .env</code>
            </div>
          </div>
        )}
      </section>
    </div>
  )
}
