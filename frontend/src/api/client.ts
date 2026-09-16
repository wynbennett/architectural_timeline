import type { CompareResult, FileContent, FileEntry, GraphResponse, Health, Job, RepoDetail, RepoSummary } from '../types/graph'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try { const body = await res.json(); if (body?.error) msg = body.error; if (body?.description) msg = body.description } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => fetch('/api/health').then(json<Health>),
  listRepos: () => fetch('/api/repos').then(json<RepoSummary[]>),
  getRepo: (id: number) => fetch(`/api/repos/${id}`).then(json<RepoDetail>),
  createRepo: (url: string, tagPattern?: string) =>
    fetch('/api/repos', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, tag_pattern: tagPattern || undefined }) }).then(json<{ repo_id: number; job_id: number }>),
  generateTag: (repoId: number, tag: string) =>
    fetch(`/api/repos/${repoId}/tags/${encodeURIComponent(tag)}/generate`, { method: 'POST' }).then(json<{ job_id: number }>),
  getJob: (id: number) => fetch(`/api/jobs/${id}`).then(json<Job>),
  // chunked mode: runs one time-boxed slice of the job on the server; resolves when the slice ends
  stepJob: (id: number) => fetch(`/api/jobs/${id}/step`, { method: 'POST' }).then(json<Job & { done: boolean }>),
  getGraph: async (repoId: number, tag: string): Promise<GraphResponse | null> => {
    const res = await fetch(`/api/repos/${repoId}/tags/${encodeURIComponent(tag)}/graph`)
    if (res.status === 404) return null
    return json<GraphResponse>(res)
  },
  getCompare: async (repoId: number, from: string, to: string): Promise<CompareResult | null> => {
    const res = await fetch(`/api/repos/${repoId}/compare?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`)
    if (res.status === 404) return null
    return json<CompareResult>(res)
  },
  summarizeCompare: (repoId: number, from: string, to: string) =>
    fetch(`/api/repos/${repoId}/compare/summary`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ from, to }) }).then(json<{ from: string; to: string; summary: string; cached: boolean }>),
  writeOverview: (repoId: number, tag: string, force = false) =>
    fetch(`/api/repos/${repoId}/tags/${encodeURIComponent(tag)}/overview`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ force }) }).then(json<{ overview: string; cached: boolean }>),
  listFiles: (repoId: number, tag: string) => fetch(`/api/repos/${repoId}/tags/${encodeURIComponent(tag)}/files`).then(json<FileEntry[]>),
  getFile: (repoId: number, tag: string, path: string) =>
    fetch(`/api/repos/${repoId}/tags/${encodeURIComponent(tag)}/files?path=${encodeURIComponent(path)}`).then(json<FileContent>),
}

export type ChatEvent =
  | { type: 'text'; text: string }
  | { type: 'tool_use'; name: string; input: Record<string, unknown> }
  | { type: 'tool_result'; name: string; ok: boolean }
  | { type: 'error'; message: string }
  | { type: 'done' }

export interface ChatRequest {
  repo_id: number
  tag: string
  tier: number
  system_id?: string | null
  module_id?: string | null
  selected_node?: string | null
  open_file?: string | null
  compare_tag?: string | null
  messages: { role: 'user' | 'assistant'; content: string }[]
}

export async function streamChat(body: ChatRequest, onEvent: (e: ChatEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal })
  if (!res.ok || !res.body) throw new Error(await res.text().catch(() => `${res.status}`))
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const chunk = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      for (const line of chunk.split('\n')) {
        if (line.startsWith('data: ')) {
          try { onEvent(JSON.parse(line.slice(6)) as ChatEvent) } catch { /* skip malformed */ }
        }
      }
    }
  }
}
