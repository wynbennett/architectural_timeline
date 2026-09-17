import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from '@xyflow/react'
import type { DiffStatus } from '../../types/graph'
import type { EdgeRoute, Point } from './useElkLayout'

export type StatusEdgeData = {
  kind: string; label: string; labelText: string; status?: DiffStatus
  sourceName: string; targetName: string; compare?: { from: string; to: string }; route?: EdgeRoute
}

/** SVG path through ELK's routed points with rounded corners. */
function roundedPath(points: Point[], radius = 8): string {
  if (points.length < 2) return ''
  let d = `M ${points[0].x} ${points[0].y}`
  for (let i = 1; i < points.length - 1; i++) {
    const p0 = points[i - 1], p1 = points[i], p2 = points[i + 1]
    const r = Math.min(radius, Math.hypot(p1.x - p0.x, p1.y - p0.y) / 2, Math.hypot(p2.x - p1.x, p2.y - p1.y) / 2)
    const inX = p1.x - Math.sign(p1.x - p0.x) * r, inY = p1.y - Math.sign(p1.y - p0.y) * r
    const outX = p1.x + Math.sign(p2.x - p1.x) * r, outY = p1.y + Math.sign(p2.y - p1.y) * r
    d += ` L ${inX} ${inY} Q ${p1.x} ${p1.y} ${outX} ${outY}`
  }
  const last = points[points.length - 1]
  d += ` L ${last.x} ${last.y}`
  return d
}

/** An edge drawn along ELK's route, with the label where ELK reserved room for it. */
export function StatusEdge(props: EdgeProps) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style } = props
  const data = (props.data ?? {}) as StatusEdgeData
  const comparing = !!data.compare
  const status = data.status ?? 'unchanged'
  const showLabel = !!data.labelText && (!comparing || status !== 'unchanged')

  let path: string, labelX: number, labelY: number
  if (data.route && data.route.points.length >= 2) {
    path = roundedPath(data.route.points)
    const l = data.route.label
    if (l) { labelX = l.x + l.width / 2; labelY = l.y + l.height / 2 }
    else { const mid = data.route.points[Math.floor(data.route.points.length / 2)]; labelX = mid.x; labelY = mid.y }
  } else {
    ;[path, labelX, labelY] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 8 })
  }

  const tip = comparing
    ? status === 'unchanged'
      ? `${data.sourceName} → ${data.targetName} (${data.kind}) unchanged`
      : status === 'added'
        ? `added in ${data.compare!.to}: ${data.sourceName} → ${data.targetName} (${data.kind}${data.label ? `, ${data.label}` : ''})`
        : `removed since ${data.compare!.from}: ${data.sourceName} → ${data.targetName} (${data.kind}${data.label ? `, ${data.label}` : ''})`
    : `${data.sourceName} → ${data.targetName}: ${data.kind}${data.label ? ` · ${data.label}` : ''}`

  return (
    <g className={`status-edge status-${status}${comparing ? ' comparing' : ''}`}>
      <title>{tip}</title>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style} />
      <path d={path} fill="none" stroke="transparent" strokeWidth={14} />
      {showLabel && (
        <EdgeLabelRenderer>
          <div className={`edge-label edge-label-${status}`} style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }} title={tip}>
            {data.labelText}
          </div>
        </EdgeLabelRenderer>
      )}
    </g>
  )
}

export const edgeTypes = { status: StatusEdge }
