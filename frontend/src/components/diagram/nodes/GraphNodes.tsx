import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import type { DiffStatus, SystemKind } from '../../../types/graph'
import { useAppStore } from '../../../store/useAppStore'

type Common = { label: string; description: string; status?: DiffStatus }
export type SystemNodeData = Common & { kind: SystemKind; paths: string[] }
export type ModuleNodeData = Common & { paths: string[] }
export type SnippetNodeData = Common & { filePath: string; startLine: number; endLine: number; selected: boolean }

const statusClass = (s?: DiffStatus) => (s && s !== 'unchanged' ? ` diff-${s}` : '')

function AskButton({ kind, name }: { kind: string; name: string }) {
  const askAbout = useAppStore((s) => s.askAbout)
  return (
    <button className="ask-btn nodrag" title="Ask the chat about this" onClick={(e) => { e.stopPropagation(); askAbout(kind, name) }}>?</button>
  )
}

function StatusTag({ status }: { status?: DiffStatus }) {
  if (!status || status === 'unchanged') return null
  return <span className={`status-tag status-${status}`}>{status}</span>
}

const KIND_ICON: Record<SystemKind, string> = { api: '⇄', service: '⚙', frontend: '▣', worker: '⟳', datastore: '🛢', external: '☁' }

function Ports() {
  return (
    <>
      <Handle type="target" position={Position.Top} className="port" />
      <Handle type="source" position={Position.Bottom} className="port" />
    </>
  )
}

export function SystemNodeView({ data }: NodeProps<Node<SystemNodeData>>) {
  return (
    <div className={`gnode gnode-system kind-${data.kind}${statusClass(data.status)}`} title={data.description}>
      <Ports />
      <AskButton kind={`${data.kind} component`} name={data.label} />
      <div className="gnode-head"><span className="gnode-icon">{KIND_ICON[data.kind]}</span><span className="gnode-kind">{data.kind}</span><StatusTag status={data.status} /></div>
      <div className="gnode-title">{data.label}</div>
      <div className="gnode-desc">{data.description}</div>
    </div>
  )
}

export function ModuleNodeView({ data }: NodeProps<Node<ModuleNodeData>>) {
  return (
    <div className={`gnode gnode-module${statusClass(data.status)}`} title={data.description}>
      <Ports />
      <AskButton kind="module" name={data.label} />
      <StatusTag status={data.status} />
      <div className="gnode-title">{data.label}</div>
      <div className="gnode-desc">{data.description}</div>
      <div className="gnode-meta">{data.paths.length} path{data.paths.length === 1 ? '' : 's'}</div>
    </div>
  )
}

export function SnippetNodeView({ data }: NodeProps<Node<SnippetNodeData>>) {
  return (
    <div className={`gnode gnode-snippet${data.selected ? ' is-selected' : ''}${statusClass(data.status)}`} title={data.description}>
      <Ports />
      <AskButton kind="code snippet" name={data.label} />
      <StatusTag status={data.status} />
      <div className="gnode-title">{data.label}</div>
      <div className="gnode-desc">{data.description}</div>
      <div className="gnode-meta mono">{data.filePath}:{data.startLine}-{data.endLine}</div>
    </div>
  )
}

export const nodeTypes = { system: SystemNodeView, module: ModuleNodeView, snippet: SnippetNodeView }
