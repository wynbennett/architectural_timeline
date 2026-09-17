import { useEffect } from 'react'
import { Group, Panel, Separator } from 'react-resizable-panels'
import { useAppStore } from '../../store/useAppStore'
import { DiagramPane } from '../diagram/DiagramPane'
import { CodePane } from '../code/CodePane'
import { ChatPane } from '../chat/ChatPane'
import { TimeSlider } from '../timeline/TimeSlider'
import { JobProgress } from '../timeline/JobProgress'
import { CompareBanner } from '../timeline/CompareBanner'
import { ThemeToggle } from './ThemeToggle'

export function AppShell() {
  const { health, repos, repo, selectRepo, error, toast, dismissToast, job, compareMode, toggleCompareMode, graph, goToIntro } = useAppStore()

  useEffect(() => { if (toast) { const t = window.setTimeout(dismissToast, 4000); return () => window.clearTimeout(t) } }, [toast, dismissToast])

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand brand-link" onClick={goToIntro} title="back to the repository list">‹ ArchTimeline</button>
        <div className="repo-controls">
          {repos.length > 0 && (
            <select value={repo?.id ?? ''} onChange={(e) => e.target.value && selectRepo(Number(e.target.value))}>
              <option value="" disabled>select a repo</option>
              {repos.map((r) => <option key={r.id} value={r.id}>{r.owner}/{r.name} ({r.generated_count}/{r.tag_count})</option>)}
            </select>
          )}
          {health?.demo_mode && <span className="demo-chip" title="Loading new repositories and generating tags is disabled on this public demo">demo mode</span>}
        </div>
        <button className={`btn tiny${compareMode ? ' active' : ''}`} disabled={!graph} onClick={toggleCompareMode} title="Compare the current tag with an earlier one">
          {compareMode ? 'exit compare' : 'compare'}
        </button>
        <ThemeToggle />
        <div className="topbar-right muted" title={health ? `credentials: ${health.auth}` : undefined}>
          {health ? `${health.model} · ${health.db} · ` : 'connecting…'}
          {health && <span className={health.auth === 'none' ? 'error-text' : undefined}>{health.auth === 'none' ? 'no credentials' : health.auth.split(' (')[0]}</span>}
        </div>
      </header>
      <div className="timeline-bar">
        <TimeSlider />
        {job && (job.status === 'queued' || job.status === 'running') && <JobProgress />}
        <CompareBanner />
      </div>
      {error && <div className="banner error">{error}<button className="btn tiny" onClick={() => useAppStore.setState({ error: null })}>dismiss</button></div>}
      {toast && <div className="banner toast">{toast}</div>}
      <main className="workspace">
        <Group orientation="vertical">
          <Panel defaultSize={68} minSize={30}>
            <Group orientation="horizontal">
              <Panel defaultSize={55} minSize={25}><DiagramPane /></Panel>
              <Separator className="sep sep-v" />
              <Panel defaultSize={45} minSize={20}><CodePane /></Panel>
            </Group>
          </Panel>
          <Separator className="sep sep-h" />
          <Panel defaultSize={32} minSize={15}><ChatPane /></Panel>
        </Group>
      </main>
    </div>
  )
}
