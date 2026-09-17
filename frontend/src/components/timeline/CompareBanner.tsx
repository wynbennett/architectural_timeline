import { useAppStore } from '../../store/useAppStore'

export function CompareBanner() {
  const { compareMode, compareTag, currentTag, compare, compareNote, summarizing, summarizeCompare, sendChat, chatBusy, health, graph, compareGraph } = useAppStore()
  if (!compareMode) return null
  const c = compare?.diff.tier1.counts
  const nameOf = (id: string) => graph?.tier1.nodes.find((n) => n.id === id)?.name ?? compareGraph?.tier1.nodes.find((n) => n.id === id)?.name ?? id
  const changed = compare ? (['added', 'removed', 'changed'] as const).flatMap((st) => Object.entries(compare.diff.tier1.nodes).filter(([, s]) => s === st).map(([id]) => ({ id, st }))) : []
  return (
    <div className="compare-banner">
      <span className="compare-title">compare</span>
      <span><strong>{compareTag ?? '?'}</strong> <span className="muted">→</span> <strong>{currentTag}</strong></span>
      {c && (
        <span className="compare-counts">
          <span className="diff-added">+{c.added} added</span>
          <span className="diff-removed">−{c.removed} removed</span>
          <span className="diff-changed">~{c.changed} changed</span>
          <span className="muted">{c.unchanged} unchanged</span>
        </span>
      )}
      {compareNote && <span className="error-text">{compareNote}</span>}
      {compare && !compare.summary && (
        <button className="btn tiny" disabled={summarizing} onClick={() => summarizeCompare()} title={`One ${health?.model ?? 'model'} call; cached afterwards`}>
          {summarizing ? 'summarizing…' : 'Summarize changes'}
        </button>
      )}
      {compare && (
        <button className="btn tiny" disabled={chatBusy} onClick={() => sendChat(`What changed between ${compare.from} and ${compare.to}, and why?`)}>Ask what changed</button>
      )}
      {changed.length > 0 && (
        <div className="compare-changes">
          {changed.map(({ id, st }) => <span key={id} className={`change-chip change-${st}`} title={`${st}: ${id}`}>{st === 'added' ? '+' : st === 'removed' ? '−' : '~'} {nameOf(id)}</span>)}
        </div>
      )}
      {compare?.summary && <p className="compare-summary">{compare.summary}</p>}
      <span className="legend"><i className="sw sw-added" />added <i className="sw sw-removed" />removed <i className="sw sw-changed" />changed</span>
    </div>
  )
}
