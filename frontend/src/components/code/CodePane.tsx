import { useEffect, useMemo, useState } from 'react'
import { api } from '../../api/client'
import { useAppStore } from '../../store/useAppStore'
import { tier3Key, type FileContent } from '../../types/graph'
import { FileTree } from './FileTree'
import { CodeViewer } from './CodeViewer'

function underPaths(all: string[], prefixes: string[]): string[] {
  const norm = prefixes.map((p) => p.replace(/^\/+|\/+$/g, '')).filter(Boolean)
  return all.filter((f) => norm.some((p) => f === p || f.startsWith(p + '/')))
}

export function CodePane() {
  const { repo, currentTag, graph, files, tier, systemId, moduleId, selectedNodeId, openFile, hoverRange, showAllFiles, toggleAllFiles, openPath } = useAppStore()
  const [content, setContent] = useState<FileContent | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const allPaths = useMemo(() => files.map((f) => f.path), [files])

  const { scopePaths, scopeLabel } = useMemo(() => {
    if (!graph) return { scopePaths: allPaths, scopeLabel: 'all files' }
    if (tier === 1) {
      const sys = selectedNodeId ? graph.tier1.nodes.find((n) => n.id === selectedNodeId) : undefined
      return sys ? { scopePaths: underPaths(allPaths, sys.paths), scopeLabel: sys.name } : { scopePaths: allPaths, scopeLabel: 'all files' }
    }
    if (tier === 2 && systemId) {
      const sys = graph.tier1.nodes.find((n) => n.id === systemId)
      return { scopePaths: underPaths(allPaths, sys?.paths ?? []), scopeLabel: sys?.name ?? systemId }
    }
    if (tier === 3 && systemId && moduleId) {
      const mod = graph.tier2[systemId]?.nodes.find((n) => n.id === moduleId)
      const snippetFiles = graph.tier3[tier3Key(systemId, moduleId)]?.nodes.map((n) => n.file_path) ?? []
      const paths = new Set([...underPaths(allPaths, mod?.paths ?? []), ...snippetFiles])
      return { scopePaths: [...paths], scopeLabel: mod?.name ?? moduleId }
    }
    return { scopePaths: allPaths, scopeLabel: 'all files' }
  }, [graph, tier, systemId, moduleId, selectedNodeId, allPaths])

  const treePaths = showAllFiles ? allPaths : scopePaths

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
        <span className="mono path-label" title={openFile?.path}>{openFile?.path ?? 'no file selected'}</span>
        {currentTag && <span className="tag-chip">@ {currentTag}</span>}
        {range && <span className="muted mono">L{range.startLine}-{range.endLine}</span>}
      </div>
      <div className="code-body">
        <div className="code-sidebar">
          <div className="code-sidebar-head">
            <span className="muted">{showAllFiles ? 'all files' : scopeLabel} · {treePaths.length}</span>
            {scopePaths.length !== allPaths.length && (
              <button className="btn tiny" onClick={toggleAllFiles}>{showAllFiles ? 'scope' : 'all'}</button>
            )}
          </div>
          {treePaths.length ? <FileTree paths={treePaths} selected={openFile?.path ?? null} onOpen={(p) => openPath(p)} /> : <div className="pane-empty small">no files</div>}
        </div>
        <div className="code-editor">
          {!openFile ? (
            <div className="pane-empty">Click a snippet or a file to view code.</div>
          ) : loadError ? (
            <div className="pane-empty error-text">{loadError}</div>
          ) : content ? (
            <CodeViewer path={content.path} content={content.content} language={content.language} range={range} hover={hover} />
          ) : (
            <div className="pane-empty">loading…</div>
          )}
        </div>
      </div>
    </div>
  )
}
