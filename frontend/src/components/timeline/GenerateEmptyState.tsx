import { useAppStore } from '../../store/useAppStore'
import { JobProgress } from './JobProgress'

export function GenerateEmptyState() {
  const { repo, currentTag, health, generateTag, job } = useAppStore()
  const tag = repo?.tags.find((t) => t.name === currentTag)
  if (!repo) {
    return <div className="pane-empty">Load a GitHub repository to begin.</div>
  }
  if (!tag) {
    return <div className="pane-empty">{repo.tags.length ? 'Pick a tag on the timeline.' : 'This repository has no tags yet.'}</div>
  }
  const inProgress = tag.status === 'queued' || tag.status === 'running' || (job && job.status !== 'done' && job.status !== 'failed' && !job.tag)
  return (
    <div className="pane-empty generate-empty">
      <h3>No graph for {tag.name} yet</h3>
      {inProgress ? (
        <JobProgress />
      ) : health?.generation_enabled ? (
        <>
          {tag.status === 'failed' && <p className="error-text">Last attempt failed: {tag.error}</p>}
          {health.auth === 'none' && <p className="error-text">No Anthropic credentials found. Run <code>ant auth login</code> or set ANTHROPIC_API_KEY, then restart the API.</p>}
          <button className="btn primary" onClick={() => generateTag(tag.name)}>Generate {tag.name}</button>
          <p className="hint">Runs the three-tier analysis with {health.model}. Takes a few minutes.</p>
        </>
      ) : (
        <p className="hint">Generation is disabled on this deployment. Run it locally and point the generator at this database.</p>
      )}
    </div>
  )
}
