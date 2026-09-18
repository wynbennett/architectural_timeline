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
  const { health, repos, repo, selectRepo, error, toast, dismissToast, job, goToIntro, refreshRepo, refreshing } = useAppStore()

  useEffect(() => { if (toast) { const t = window.setTimeout(dismissToast, 4000); return () => window.clearTimeout(t) } }, [toast, dismissToast])

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand brand-link" onClick={goToIntro} title="back to the repository list">‹ <span className="brand-name">Ziggi</span></button>
        <div className="repo-controls">
          {repos.length > 0 && (
            <select value={repo?.id ?? ''} onChange={(e) => e.target.value && selectRepo(Number(e.target.value))}>
              <option value="" disabled>select a repo</option>
              {repos.map((r) => <option key={r.id} value={r.id}>{r.owner}/{r.name} ({r.generated_count}/{r.tag_count})</option>)}
            </select>
          )}
          {repo && (
            <button
              className="btn tiny"
              disabled={refreshing || !health?.generation_enabled || !!health?.demo_mode || (job !== null && (job.status === 'queued' || job.status === 'running'))}
              onClick={() => refreshRepo()}
              title={health?.demo_mode ? 'Demo mode: pulling and generating is disabled' : !health?.generation_enabled ? 'Generation is disabled on this deployment' : 'Fetch the latest tags from GitHub and generate any newest ones that are missing'}
            >
              {refreshing ? '↻ pulling…' : '↻ pull latest'}
            </button>
          )}
          {health?.demo_mode && <span className="demo-chip" title="Loading new repositories and generating tags is disabled on this public demo">demo mode</span>}
        </div>
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
        <Group orientation="horizontal">
          <Panel defaultSize="58%" minSize="30%"><DiagramPane /></Panel>
          <Separator className="sep sep-v" />
          <Panel defaultSize="42%" minSize="22%">
            <Group orientation="vertical">
              <Panel defaultSize="62%" minSize="25%"><CodePane /></Panel>
              <Separator className="sep sep-h" />
              <Panel defaultSize="38%" minSize="15%"><ChatPane /></Panel>
            </Group>
          </Panel>
        </Group>
      </main>
    </div>
  )
}
