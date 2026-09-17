export type EdgeKind = 'http' | 'rpc' | 'queue' | 'reads' | 'writes' | 'imports' | 'calls'
export type SystemKind = 'api' | 'service' | 'frontend' | 'worker' | 'datastore' | 'external'

export interface GraphEdge { source: string; target: string; kind: EdgeKind; label: string }
export interface SystemNode { id: string; name: string; kind: SystemKind; description: string; paths: string[] }
export interface Tier1Graph { summary: string; nodes: SystemNode[]; edges: GraphEdge[] }
export interface ModuleNode { id: string; name: string; description: string; paths: string[] }
export interface Tier2Graph { nodes: ModuleNode[]; edges: GraphEdge[] }
export interface SnippetNode { id: string; title: string; description: string; file_path: string; start_line: number; end_line: number }
export interface Tier3Graph { nodes: SnippetNode[]; edges: GraphEdge[] }

export interface GraphResponse {
  tag: string
  sha: string
  tier1: Tier1Graph
  tier2: Record<string, Tier2Graph>
  tier3: Record<string, Tier3Graph>
  change_summary: string | null
  overview: string | null
  model: string
  prompt_version: string
  generated_at: string | null
}

export type TagStatus = 'none' | 'queued' | 'running' | 'done' | 'failed'
export interface TagInfo { name: string; sha: string; tagged_at: string | null; order_index: number; status: TagStatus; has_graph: boolean; error: string | null }
export interface RepoDetail { id: number; url: string; owner: string; name: string; default_branch: string | null; tags: TagInfo[] }
export interface RepoSummary { id: number; url: string; owner: string; name: string; tag_count: number; generated_count: number }
export interface Job { id: number; repo_id: number; tag: string | null; status: 'queued' | 'running' | 'done' | 'failed'; step: string; progress: number; detail: string | null; error: string | null }
export interface Health { ok: boolean; generation_enabled: boolean; generation_mode: 'local' | 'chunked' | 'off'; demo_mode: boolean; db: string; file_source: string; model: string; auth: string }
export interface FileEntry { path: string; language: string | null; size: number }
export interface FileContent { path: string; language: string | null; content: string; sha: string }

export type Tier = 1 | 2 | 3
export interface OpenFile { path: string; startLine?: number; endLine?: number }
export interface ChatMessage { role: 'user' | 'assistant'; content: string; activity?: string[]; streaming?: boolean }

export const tier3Key = (systemId: string, moduleId: string) => `${systemId}/${moduleId}`

export type DiffStatus = 'added' | 'removed' | 'changed' | 'modified' | 'unchanged'
export interface DiffScope { nodes: Record<string, DiffStatus>; edges: Record<string, DiffStatus>; counts: Record<DiffStatus, number>; edge_counts: Record<'added' | 'removed' | 'unchanged', number> }
export interface DiffResult { tier1: DiffScope; tier2: Record<string, DiffScope>; tier3: Record<string, DiffScope> }
export interface CompareResult { from: string; to: string; diff: DiffResult; summary: string | null }
export const edgeKey = (e: GraphEdge) => `${e.source}|${e.target}|${e.kind}`
