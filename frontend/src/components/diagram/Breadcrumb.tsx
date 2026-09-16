import { useAppStore } from '../../store/useAppStore'
import { tier3Key } from '../../types/graph'

export function Breadcrumb() {
  const { graph, tier, systemId, moduleId, goToTier } = useAppStore()
  const system = systemId ? graph?.tier1.nodes.find((n) => n.id === systemId) : undefined
  const module = systemId && moduleId ? graph?.tier2[systemId]?.nodes.find((n) => n.id === moduleId) : undefined
  const snippetCount = systemId && moduleId ? graph?.tier3[tier3Key(systemId, moduleId)]?.nodes.length ?? 0 : 0
  return (
    <div className="breadcrumb">
      <button className={tier === 1 ? 'crumb active' : 'crumb'} onClick={() => goToTier(1)}>System</button>
      {system && (<><span className="crumb-sep">›</span><button className={tier === 2 ? 'crumb active' : 'crumb'} onClick={() => goToTier(2)}>{system.name}</button></>)}
      {module && (<><span className="crumb-sep">›</span><span className="crumb active">{module.name}</span><span className="crumb-hint">{snippetCount} snippets</span></>)}
      <span className="crumb-tier">tier {tier}</span>
    </div>
  )
}
