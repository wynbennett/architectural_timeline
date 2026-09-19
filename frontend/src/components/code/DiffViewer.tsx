import { useEffect, useRef } from 'react'
import { DiffEditor, type DiffOnMount } from '@monaco-editor/react'
import type { editor as MonacoEditor } from 'monaco-editor'
import { useAppStore } from '../../store/useAppStore'
import { MONACO_LANG } from './CodeViewer'

interface Props {
  path: string
  original: string   // content at the compare (older) tag; empty when the file did not exist
  modified: string   // content at the current tag; empty when the file was removed
  language: string | null
  sideBySide: boolean
  range?: { startLine: number; endLine: number } | null
}

/** Compare mode: the open file at the older tag versus the current tag, Monaco diff style. */
export function DiffViewer({ path, original, modified, language, sideBySide, range }: Props) {
  const theme = useAppStore((s) => s.theme)
  const editorRef = useRef<MonacoEditor.IStandaloneDiffEditor | null>(null)
  const monacoRef = useRef<Parameters<DiffOnMount>[1] | null>(null)
  const decosRef = useRef<MonacoEditor.IEditorDecorationsCollection | null>(null)

  const applyRange = () => {
    const ed = editorRef.current?.getModifiedEditor()
    const monaco = monacoRef.current
    if (!ed || !monaco) return
    if (!decosRef.current) decosRef.current = ed.createDecorationsCollection([])
    if (range) {
      decosRef.current.set([{ range: new monaco.Range(range.startLine, 1, range.endLine, 1), options: { isWholeLine: true, linesDecorationsClassName: 'snippet-gutter' } }])
      ed.revealLinesInCenter(range.startLine, range.endLine, 0)
    } else {
      decosRef.current.clear()
    }
  }
  const onMount: DiffOnMount = (ed, monaco) => { editorRef.current = ed; monacoRef.current = monaco; applyRange() }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(applyRange, [path, range?.startLine, range?.endLine])

  return (
    <DiffEditor
      originalModelPath={`compare://${path}`}
      modifiedModelPath={`current://${path}`}
      original={original}
      modified={modified}
      language={MONACO_LANG[language ?? ''] ?? 'plaintext'}
      theme={theme === 'dark' ? 'vs-dark' : 'vs'}
      onMount={onMount}
      loading={<div className="pane-empty">loading diff…</div>}
      options={{
        readOnly: true, originalEditable: false, renderSideBySide: sideBySide, renderSideBySideInlineBreakpoint: 0, renderIndicators: true, renderOverviewRuler: true,
        minimap: { enabled: false }, fontSize: 12.5, scrollBeyondLastLine: false, automaticLayout: true, diffWordWrap: 'off',
        ignoreTrimWhitespace: false, glyphMargin: false, folding: false, hideUnchangedRegions: { enabled: true, contextLineCount: 3, minimumLineCount: 4 },
      }}
    />
  )
}
