import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type EdgeProps } from '@xyflow/react'
import type { DiffStatus } from '../../types/graph'

export type StatusEdgeData = { kind: string; label: string; status?: DiffStatus; sourceName: string; targetName: string; compare?: { from: string; to: string } }

/** A smooth-step edge that carries a tooltip and, in compare mode, only labels what changed. */
export function StatusEdge(props: EdgeProps) {
  const { id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, markerEnd, style } = props
  const data = (props.data ?? {}) as StatusEdgeData
  const [path, labelX, labelY] = getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, borderRadius: 8 })
  const comparing = !!data.compare
  const status = data.status ?? 'unchanged'
  const showLabel = !comparing || status !== 'unchanged'
  const text = data.label || data.kind
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
      {/* wide invisible hit area so the tooltip is easy to reach */}
      <path d={path} fill="none" stroke="transparent" strokeWidth={14} />
      {showLabel && (
        <EdgeLabelRenderer>
          <div className={`edge-label edge-label-${status}`} style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }} title={tip}>
            {comparing && status !== 'unchanged' ? <span className="edge-status">{status === 'added' ? '+' : '−'}</span> : null}
            {text}
          </div>
        </EdgeLabelRenderer>
      )}
    </g>
  )
}

export const edgeTypes = { status: StatusEdge }
