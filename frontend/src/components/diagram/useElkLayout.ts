import { useEffect, useState } from 'react'
import type { ELK, ElkNode } from 'elkjs/lib/elk-api'
import type { Edge, Node } from '@xyflow/react'

// elkjs is ~700 KB; load it the first time a diagram needs a layout
let elkPromise: Promise<ELK> | null = null
const getElk = () => (elkPromise ??= import('elkjs/lib/elk.bundled.js').then((m) => new m.default() as ELK))

export const NODE_SIZE: Record<string, { width: number; height: number }> = {
  system: { width: 220, height: 92 },
  module: { width: 220, height: 84 },
  snippet: { width: 240, height: 92 },
}

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
        'elk.spacing.nodeNode': '40',
        'elk.layered.spacing.nodeNodeBetweenLayers': '70',
        'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
        'elk.edgeRouting': 'ORTHOGONAL',
      },
      children: nodes.map((n) => {
        const size = NODE_SIZE[n.type ?? 'system']
        return { id: n.id, width: size.width, height: size.height }
      }),
      edges: edges.map((e) => ({ id: e.id, sources: [e.source], targets: [e.target] })),
    }
    getElk().then((elk) => elk.layout(graph)).then((laid) => {
      if (cancelled) return
      const pos = new Map((laid.children ?? []).map((c) => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }]))
      setResult({
        key: layoutKey,
        nodes: nodes.map((n) => ({ ...n, position: pos.get(n.id) ?? { x: 0, y: 0 } })),
        edges,
      })
    })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey])

  return result
}
