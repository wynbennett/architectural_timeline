import type { ComponentProps } from 'react'
import ReactMarkdown from 'react-markdown'
import { useAppStore } from '../../store/useAppStore'

const CITE_RE = /^([\w@./+-]+\.[\w]+):(\d+)(?:-(\d+))?$/

/** Inline code that is `path:start-end`, or a bare path present in the tag's inventory,
 *  becomes a button that opens the code pane. */
function Code({ children, className, ...rest }: ComponentProps<'code'>) {
  const openPath = useAppStore((s) => s.openPath)
  const files = useAppStore((s) => s.files)
  const text = String(children ?? '').trim()
  if (!className) {
    const m = CITE_RE.exec(text)
    if (m) {
      const start = Number(m[2])
      const end = m[3] ? Number(m[3]) : start
      return <button className="cite" onClick={() => openPath(m[1], start, end)} title="open in code pane">{text}</button>
    }
    const bare = text.replace(/^\.?\//, '').replace(/\/$/, '')
    if (bare.includes('/') || bare.includes('.')) {
      const hit = files.find((f) => f.path === bare)
      if (hit) return <button className="cite" onClick={() => openPath(hit.path)} title="open in code pane">{text}</button>
    }
  }
  return <code className={className} {...rest}>{children}</code>
}

export function Markdown({ children }: { children: string }) {
  return <ReactMarkdown components={{ code: Code }}>{children}</ReactMarkdown>
}
