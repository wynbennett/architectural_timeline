import { useState } from 'react'
import { useAppStore } from '../../store/useAppStore'
import { scopeContents, scopeDiff, scopeLabel } from '../../lib/diffScope'
import { edgeKey, type DiffStatus } from '../../types/graph'

const SIGN: Record<DiffStatus, string> = { added: '+', removed: '−', changed: '↔', modified: '✎', unchanged: '' }
const WORD: Record<DiffStatus, string> = { added: 'added', removed: 'removed', changed: 're-scoped', modified: 'modified', unchanged: 'unchanged' }
const HINT: Record<DiffStatus, string> = {
  added: 'exists in the newer tag only',
  removed: 'existed in the older tag only (drawn as a dashed ghost)',
  changed: 'still exists, but its paths or kind moved',
  modified: 'same paths, but the code under them changed',
  unchanged: 'identical paths and file contents',
}

const CHIP_LIMIT = 10

export function CompareBanner() {
  const [showAll, setShowAll] = useState(false)
  const { compareMode, compareTag, currentTag, compare, compareNote, summarizing, summarizeCompare, sendChat, chatBusy, health, graph, compareGraph, tier, systemId, moduleId } = useAppStore()
  if (!compareMode) return null

  const scope = scopeDiff(compare?.diff, tier, systemId, moduleId)
  const { things, where } = scopeLabel(graph, tier, systemId, moduleId)
  const cur = scopeContents(graph, tier, systemId, moduleId)
  const old = scopeContents(compareGraph, tier, systemId, moduleId)
  const nameOf = (id: string) => cur.nodes.find((n) => n.id === id)?.name ?? old.nodes.find((n) => n.id === id)?.name ?? id
  const nodeChips = scope ? (['added', 'removed', 'changed', 'modified'] as DiffStatus[]).flatMap((st) => Object.entries(scope.nodes).filter(([, s]) => s === st).map(([id]) => ({ id, st }))) : []
  const edgeChips = scope
    ? [...cur.edges.map((e) => ({ e, st: scope.edges[edgeKey(e)] })), ...old.edges.filter((e) => scope.edges[edgeKey(e)] === 'removed').map((e) => ({ e, st: 'removed' as DiffStatus }))]
        .filter(({ st }) => st === 'added' || st === 'removed')
    : []
  const c = scope?.counts
  const ec = scope?.edge_counts

  return (
    <div className="compare-banner">
      <span className="compare-title">compare</span>
      <span><strong>{compareTag ?? '?'}</strong> <span className="muted">→</span> <strong>{currentTag}</strong></span>
      <span className="muted">· {where}</span>
      {c && (
        <span className="compare-counts" title={`${things} at this level`}>
          <span className="muted">{things}</span>
          {(['added', 'removed', 'changed', 'modified'] as DiffStatus[]).map((st) => (
            <span key={st} className={`diff-${st}`} title={HINT[st]}>{SIGN[st]}{c[st] ?? 0} {WORD[st]}</span>
          ))}
          <span className="muted">{c.unchanged} unchanged</span>
        </span>
      )}
      {ec && (
        <span className="compare-counts" title="connections (edges) at this level">
          <span className="muted">connections</span>
          <span className="diff-added" title="drawn as a solid green line">+{ec.added} added</span>
          <span className="diff-removed" title="drawn as a dashed red line">−{ec.removed} removed</span>
          <span className="muted">{ec.unchanged} unchanged</span>
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
      {(nodeChips.length > 0 || edgeChips.length > 0) && (
        <div className="compare-changes">
          {nodeChips.map(({ id, st }) => <span key={id} className={`change-chip change-${st}`} title={`${WORD[st]}: ${HINT[st]}`}>{SIGN[st]} {nameOf(id)}</span>)}
          {(showAll ? edgeChips : edgeChips.slice(0, Math.max(0, CHIP_LIMIT - nodeChips.length))).map(({ e, st }, i) => (
            <span key={`e${i}`} className={`change-chip change-edge change-${st}`} title={`connection ${WORD[st]}: ${e.kind}${e.label ? ` · ${e.label}` : ''}`}>
              {SIGN[st]} {nameOf(e.source)} → {nameOf(e.target)} <span className="muted">({e.kind})</span>
            </span>
          ))}
          {nodeChips.length + edgeChips.length > CHIP_LIMIT && (
            <button className="btn tiny" onClick={() => setShowAll((v) => !v)}>{showAll ? 'fewer' : `+${nodeChips.length + edgeChips.length - CHIP_LIMIT} more`}</button>
          )}
        </div>
      )}
      {scope && nodeChips.length === 0 && edgeChips.length === 0 && <span className="muted">nothing changed at this level</span>}
      {compare?.summary && (
        <details className="compare-summary">
          <summary>what changed (narrative)</summary>
          <p>{compare.summary}</p>
        </details>
      )}
      <span className="legend">
        <i className="sw sw-node sw-added" title={HINT.added} />added
        <i className="sw sw-node sw-removed" title={HINT.removed} />removed
        <i className="sw sw-node sw-changed" title={HINT.changed} />re-scoped
        <i className="sw sw-node sw-modified" title={HINT.modified} />modified
        <i className="sw sw-line sw-added" title="added connection" />
        <i className="sw sw-line sw-removed" title="removed connection" />connections
      </span>
    </div>
  )
}
