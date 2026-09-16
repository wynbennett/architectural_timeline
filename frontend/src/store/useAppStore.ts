import { create } from 'zustand'
import { api, streamChat } from '../api/client'
import type { ChatMessage, CompareResult, FileEntry, GraphResponse, Health, Job, OpenFile, RepoDetail, RepoSummary, SnippetNode, TagInfo, Tier } from '../types/graph'
import { tier3Key } from '../types/graph'

interface AppState {
  health: Health | null
  repos: RepoSummary[]
  repo: RepoDetail | null
  currentTag: string | null
  graph: GraphResponse | null
  graphLoading: boolean
  files: FileEntry[]
  tier: Tier
  systemId: string | null
  moduleId: string | null
  selectedNodeId: string | null
  openFile: OpenFile | null
  hoverRange: { path: string; startLine: number; endLine: number } | null
  showAllFiles: boolean
  job: Job | null
  toast: string | null
  error: string | null
  chat: ChatMessage[]
  chatBusy: boolean
  chatDraft: string | null
  compareMode: boolean
  compareTag: string | null
  compareGraph: GraphResponse | null
  compare: CompareResult | null
  compareNote: string | null
  summarizing: boolean
  timelineMode: TimelineMode
  leftTab: 'diagram' | 'overview'
  overviewBusy: boolean

  init: () => Promise<void>
  loadRepo: (url: string, tagPattern?: string) => Promise<void>
  selectRepo: (id: number) => Promise<void>
  selectTag: (name: string) => Promise<void>
  generateTag: (name: string) => Promise<void>
  drillInto: (nodeId: string) => void
  goToTier: (tier: Tier) => void
  selectSnippet: (s: SnippetNode) => void
  openPath: (path: string, startLine?: number, endLine?: number) => void
  setHoverRange: (r: AppState['hoverRange']) => void
  toggleAllFiles: () => void
  sendChat: (text: string) => Promise<void>
  clearChat: () => void
  dismissToast: () => void
  setChatDraft: (text: string | null) => void
  askAbout: (kind: string, name: string) => void
  toggleCompareMode: () => void
  setCompareTag: (name: string) => Promise<void>
  refreshCompare: () => Promise<void>
  summarizeCompare: () => Promise<void>
  setTimelineMode: (m: TimelineMode) => void
  setLeftTab: (t: 'diagram' | 'overview') => void
  writeOverview: (force?: boolean) => Promise<void>
}

export type TimelineMode = 'generated' | 'recent' | 'all'
export const RECENT_TAGS = 12

/** Tags shown on the slider for a mode. Always keeps the current/compare tags visible. */
export function visibleTags(tags: TagInfo[], mode: TimelineMode, keep: (string | null)[]): TagInfo[] {
  if (mode === 'all') return tags
  const keepSet = new Set(keep.filter(Boolean) as string[])
  const interesting = (t: TagInfo) => t.has_graph || t.status === 'running' || t.status === 'queued' || t.status === 'failed' || keepSet.has(t.name)
  if (mode === 'generated') return tags.filter(interesting)
  const recentFrom = Math.max(0, tags.length - RECENT_TAGS)
  return tags.filter((t, i) => i >= recentFrom || interesting(t))
}

function loadTimelineMode(): TimelineMode {
  try { const v = localStorage.getItem('timelineMode'); if (v === 'generated' || v === 'recent' || v === 'all') return v } catch { /* ignore */ }
  return 'recent'
}

let graphRequest = 0

/** The repo README at this tag, shown in the code pane while on the system view. */
function readmeFile(files: FileEntry[]): OpenFile | null {
  const f = files.find((x) => /^readme(\.(md|rst|txt|markdown))?$/i.test(x.path))
  return f ? { path: f.path } : null
}

function newestGeneratedTag(tags: TagInfo[]): TagInfo | undefined {
  return [...tags].reverse().find((t) => t.has_graph)
}

