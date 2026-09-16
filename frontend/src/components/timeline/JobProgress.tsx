import { useAppStore } from '../../store/useAppStore'

export function JobProgress() {
  const job = useAppStore((s) => s.job)
  if (!job || job.status === 'done' || job.status === 'failed') return null
  const pct = Math.round((job.progress ?? 0) * 100)
  return (
    <div className={`job-progress status-${job.status}`}>
      <div className="job-bar"><div className="job-fill" style={{ width: `${pct}%` }} /></div>
      <div className="job-text">
        <span className="job-step">{job.step}</span>
        <span className="job-detail">{job.error ?? job.detail ?? ''}</span>
        <span className="job-pct">{pct}%</span>
      </div>
    </div>
  )
}
