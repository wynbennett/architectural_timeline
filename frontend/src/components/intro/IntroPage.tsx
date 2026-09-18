import { useState } from 'react'
import { repoPath, useAppStore } from '../../store/useAppStore'
import { ThemeToggle } from '../layout/ThemeToggle'

export function IntroPage() {
  const { health, repos, selectRepo, loadRepo, openApp, error } = useAppStore()
  const [url, setUrl] = useState('')
  const demo = !!health?.demo_mode
  const canLoad = !!health?.generation_enabled && !demo
  const loadTitle = demo ? 'Demo mode: loading new repositories is disabled' : !health?.generation_enabled ? 'Generation is disabled on this deployment' : undefined

  return (
    <div className="intro">
      <div className="intro-top"><ThemeToggle /></div>
      <header className="intro-hero">
        <div className="intro-kicker">architectural timeline</div>
        <h1 className="intro-title">Ziggi</h1>
        <p className="intro-lede">
          Turn a Git repository into a navigable architecture map. For each release tag, Claude reads the code and
          builds three levels of detail: the systems and how they talk to each other, the modules inside each system,
          and the code that matters in each module. Then leap between tags to see how it all changed.
        </p>
        <div className="feature-grid">
          <div className="feature"><span className="feature-icon">◫</span><strong>Graphical map</strong><p>Systems, modules, and code snippets drawn as an interactive diagram. Click a node to drill in, hover a line to see how things connect.</p></div>
          <div className="feature"><span className="feature-icon">⧗</span><strong>Time machine</strong><p>Slide between tags to watch the architecture evolve; compare any two to see what was added, removed, or rewired.</p></div>
          <div className="feature"><span className="feature-icon">✎</span><strong>Written overview</strong><p>A per-tag walkthrough: what it is, the components, how a request flows, and where to start reading.</p></div>
          <div className="feature"><span className="feature-icon">❯</span><strong>Grounded chat</strong><p>Ask about the system at any tag. Answers cite real files that open right in the code pane.</p></div>
        </div>
        <p className="intro-footnote">Named for Ziggy, the hybrid computer that steered every leap in <em>Quantum Leap</em>.</p>
      </header>

      <section className="intro-repos">
        <h2>Pick a repository</h2>
        {repos.length === 0 && <p className="muted">{health ? 'Nothing generated yet.' : 'Connecting…'}</p>}
        <div className="repo-grid">
          {repos.map((r) => (
            <a
              key={r.id}
              className={`repo-card${r.generated_count === 0 ? ' disabled' : ''}`}
              href={repoPath(r.owner, r.name)}
              onClick={(e) => { e.preventDefault(); if (r.generated_count === 0) return; void selectRepo(r.id); openApp() }}
              aria-disabled={r.generated_count === 0}
              title={r.generated_count === 0 ? 'no generated tags yet' : `open ${r.owner}/${r.name}`}
            >
              <span className="repo-card-name">{r.owner}/<strong>{r.name}</strong></span>
              <span className="repo-card-meta">{r.generated_count} of {r.tag_count} tags generated</span>
            </a>
          ))}
        </div>
      </section>

      <section className="intro-load">
        <h2>Or load a new one</h2>
        <form className="repo-form" onSubmit={(e) => { e.preventDefault(); if (canLoad && url.trim()) { void loadRepo(url.trim()); openApp() } }} title={loadTitle}>
          <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/owner/repo" disabled={!canLoad} title={loadTitle} />
          <button className="btn primary" type="submit" disabled={!canLoad || !url.trim()} title={loadTitle}>Load</button>
        </form>
        {demo && <p className="hint">This is a public demo, so loading new repositories and generating new tags is turned off. Browsing, chat, overviews, and comparisons all work.</p>}
        {!demo && health?.generation_enabled && <p className="hint">Clones the repo and generates the newest three tags with {health.model}. Takes a few minutes per tag.</p>}
        {error && <p className="error-text">{error}</p>}
      </section>
    </div>
  )
}
