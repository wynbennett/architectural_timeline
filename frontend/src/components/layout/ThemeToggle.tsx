import { useAppStore } from '../../store/useAppStore'

export function ThemeToggle() {
  const { theme, setTheme } = useAppStore()
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button className="btn tiny theme-toggle" onClick={() => setTheme(next)} title={`switch to ${next} mode`} aria-label={`switch to ${next} mode`}>
      {theme === 'dark' ? '☀ light' : '☾ dark'}
    </button>
  )
}
