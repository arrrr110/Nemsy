/**
 * Nemsy API 客户端
 * 封装所有后端接口调用，集中管理 endpoint 和请求格式
 */

const BASE = '/api'

async function post<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`API ${path} failed: ${resp.status}`)
  return resp.json()
}

async function get<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v))
  const resp = await fetch(url.toString())
  if (!resp.ok) throw new Error(`API ${path} failed: ${resp.status}`)
  return resp.json()
}

// ── 状态 ────────────────────────────────────────────
export const getStatus = () => get('/status')

// ── 文件树 ───────────────────────────────────────────
export const getSources = () => get('/sources')
export const getWiki = () => get('/wiki')
export const getFile = (path: string) => get('/file', { path })

// ── 配置 ────────────────────────────────────────────
export const getSettings = () => get('/settings')
export const saveSettings = (data: unknown) => post('/settings', data)

// ── Ingest ───────────────────────────────────────────
export const ingestPath = (path: string, options?: { recursive?: boolean; force?: boolean }) =>
  post('/ingest', { path, ...options })

// SSE 接口（/api/chat, /api/query, /api/lint）通过 useSSE hook 直接调用，不在此封装
export const CHAT_URL = `${BASE}/chat`
export const QUERY_URL = `${BASE}/query`
export const LINT_URL = `${BASE}/lint`
export const SAVE_URL = `${BASE}/save`
