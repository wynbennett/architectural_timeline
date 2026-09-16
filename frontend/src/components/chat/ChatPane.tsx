import { useEffect, useRef, useState, type ComponentProps } from 'react'
import ReactMarkdown from 'react-markdown'
import { useAppStore } from '../../store/useAppStore'

const CITE_RE = /^([\w@./+-]+\.[\w]+):(\d+)(?:-(\d+))?$/

function Code({ children, className, ...rest }: ComponentProps<'code'>) {
  const openPath = useAppStore((s) => s.openPath)
  const text = String(children ?? '')
  const m = !className && CITE_RE.exec(text.trim())
  if (m) {
    const start = Number(m[2])
    const end = m[3] ? Number(m[3]) : start
    return <button className="cite" onClick={() => openPath(m[1], start, end)} title="open in code pane">{text}</button>
  }
  return <code className={className} {...rest}>{children}</code>
}

export function ChatPane() {
  const { chat, chatBusy, sendChat, clearChat, currentTag, graph, tier, systemId, moduleId, openFile, chatDraft, setChatDraft, compareMode, compareTag } = useAppStore()
  const [draft, setDraft] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }) }, [chat])
  useEffect(() => {
    if (chatDraft) { setDraft(chatDraft); setChatDraft(null); inputRef.current?.focus() }
  }, [chatDraft, setChatDraft])

  const crumbs = ['System', systemId, moduleId].filter(Boolean).join(' › ')
  const submit = () => { const t = draft.trim(); if (!t || chatBusy || !graph) return; setDraft(''); void sendChat(t) }

  return (
    <div className="pane chat-pane">
      <div className="pane-header">
        <span>Chat</span>
        {currentTag && <span className="muted">context: {currentTag}{compareMode && compareTag ? ` (vs ${compareTag})` : ''} · tier {tier} · {crumbs}{openFile ? ` · ${openFile.path}` : ''}</span>}
        {chat.length > 0 && <button className="btn tiny" onClick={clearChat}>clear</button>}
      </div>
      <div className="chat-list" ref={listRef}>
        {chat.length === 0 && <div className="pane-empty small">Ask about the architecture at this tag. Cited files open in the code pane.</div>}
        {chat.map((m, i) => (
          <div key={i} className={`msg msg-${m.role}`}>
            {m.activity && m.activity.length > 0 && <div className="msg-activity">{m.activity.map((a, j) => <span key={j} className="mono">{a}</span>)}</div>}
            {m.role === 'assistant' ? <ReactMarkdown components={{ code: Code }}>{m.content || (m.streaming ? '…' : '')}</ReactMarkdown> : <p>{m.content}</p>}
          </div>
        ))}
      </div>
      <div className="chat-input">
        <textarea
          ref={inputRef}
          value={draft}
          placeholder={graph ? 'Ask about the architecture…' : 'Generate or select a tag with a graph first'}
          disabled={!graph || chatBusy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() } }}
          rows={2}
        />
        <button className="btn primary" disabled={!graph || chatBusy || !draft.trim()} onClick={submit}>{chatBusy ? '…' : 'Send'}</button>
      </div>
    </div>
  )
}
