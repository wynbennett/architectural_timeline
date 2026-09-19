import { useEffect, useRef } from 'react'
import Editor, { type OnMount } from '@monaco-editor/react'
import type { editor as MonacoEditor } from 'monaco-editor'
import { useAppStore } from '../../store/useAppStore'

export const MONACO_LANG: Record<string, string> = {
  python: 'python', typescript: 'typescript', javascript: 'javascript', go: 'go', rust: 'rust', java: 'java',
  kotlin: 'kotlin', ruby: 'ruby', php: 'php', csharp: 'csharp', cpp: 'cpp', c: 'c', swift: 'swift', scala: 'scala',
  shell: 'shell', sql: 'sql', html: 'html', css: 'css', scss: 'scss', less: 'less', json: 'json', yaml: 'yaml',
  toml: 'ini', markdown: 'markdown', xml: 'xml', protobuf: 'protobuf', graphql: 'graphql', hcl: 'hcl', vue: 'html',
  svelte: 'html', dockerfile: 'dockerfile', elixir: 'elixir', erlang: 'plaintext', haskell: 'plaintext', lua: 'lua',
  r: 'r', dart: 'dart', makefile: 'plaintext', plaintext: 'plaintext',
}

interface Props {
  path: string
  content: string
  language: string | null
  range?: { startLine: number; endLine: number } | null
  hover?: { startLine: number; endLine: number } | null
}

export function CodeViewer({ path, content, language, range, hover }: Props) {
  const theme = useAppStore((s) => s.theme)
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null)
  const monacoRef = useRef<Parameters<OnMount>[1] | null>(null)
  const decosRef = useRef<MonacoEditor.IEditorDecorationsCollection | null>(null)
  const hoverRef = useRef<MonacoEditor.IEditorDecorationsCollection | null>(null)

  const applyRange = () => {
    const ed = editorRef.current
    const monaco = monacoRef.current
    if (!ed || !monaco) return
    if (!decosRef.current) decosRef.current = ed.createDecorationsCollection([])
    if (range) {
      decosRef.current.set([{ range: new monaco.Range(range.startLine, 1, range.endLine, 1), options: { isWholeLine: true, className: 'snippet-line', linesDecorationsClassName: 'snippet-gutter' } }])
      ed.revealLinesInCenter(range.startLine, range.endLine, 0)
    } else {
      decosRef.current.clear()
    }
  }

  const onMount: OnMount = (ed, monaco) => {
    editorRef.current = ed
    monacoRef.current = monaco
    applyRange()
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(applyRange, [path, content, range?.startLine, range?.endLine])

  useEffect(() => {
    const ed = editorRef.current
    const monaco = monacoRef.current
    if (!ed || !monaco) return
    if (!hoverRef.current) hoverRef.current = ed.createDecorationsCollection([])
    if (hover) hoverRef.current.set([{ range: new monaco.Range(hover.startLine, 1, hover.endLine, 1), options: { isWholeLine: true, className: 'snippet-line-hover' } }])
    else hoverRef.current.clear()
  }, [hover, path])

  return (
    <Editor
      path={path}
      value={content}
      language={MONACO_LANG[language ?? ''] ?? 'plaintext'}
      theme={theme === 'dark' ? 'vs-dark' : 'vs'}
      onMount={onMount}
      loading={<div className="pane-empty">loading editor…</div>}
      options={{ readOnly: true, domReadOnly: true, minimap: { enabled: true }, fontSize: 12.5, lineNumbers: 'on', scrollBeyondLastLine: false, wordWrap: 'off', renderLineHighlight: 'none', glyphMargin: false, folding: true, automaticLayout: true }}
    />
  )
}
