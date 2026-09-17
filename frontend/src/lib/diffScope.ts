import { tier3Key, type DiffResult, type DiffScope, type GraphEdge, type GraphResponse, type Tier } from '../types/graph'

/** The part of a diff that applies to what the user is looking at. */
export function scopeDiff(diff: DiffResult | undefined, tier: Tier, systemId: string | null, moduleId: string | null): DiffScope | undefined {
  if (!diff) return undefined
  if (tier === 1) return diff.tier1
  if (tier === 2 && systemId) return diff.tier2[systemId]
  if (tier === 3 && systemId && moduleId) return diff.tier3[tier3Key(systemId, moduleId)]
  return undefined
}

export type ScopeItem = { id: string; name: string }
export type ScopeEdge = GraphEdge

/** Names of the nodes and the edges in the current scope of a graph (for chips and tooltips). */
export function scopeContents(g: GraphResponse | null, tier: Tier, systemId: string | null, moduleId: string | null): { nodes: ScopeItem[]; edges: ScopeEdge[] } {
  if (!g) return { nodes: [], edges: [] }
  if (tier === 1) return { nodes: g.tier1.nodes.map((n) => ({ id: n.id, name: n.name })), edges: g.tier1.edges }
  if (tier === 2 && systemId) { const s = g.tier2[systemId]; return { nodes: (s?.nodes ?? []).map((n) => ({ id: n.id, name: n.name })), edges: s?.edges ?? [] } }
  if (tier === 3 && systemId && moduleId) { const s = g.tier3[tier3Key(systemId, moduleId)]; return { nodes: (s?.nodes ?? []).map((n) => ({ id: n.id, name: n.title })), edges: s?.edges ?? [] } }
  return { nodes: [], edges: [] }
}

export function scopeLabel(g: GraphResponse | null, tier: Tier, systemId: string | null, moduleId: string | null): { things: string; where: string } {
  if (tier === 1) return { things: 'components', where: 'system level' }
  const sys = g?.tier1.nodes.find((n) => n.id === systemId)
  if (tier === 2) return { things: 'modules', where: sys?.name ?? systemId ?? '' }
  const mod = systemId ? g?.tier2[systemId]?.nodes.find((n) => n.id === moduleId) : undefined
  return { things: 'snippets', where: mod?.name ?? moduleId ?? '' }
}
