import { useEffect } from 'react'
import { AppShell } from './components/layout/AppShell'
import { IntroPage } from './components/intro/IntroPage'
import { useAppStore } from './store/useAppStore'

export default function App() {
  const { screen, init } = useAppStore()
  useEffect(() => { void init() }, [init])
  return screen === 'intro' ? <IntroPage /> : <AppShell />
}
