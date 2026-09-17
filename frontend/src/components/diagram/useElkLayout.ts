import { useEffect, useState } from 'react'
import type { ELK, ElkNode, ElkExtendedEdge } from 'elkjs/lib/elk-api'
import type { Edge, Node } from '@xyflow/react'

// elkjs is ~700 KB; load it the first time a diagram needs a layout
let elkPromise: Promise<ELK> | null = null
const getElk = () => (elkPromise ??= import('elkjs/lib/elk.bundled.js').then((m) => new m.default() as ELK))

export const NODE_SIZE: Record<string, { width: number; height: number }> = {
  system: { width: 220, height: 92 },
  module: { width: 220, height: 84 },
  snippet: { width: 240, height: 92 },
}

export type Point = { x: number; y: number }
export type EdgeRoute = { points: Point[]; label?: { x: number; y: number; width: number; height: number } }

/** Approximate rendered size of an edge label pill, so ELK can reserve room for it. */
export function labelSize(text: string): { width: number; height: number } {
  return { width: Math.round(text.length * 6.2) + 16, height: 20 }
}

/**
 * ELK lays out nodes AND routes the edges (orthogonal), placing each edge label inline on
 * its own edge with space reserved, so labels never overlap each other or nodes. The routed
 * polyline and the label box are returned on each edge's `data.route`.
 */
export function useElkLayout(nodes: Node[], edges: Edge[], layoutKey: string) {
  const [result, setResult] = useState<{ key: string; nodes: Node[]; edges: Edge[] }>({ key: '', nodes: [], edges: [] })

  useEffect(() => {
    let cancelled = false
    if (nodes.length === 0) {
      setResult({ key: layoutKey, nodes: [], edges: [] })
      return
    }
    const graph: ElkNode = {
      id: 'root',
      layoutOptions: {
        'elk.algorithm': 'layered',
        'elk.direction': 'DOWN',
        'elk.edgeRouting': 'ORTHOGONAL',
        'elk.spacing.nodeNode': '48',
        'elk.spacing.edgeNode': '28',
        'elk.spacing.edgeEdge': '18',
        'elk.spacing.edgeLabel': '8',
        'elk.layered.spacing.nodeNodeBetweenLayers': '90',
        'elk.layered.spacing.edgeNodeBetweenLayers': '32',
        'elk.layered.spacing.edgeEdgeBetweenLayers': '18',
        'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
        'elk.edgeLabels.inline': 'true',
        'elk.layered.edgeLabels.sideSelection': 'SMART_DOWN',
        'elk.layered.mergeEdges': 'false',
      },
      children: nodes.map((n) => {
        const size = NODE_SIZE[n.type ?? 'system']
        return { id: n.id, width: size.width, height: size.height }
      }),
      edges: edges.map((e) => {
        const text = String((e.data as { labelText?: string } | undefined)?.labelText ?? '')
        const edge: ElkExtendedEdge = { id: e.id, sources: [e.source], targets: [e.target] }
        if (text) edge.labels = [{ text, ...labelSize(text) }]
        return edge
      }),
    }
    getElk().then((elk) => elk.layout(graph)).then((laid) => {
      if (cancelled) return
      const pos = new Map((laid.children ?? []).map((c) => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }]))
      const routes = new Map<string, EdgeRoute>()
      for (const e of (laid.edges ?? []) as ElkExtendedEdge[]) {
        const s = e.sections?.[0]
        if (!s) continue
        const points = [s.startPoint, ...(s.bendPoints ?? []), s.endPoint]
        const l = e.labels?.[0]
        routes.set(e.id, { points, label: l && l.x !== undefined && l.y !== undefined ? { x: l.x, y: l.y, width: l.width ?? 0, height: l.height ?? 0 } : undefined })
      }
      setResult({
        key: layoutKey,
        nodes: nodes.map((n) => ({ ...n, position: pos.get(n.id) ?? { x: 0, y: 0 } })),
        edges: edges.map((e) => ({ ...e, data: { ...e.data, route: routes.get(e.id) } })),
      })
    })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey])

  return result
}