export const useAppStore = create<AppState>((set, get) => ({
  health: null,
  repos: [],
  repo: null,
  currentTag: null,
  graph: null,
  graphLoading: false,
  files: [],
  tier: 1,
  systemId: null,
  moduleId: null,
  selectedNodeId: null,
  openFile: null,
  hoverRange: null,
  showAllFiles: false,
  job: null,
  toast: null,
  error: null,
  chat: [],
  chatBusy: false,
  chatDraft: null,
  compareMode: false,
  compareTag: null,
  compareGraph: null,
  compare: null,
  compareNote: null,
  summarizing: false,
  timelineMode: loadTimelineMode(),
  leftTab: 'diagram',
  overviewBusy: false,

  init: async () => {
    try {
      const [health, repos] = await Promise.all([api.health(), api.listRepos()])
      set({ health, repos })
      const first = repos.find((r) => r.generated_count > 0) ?? repos[0]
      if (first) await get().selectRepo(first.id)
    } catch (e) {
      set({ error: `backend unreachable: ${(e as Error).message}` })
    }
  },

  loadRepo: async (url, tagPattern) => {
    set({ error: null })
    try {
      const { repo_id, job_id } = await api.createRepo(url, tagPattern)
      const repo = await api.getRepo(repo_id)
      set({ repo, currentTag: null, graph: null, files: [], tier: 1, systemId: null, moduleId: null, selectedNodeId: null, openFile: null, chat: [], compareMode: false, compareTag: null, compareGraph: null, compare: null })
      startPolling(job_id)
      set({ repos: await api.listRepos() })
    } catch (e) {
      set({ error: (e as Error).message })
    }
  },

  selectRepo: async (id) => {
    const repo = await api.getRepo(id)
    set({ repo, currentTag: null, graph: null, files: [], tier: 1, systemId: null, moduleId: null, selectedNodeId: null, openFile: null, chat: [], job: null, compareMode: false, compareTag: null, compareGraph: null, compare: null })
    const tag = newestGeneratedTag(repo.tags) ?? repo.tags[repo.tags.length - 1]
    if (tag) await get().selectTag(tag.name)
  },

  selectTag: async (name) => {
    const repo = get().repo
    if (!repo) return
    const reqId = ++graphRequest
    set({ currentTag: name, graphLoading: true })
    const [graph, files] = await Promise.all([
      api.getGraph(repo.id, name),
      api.listFiles(repo.id, name).catch(() => [] as FileEntry[]),
    ])
    if (reqId !== graphRequest) return
    let { tier, systemId, moduleId } = get()
    let toast: string | null = null
    if (!graph) {
      tier = 1; systemId = null; moduleId = null
    } else {
      if (tier >= 2 && systemId && !graph.tier2[systemId]) {
        toast = `"${systemId}" does not exist in ${name}; showing system level`
        tier = 1; systemId = null; moduleId = null
      } else if (tier === 3 && systemId && moduleId && !graph.tier3[tier3Key(systemId, moduleId)]) {
        toast = `"${moduleId}" does not exist in ${name}; showing modules`
        tier = 2; moduleId = null
      }
    }
    set({ graph, files, graphLoading: false, tier, systemId, moduleId, selectedNodeId: null, openFile: tier === 1 ? readmeFile(files) : null, hoverRange: null, toast })
    if (get().compareMode) void get().refreshCompare()
  },

  generateTag: async (name) => {
    const repo = get().repo
    if (!repo) return
    try {
      const { job_id } = await api.generateTag(repo.id, name)
      set({ repo: await api.getRepo(repo.id) })
      startPolling(job_id)
    } catch (e) {
      set({ error: (e as Error).message })
    }
  },

  drillInto: (nodeId) => {
    const { tier, graph, systemId, moduleId } = get()
    if (!graph) return
    if (tier === 1) {
      set({ tier: 2, systemId: nodeId, moduleId: null, selectedNodeId: null, openFile: null })
    } else if (tier === 2 && systemId) {
      set({ tier: 3, moduleId: nodeId, selectedNodeId: null, openFile: null })
    } else if (tier === 3 && systemId && moduleId) {
      const snippet = graph.tier3[tier3Key(systemId, moduleId)]?.nodes.find((n) => n.id === nodeId)
      if (snippet) get().selectSnippet(snippet)
    }
  },

  goToTier: (tier) => {
    const s = get()
    if (tier === 1) set({ tier: 1, systemId: null, moduleId: null, selectedNodeId: null, openFile: readmeFile(s.files) })
    else if (tier === 2 && s.systemId) set({ tier: 2, moduleId: null, selectedNodeId: null, openFile: null })
  },

  selectSnippet: (s) => {
    set({ selectedNodeId: s.id, openFile: { path: s.file_path, startLine: s.start_line, endLine: s.end_line } })
  },

  openPath: (path, startLine, endLine) => set({ openFile: { path, startLine, endLine } }),
  setHoverRange: (hoverRange) => set({ hoverRange }),
  toggleAllFiles: () => set((s) => ({ showAllFiles: !s.showAllFiles })),
  dismissToast: () => set({ toast: null }),
  setChatDraft: (chatDraft) => set({ chatDraft }),
  askAbout: (kind, name) => set({ chatDraft: `Explain the ${kind} "${name}" at this tag: what it does, what it depends on, and what depends on it.` }),

  toggleCompareMode: () => {
    const { compareMode, repo, currentTag } = get()
    if (compareMode) { set({ compareMode: false, compareTag: null, compareGraph: null, compare: null, compareNote: null }); return }
    if (!repo || !currentTag) return
    // default compare target: the nearest earlier tag that has a graph
    const idx = repo.tags.findIndex((t) => t.name === currentTag)
    const earlier = [...repo.tags.slice(0, idx)].reverse().find((t) => t.has_graph)
    set({ compareMode: true, compareTag: earlier?.name ?? null, compare: null, compareNote: earlier ? null : 'no earlier generated tag to compare with' })
    if (earlier) void get().refreshCompare()
  },

  setCompareTag: async (name) => {
    set({ compareTag: name, compare: null, compareNote: null })
    await get().refreshCompare()
  },

  refreshCompare: async () => {
    const { repo, currentTag, compareTag } = get()
    if (!repo || !currentTag || !compareTag || compareTag === currentTag) { set({ compare: null, compareGraph: null }); return }
    try {
      const [compare, compareGraph] = await Promise.all([api.getCompare(repo.id, compareTag, currentTag), api.getGraph(repo.id, compareTag)])
      if (get().compareTag !== compareTag || get().currentTag !== currentTag) return
      set({ compare, compareGraph, compareNote: compare ? null : `no graph for ${compareTag} yet` })
    } catch (e) {
      set({ compare: null, compareGraph: null, compareNote: (e as Error).message })
    }
  },

  setLeftTab: (leftTab) => set({ leftTab }),

  writeOverview: async (force = false) => {
    const { repo, currentTag, graph } = get()
    if (!repo || !currentTag || !graph) return
    set({ overviewBusy: true, error: null })
    try {
      const r = await api.writeOverview(repo.id, currentTag, force)
      if (get().currentTag === currentTag) set((s) => ({ graph: s.graph ? { ...s.graph, overview: r.overview } : s.graph }))
    } catch (e) {
      set({ error: (e as Error).message })
    } finally {
      set({ overviewBusy: false })
    }
  },

  setTimelineMode: (timelineMode) => {
    try { localStorage.setItem('timelineMode', timelineMode) } catch { /* ignore */ }
    set({ timelineMode })
  },

  summarizeCompare: async () => {
    const { repo, compare } = get()
    if (!repo || !compare) return
    set({ summarizing: true })
    try {
      const r = await api.summarizeCompare(repo.id, compare.from, compare.to)
      set((s) => ({ compare: s.compare ? { ...s.compare, summary: r.summary } : s.compare }))
    } catch (e) {
      set({ compareNote: (e as Error).message })
    } finally {
      set({ summarizing: false })
    }
  },
  clearChat: () => set({ chat: [] }),

  sendChat: async (text) => {
    const { repo, currentTag, tier, systemId, moduleId, selectedNodeId, openFile, chat, chatBusy, compareMode, compareTag } = get()
    if (!repo || !currentTag || chatBusy || !text.trim()) return
    const history = [...chat, { role: 'user' as const, content: text }]
    set({ chat: [...history, { role: 'assistant', content: '', activity: [], streaming: true }], chatBusy: true })
    const update = (fn: (m: ChatMessage) => ChatMessage) =>
      set((s) => { const c = [...s.chat]; c[c.length - 1] = fn(c[c.length - 1]); return { chat: c } })
    try {
      await streamChat(
        {
          repo_id: repo.id, tag: currentTag, tier, system_id: systemId, module_id: moduleId,
          selected_node: selectedNodeId, open_file: openFile?.path ?? null,
          compare_tag: compareMode ? compareTag : null,
          messages: history.map((m) => ({ role: m.role, content: m.content })),
        },
        (e) => {
          if (e.type === 'text') update((m) => ({ ...m, content: m.content + e.text }))
          else if (e.type === 'tool_use') update((m) => ({ ...m, activity: [...(m.activity ?? []), `${e.name}(${Object.values(e.input).join(', ')})`] }))
          else if (e.type === 'error') update((m) => ({ ...m, content: m.content + `\n\n_${e.message}_` }))
        },
      )
    } catch (e) {
      update((m) => ({ ...m, content: m.content + `\n\n_error: ${(e as Error).message}_` }))
    } finally {
      update((m) => ({ ...m, streaming: false }))
      set({ chatBusy: false })
    }
  },
}))

