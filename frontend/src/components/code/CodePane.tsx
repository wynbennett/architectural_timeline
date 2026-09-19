import { useEffect, useMemo, useState } from 'react'
import { Group, Panel, Separator } from 'react-resizable-panels'
import { api } from '../../api/client'
import { useAppStore } from '../../store/useAppStore'
import { tier3Key, type FileContent } from '../../types/graph'
import { FileTree, type PathStatus } from './FileTree'
import { CodeViewer } from './CodeViewer'
import { DiffViewer } from './DiffViewer'

function underPaths(all: string[], prefixes: string[]): string[] {
  const norm = prefixes.map((p) => p.replace(/^\/+|\/+$/g, '')).filter(Boolean)
  return all.filter((f) => norm.some((p) => f === p || f.startsWith(p + '/')))
}

export function CodePane() {
  const { repo, currentTag, graph, files, tier, systemId, moduleId, selectedNodeId, openFile, hoverRange, showAllFiles, toggleAllFiles, openPath, compareMode, compareTag, compare } = useAppStore()
  const [content, setContent] = useState<FileContent | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [showFiles, setShowFiles] = useState<boolean>(() => { try { return localStorage.getItem('showFiles') !== '0' } catch { return true } })
  // compare mode: the same file at the older tag, keyed by path so a slow fetch never pairs
  // with the wrong file ('' = the file did not exist at the older tag)
  const [old, setOld] = useState<{ path: string; tag: string; content: string } | null>(null)
  const [showDiff, setShowDiff] = useState(true)
  const [sideBySide, setSideBySide] = useState(false)
  const oldContent = old && openFile && old.path === openFile.path && old.tag === compareTag ? old.content : null
  const diffActive = compareMode && !!compareTag && !!compare && !!openFile && showDiff
  const toggleFiles = () => setShowFiles((v) => { try { localStorage.setItem('showFiles', v ? '0' : '1') } catch { /* ignore */ } return !v })

  const allPaths = useMemo(() => files.map((f) => f.path), [files])

  const { scopePaths, scopeLabel, scopePathsPrefixes } = useMemo(() => {
    if (!graph) return { scopePaths: allPaths, scopeLabel: 'all files', scopePathsPrefixes: [] as string[] }
    if (tier === 1) {
      const sys = selectedNodeId ? graph.tier1.nodes.find((n) => n.id === selectedNodeId) : undefined
      return sys ? { scopePaths: underPaths(allPaths, sys.paths), scopeLabel: sys.name, scopePathsPrefixes: sys.paths } : { scopePaths: allPaths, scopeLabel: 'all files', scopePathsPrefixes: [] as string[] }
    }
    if (tier === 2 && systemId) {
      const sys = graph.tier1.nodes.find((n) => n.id === systemId)
      return { scopePaths: underPaths(allPaths, sys?.paths ?? []), scopeLabel: sys?.name ?? systemId, scopePathsPrefixes: sys?.paths ?? [] }
    }
    if (tier === 3 && systemId && moduleId) {
      const mod = graph.tier2[systemId]?.nodes.find((n) => n.id === moduleId)
      const snippetFiles = graph.tier3[tier3Key(systemId, moduleId)]?.nodes.map((n) => n.file_path) ?? []
      const paths = new Set([...underPaths(allPaths, mod?.paths ?? []), ...snippetFiles])
      return { scopePaths: [...paths], scopeLabel: mod?.name ?? moduleId, scopePathsPrefixes: mod?.paths ?? [] }
    }
    return { scopePaths: allPaths, scopeLabel: 'all files', scopePathsPrefixes: [] as string[] }
  }, [graph, tier, systemId, moduleId, selectedNodeId, allPaths])

  // compare mode: per-file change status for the tree, plus an optional "changed only" filter
  const [changedOnly, setChangedOnly] = useState(false)
  const pathStatus = useMemo<PathStatus>(() => {
    if (!compareMode || !compare) return {}
    const st: PathStatus = {}
    compare.files.added.forEach((p) => { st[p] = 'added' })
    compare.files.modified.forEach((p) => { st[p] = 'modified' })
    compare.files.removed.forEach((p) => { st[p] = 'removed' })
    return st
  }, [compareMode, compare])
  const removedInScope = useMemo(() => (compareMode && compare ? compare.files.removed : []), [compareMode, compare])
  const basePaths = showAllFiles ? allPaths : scopePaths
  const treePaths = useMemo(() => {
    const withRemoved = compareMode && compare ? [...basePaths, ...removedInScope.filter((p) => showAllFiles || scopePaths.includes(p) || underScope(p))] : basePaths
    return changedOnly && compareMode ? withRemoved.filter((p) => pathStatus[p]) : withRemoved
    function underScope(p: string) { return scopeLabel === 'all files' ? true : underPaths([p], scopePathsPrefixes).length > 0 }
  }, [basePaths, compareMode, compare, removedInScope, showAllFiles, scopePaths, changedOnly, pathStatus, scopeLabel, scopePathsPrefixes])
  const changedCount = treePaths.filter((p) => pathStatus[p]).length

  useEffect(() => {
    if (!repo || !compareTag || !openFile || !compareMode) { setOld(null); return }
    const path = openFile.path, tag = compareTag
    let cancelled = false
    api.getFile(repo.id, tag, path)
      .then((c) => { if (!cancelled) setOld({ path, tag, content: c.content }) })
      .catch(() => { if (!cancelled) setOld({ path, tag, content: '' }) })  // 404: the file did not exist at the older tag
    return () => { cancelled = true }
  }, [repo, compareTag, compareMode, openFile?.path]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!repo || !currentTag || !openFile) { setContent(null); return }
    let cancelled = false
    setLoadError(null)
    api.getFile(repo.id, currentTag, openFile.path)
      .then((c) => { if (!cancelled) setContent(c) })
      .catch((e: Error) => { if (!cancelled) { setContent(null); setLoadError(e.message) } })
    return () => { cancelled = true }
  }, [repo, currentTag, openFile?.path]) // eslint-disable-line react-hooks/exhaustive-deps

  const range = openFile?.startLine && openFile?.endLine ? { startLine: openFile.startLine, endLine: openFile.endLine } : null
  const hover = hoverRange && openFile && hoverRange.path === openFile.path ? { startLine: hoverRange.startLine, endLine: hoverRange.endLine } : null

  return (
    <div className="pane code-pane">
      <div className="pane-header">
        <button className="btn tiny files-toggle" onClick={toggleFiles} title={showFiles ? 'hide file browser' : 'show file browser'} aria-pressed={showFiles}>{showFiles ? '◧ files' : '▤ files'}</button>
        <span className="mono path-label" title={openFile?.path}>{openFile?.path ?? 'no file selected'}</span>
        {currentTag && <span className="tag-chip">@ {currentTag}</span>}
        {range && <span className="muted mono">L{range.startLine}-{range.endLine}</span>}
        {compareMode && compareTag && openFile && (
          <span className="diff-controls">
            <button className={`btn tiny${showDiff ? ' active' : ''}`} onClick={() => setShowDiff((v) => !v)} title={`show changes since ${compareTag}`}>diff vs {compareTag}</button>
            {showDiff && <button className="btn tiny" onClick={() => setSideBySide((v) => !v)} title="toggle inline / side-by-side">{sideBySide ? 'inline' : 'side by side'}</button>}
            {showDiff && oldContent !== null && content && oldContent === content.content && <span className="muted">unchanged</span>}
            {showDiff && oldContent === '' && <span className="diff-added">new in {currentTag}</span>}
          </span>
        )}
      </div>
      <div className="code-body">
        <Group orientation="horizontal">
          {showFiles && (
            <>
              <Panel defaultSize="34%" minSize="10%">
                <div className="code-sidebar">
                  <div className="code-sidebar-head">
                    <span className="muted">{showAllFiles ? 'all files' : scopeLabel} · {treePaths.length}{compareMode && compare ? ` · ${changedCount} changed` : ''}</span>
                    <span className="sidebar-actions">
                      {compareMode && compare && <button className={`btn tiny${changedOnly ? ' active' : ''}`} onClick={() => setChangedOnly((v) => !v)} title="show only files that changed since the compare tag">changed</button>}
                      {scopePaths.length !== allPaths.length && (
                        <button className="btn tiny" onClick={toggleAllFiles}>{showAllFiles ? 'scope' : 'all'}</button>
                      )}
                    </span>
                  </div>
                  {treePaths.length ? <FileTree paths={treePaths} selected={openFile?.path ?? null} onOpen={(p) => openPath(p)} status={pathStatus} /> : <div className="pane-empty small">{changedOnly ? 'nothing changed here' : 'no files'}</div>}
                </div>
              </Panel>
              <Separator className="sep sep-v" />
            </>
          )}
          <Panel minSize="5%">
            <div className="code-editor">
              {!openFile ? (
                <div className="pane-empty">Click a snippet or a file to view code.</div>
              ) : loadError ? (
                <div className="pane-empty error-text">{loadError}</div>
              ) : content && diffActive && oldContent === null ? (
                <div className="pane-empty">loading {compareTag} version…</div>
              ) : content && diffActive && oldContent !== null && oldContent !== content.content ? (
                <DiffViewer key={`${compareTag}:${content.path}`} path={content.path} original={oldContent} modified={content.content} language={content.language} sideBySide={sideBySide} range={range} />
              ) : content ? (
                <CodeViewer path={content.path} content={content.content} language={content.language} range={range} hover={hover} />
              ) : (
                <div className="pane-empty">loading…</div>
              )}
            </div>
          </Panel>
        </Group>
      </div>
    </div>
  )
}
