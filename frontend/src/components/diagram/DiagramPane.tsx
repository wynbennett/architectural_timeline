import { useEffect, useMemo } from 'react'
import { Background, Controls, MarkerType, ReactFlow, ReactFlowProvider, useReactFlow, type Edge, type Node } from '@xyflow/react'
import { useAppStore } from '../../store/useAppStore'
import { edgeKey, tier3Key, type DiffScope, type GraphEdge, type GraphResponse, type Tier } from '../../types/graph'
import { nodeTypes } from './nodes/GraphNodes'
import { edgeTypes } from './StatusEdge'
import { scopeDiff } from '../../lib/diffScope'
import { useElkLayout } from './useElkLayout'
import { Breadcrumb } from './Breadcrumb'
import { GenerateEmptyState } from '../timeline/GenerateEmptyState'
import { OverviewPane } from './OverviewPane'

function toEdges(edges: GraphEdge[], prefix: string, names: Map<string, string>, diff?: DiffScope, compare?: { from: string; to: string }): Edge[] {
  return edges.map((e, i) => {
    const status = diff?.edges[edgeKey(e)]
    const base = e.label || e.kind
    // what the label pill will say; ELK reserves room for exactly this text
    const labelText = compare ? (status === 'added' ? `+ ${base}` : status === 'removed' ? `− ${base}` : '') : base
    return {
      id: `${prefix}-${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      type: 'status',
      data: { kind: e.kind, label: e.label, labelText, status, sourceName: names.get(e.source) ?? e.source, targetName: names.get(e.target) ?? e.target, compare },
      markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
      className: `edge-${e.kind}${status && status !== 'unchanged' ? ` edge-${status}` : ''}${compare && status === 'unchanged' ? ' edge-dim' : ''}`,
    }
  })
}

/** Nodes/edges of the scope the user is looking at, for one graph. */
function scopeOf(g: GraphResponse, tier: Tier, systemId: string | null, moduleId: string | null) {
  if (tier === 1) return { nodes: g.tier1.nodes.map((n) => ({ id: n.id, type: 'system', data: { label: n.name, kind: n.kind, description: n.description, paths: n.paths } })), edges: g.tier1.edges }
  if (tier === 2 && systemId) {
    const s = g.tier2[systemId]
    return { nodes: (s?.nodes ?? []).map((n) => ({ id: n.id, type: 'module', data: { label: n.name, description: n.description, paths: n.paths } })), edges: s?.edges ?? [] }
  }
  if (tier === 3 && systemId && moduleId) {
    const s = g.tier3[tier3Key(systemId, moduleId)]
    return { nodes: (s?.nodes ?? []).map((n) => ({ id: n.id, type: 'snippet', data: { label: n.title, description: n.description, filePath: n.file_path, startLine: n.start_line, endLine: n.end_line, selected: false } })), edges: s?.edges ?? [] }
  }
  return { nodes: [], edges: [] as GraphEdge[] }
}

function Canvas() {
  const { graph, tier, systemId, moduleId, selectedNodeId, drillInto, setHoverRange, currentTag, compareMode, compare, compareGraph, theme } = useAppStore()
  const { fitView } = useReactFlow()

  const { rawNodes, rawEdges, key } = useMemo(() => {
    if (!graph) return { rawNodes: [] as Node[], rawEdges: [] as Edge[], key: 'empty' }
    const scope = scopeOf(graph, tier, systemId, moduleId)
    const diff = compareMode && compare ? scopeDiff(compare.diff, tier, systemId, moduleId) : undefined
    const pair = compareMode && compare ? { from: compare.from, to: compare.to } : undefined
    const nodes: Node[] = scope.nodes.map((n) => ({ ...n, position: { x: 0, y: 0 }, data: { ...n.data, status: diff?.nodes[n.id] } }))
    const names = new Map(nodes.map((n) => [n.id, String((n.data as { label: string }).label)]))
    if (diff && compareGraph) {
      // ghosts: things that existed in the compare tag but not in the current one
      const prev = scopeOf(compareGraph, tier, systemId, moduleId)
      const have = new Set(nodes.map((n) => n.id))
      for (const n of prev.nodes) {
        if (diff.nodes[n.id] === 'removed' && !have.has(n.id)) {
          nodes.push({ ...n, position: { x: 0, y: 0 }, data: { ...n.data, status: 'removed' }, selectable: false, draggable: false })
          have.add(n.id)
          names.set(n.id, String((n.data as { label: string }).label))
        }
      }
      const removedEdges = prev.edges.filter((e) => diff.edges[edgeKey(e)] === 'removed' && have.has(e.source) && have.has(e.target))
      const edges = toEdges(scope.edges, `t${tier}`, names, diff, pair).concat(toEdges(removedEdges, 'rm', names, diff, pair))
      const scopeKey = tier === 1 ? '1' : tier === 2 ? `2:${systemId}` : `3:${systemId}/${moduleId}`
      return { rawNodes: nodes, rawEdges: edges, key: `${currentTag}:${scopeKey}:vs:${compare!.from}` }
    }
    const edges = toEdges(scope.edges, `t${tier}`, names, diff, pair)
    const scopeKey = tier === 1 ? '1' : tier === 2 ? `2:${systemId}` : `3:${systemId}/${moduleId}`
    return { rawNodes: nodes, rawEdges: edges, key: `${currentTag}:${scopeKey}` }
  }, [graph, tier, systemId, moduleId, currentTag, compareMode, compare, compareGraph])

  const laid = useElkLayout(rawNodes, rawEdges, key)
  const nodes = useMemo(
    () => laid.nodes.map((n) => (n.type === 'snippet' ? { ...n, data: { ...n.data, selected: n.id === selectedNodeId } } : n)),
    [laid.nodes, selectedNodeId],
  )

  useEffect(() => {
    if (laid.key === key && laid.nodes.length) {
      // wait until React Flow has measured the new nodes (two frames), then fit
      let raf2 = 0
      const raf1 = window.requestAnimationFrame(() => { raf2 = window.requestAnimationFrame(() => { void fitView({ padding: 0.15, duration: 300 }) }) })
      const t = window.setTimeout(() => { void fitView({ padding: 0.15, duration: 200 }) }, 250)
      return () => { window.cancelAnimationFrame(raf1); window.cancelAnimationFrame(raf2); window.clearTimeout(t) }
    }
  }, [laid, key, fitView])

  const empty = laid.key === key && laid.nodes.length === 0
  return (
    <div className="diagram-canvas">
      <ReactFlow
        nodes={nodes}
        edges={laid.edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={(_, n) => { if ((n.data as { status?: string }).status !== 'removed') drillInto(n.id) }}
        onNodeMouseEnter={(_, n) => { if (n.type === 'snippet') { const d = n.data as { filePath: string; startLine: number; endLine: number }; setHoverRange({ path: d.filePath, startLine: d.startLine, endLine: d.endLine }) } }}
        onNodeMouseLeave={() => setHoverRange(null)}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        minZoom={0.2}
        colorMode={theme}
      >
        <Background gap={24} />
        <Controls showInteractive={false} />
      </ReactFlow>
      {empty && <div className="diagram-empty-note">Nothing to show at this level.</div>}
    </div>
  )
}

export function DiagramPane() {
  const { graph, graphLoading, currentTag, leftTab, setLeftTab } = useAppStore()
  return (
    <div className="pane diagram-pane">
      <div className="pane-header">
        <div className="tabs">
          <button className={`tab${leftTab === 'diagram' ? ' active' : ''}`} onClick={() => setLeftTab('diagram')}>Diagram</button>
          <button className={`tab${leftTab === 'overview' ? ' active' : ''}`} onClick={() => setLeftTab('overview')} disabled={!graph}>
            Overview{graph?.overview ? '' : graph ? ' ○' : ''}
          </button>
        </div>
      </div>
      {graphLoading ? (
        <div className="pane-empty">Loading {currentTag}…</div>
      ) : !graph ? (
        <GenerateEmptyState />
      ) : leftTab === 'overview' ? (
        <OverviewPane />
      ) : (
        <div className="diagram-tab">
          <div className="diagram-toolbar">
            <Breadcrumb />
            {graph.tier1.summary && <span className="pane-header-hint" title={graph.tier1.summary}>ⓘ summary</span>}
          </div>
          <ReactFlowProvider><Canvas /></ReactFlowProvider>
        </div>
      )}
    </div>
  )
}