let pollRun = 0

/** Follow a job until it finishes. In local mode the server works in the background and we
 *  poll. In chunked mode (Vercel) nothing runs unless we ask: each POST /step performs one
 *  time-boxed slice, so the browser drives the job by calling step until it reports done. */
function startPolling(jobId: number) {
  const run = ++pollRun
  const sleep = (ms: number) => new Promise((r) => window.setTimeout(r, ms))
  const loop = async () => {
    while (run === pollRun) {
      const s = useAppStore.getState()
      const chunked = s.health?.generation_mode === 'chunked'
      try {
        const job = chunked ? await api.stepJob(jobId) : await api.getJob(jobId)
        const repo = s.repo ? await api.getRepo(s.repo.id) : null
        if (run !== pollRun) return
        useAppStore.setState({ job, repo: repo ?? s.repo })
        if (repo) {
          const cur = s.currentTag ? repo.tags.find((t) => t.name === s.currentTag) : undefined
          if (!s.currentTag) {
            const t = newestGeneratedTag(repo.tags) ?? repo.tags[repo.tags.length - 1]
            if (t) await useAppStore.getState().selectTag(t.name)
          } else if (cur?.has_graph && !s.graph && !s.graphLoading) {
            await useAppStore.getState().selectTag(cur.name)
          }
        }
        if (job.status === 'done' || job.status === 'failed') {
          if (job.status === 'failed') useAppStore.setState({ error: job.error ?? 'generation failed' })
          useAppStore.setState({ repos: await api.listRepos() })
          return
        }
      } catch {
        /* transient; keep going */
      }
      if (!chunked) await sleep(2000)
    }
  }
  void loop()
}
