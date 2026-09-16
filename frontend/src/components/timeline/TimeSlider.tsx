import { useMemo, useState } from 'react'
import Slider from 'rc-slider'
import { useAppStore, visibleTags, type TimelineMode } from '../../store/useAppStore'
import type { TagInfo } from '../../types/graph'

function statusGlyph(t: TagInfo): { glyph: string; cls: string } {
  if (t.has_graph) return { glyph: '●', cls: 'done' }
  if (t.status === 'running' || t.status === 'queued') return { glyph: '◐', cls: 'running' }
  if (t.status === 'failed') return { glyph: '✕', cls: 'failed' }
  return { glyph: '○', cls: 'none' }
}

export function TimeSlider() {
  const { repo, currentTag, selectTag, compareMode, compareTag, setCompareTag, timelineMode, setTimelineMode } = useAppStore()
  const allTags = repo?.tags ?? []
  // Only the tags in scope are slider stops, spaced evenly, so the thumb always lands on a tag.
  const tags = useMemo(() => visibleTags(allTags, timelineMode, [currentTag, compareTag]), [allTags, timelineMode, currentTag, compareTag])
  const currentIdx = Math.max(0, tags.findIndex((t) => t.name === currentTag))
  const compareIdx = compareTag ? Math.max(0, tags.findIndex((t) => t.name === compareTag)) : Math.max(0, currentIdx - 1)
  const generatedCount = allTags.filter((t) => t.has_graph).length
  const modes: { id: TimelineMode; label: string; count: number }[] = [
    { id: 'generated', label: 'generated', count: generatedCount },
    { id: 'recent', label: 'recent', count: visibleTags(allTags, 'recent', []).length },
    { id: 'all', label: 'all', count: allTags.length },
  ]
  const [dragIdx, setDragIdx] = useState<number | null>(null)
  const shownIdx = dragIdx ?? currentIdx
  const shown = tags[shownIdx]

  const marks = useMemo(() => {
    const m: Record<number, React.ReactNode> = {}
    const step = tags.length > 24 ? Math.ceil(tags.length / 24) : 1
    tags.forEach((t, i) => {
      const { glyph, cls } = statusGlyph(t)
      const showLabel = i % step === 0 || i === tags.length - 1
      m[i] = (
        <span className={`mark mark-${cls}${i === shownIdx ? ' mark-current' : ''}${compareMode && i === compareIdx ? ' mark-compare' : ''}`} title={`${t.name} (${t.status})`}>
          <span className="mark-glyph">{glyph}</span>
          {showLabel && <span className="mark-label">{t.name}</span>}
        </span>
      )
    })
    return m
  }, [tags, shownIdx, compareMode, compareIdx])

  if (!repo) return <div className="timeline timeline-empty">time machine: load a repo to see its tags</div>
  if (allTags.length === 0) return <div className="timeline timeline-empty">no tags in {repo.owner}/{repo.name}</div>

  return (
    <div className="timeline">
      <div className="timeline-label">
        <span className="timeline-title">time machine</span>
        <span className="timeline-scope">
          {modes.map((m) => (
            <button key={m.id} className={`scope-btn${timelineMode === m.id ? ' active' : ''}`} onClick={() => setTimelineMode(m.id)} title={`show ${m.label} tags`}>
              {m.label} <span className="muted">{m.count}</span>
            </button>
          ))}
          <select className="tag-jump" value="" onChange={(e) => { if (e.target.value) void selectTag(e.target.value) }} title="jump to any tag">
            <option value="">jump to tag…</option>
            {[...allTags].reverse().map((t) => (
              <option key={t.name} value={t.name}>{t.has_graph ? '● ' : '○ '}{t.name}</option>
            ))}
          </select>
          {tags.length < allTags.length && <span className="muted">{allTags.length - tags.length} hidden</span>}
        </span>
        {shown && (
          <span className="timeline-current">
            <strong>{shown.name}</strong>
            {shown.tagged_at && <span className="muted"> · {new Date(shown.tagged_at).toLocaleDateString()}</span>}
            <span className="muted"> · {shown.has_graph ? 'generated' : shown.status === 'none' ? 'not generated' : shown.status}</span>
          </span>
        )}
      </div>
      <div className="timeline-slider">
        {compareMode ? (
          <Slider
            range
            allowCross={false}
            min={0}
            max={tags.length - 1}
            step={1}
            value={[compareIdx, currentIdx]}
            marks={marks}
            dots={false}
            onChange={(v) => { if (Array.isArray(v)) setDragIdx(v[1]) }}
            onChangeComplete={(v) => {
              if (!Array.isArray(v)) return
              const [lo, hi] = v
              setDragIdx(null)
              if (hi !== currentIdx && tags[hi]) void selectTag(tags[hi].name)
              if (lo !== compareIdx && tags[lo]) void setCompareTag(tags[lo].name)
            }}
          />
        ) : (
          <Slider
            min={0}
            max={tags.length - 1}
            step={1}
            value={shownIdx}
            marks={marks}
            dots={false}
            onChange={(v) => setDragIdx(Array.isArray(v) ? v[0] : v)}
            onChangeComplete={(v) => {
              const idx = Array.isArray(v) ? v[0] : v
              setDragIdx(null)
              const t = tags[idx]
              if (t && t.name !== currentTag) void selectTag(t.name)
            }}
          />
        )}
      </div>
    </div>
  )
}
