import { useAppStore } from '../../store/useAppStore'
import { Markdown } from '../shared/Markdown'

export function OverviewPane() {
  const { graph, currentTag, health, overviewBusy, writeOverview } = useAppStore()
  if (!graph) return null
  if (!graph.overview) {
    return (
      <div className="pane-empty overview-empty">
        <h3>No overview for {currentTag} yet</h3>
        <p className="hint">A written walkthrough of the architecture at this tag: what it is, its components, how a request flows, design notes, and where to start reading. One {health?.model ?? 'model'} call, cached afterwards.</p>
        <button className="btn primary" disabled={overviewBusy || health?.auth === 'none'} onClick={() => writeOverview()}>
          {overviewBusy ? 'writing…' : 'Write overview'}
        </button>
      </div>
    )
  }
  return (
    <div className="overview-body">
      <div className="overview-toolbar">
        <span className="muted">overview of {currentTag}</span>
        <button className="btn tiny" disabled={overviewBusy} onClick={() => writeOverview(true)} title="regenerate (one model call)">{overviewBusy ? 'writing…' : 'rewrite'}</button>
      </div>
      <article className="overview-article"><Markdown>{graph.overview}</Markdown></article>
    </div>
  )
}
