import { api, type Stats } from './api.ts'
import { statsLine } from './format.ts'

interface HeaderProps {
  username: string
  stats: Stats | undefined
  onLogout: () => void
}

export function Header({ username, stats, onLogout }: HeaderProps) {
  async function logOut() {
    await api.logout().catch(() => undefined)
    onLogout()
  }
  return (
    <header className="top">
      <a className="brand" href="#/queue/review">
        Job ads
      </a>
      <p className="stats">{stats ? statsLine(stats) : ''}</p>
      <span className="muted">{username}</span>
      <button type="button" className="link" onClick={() => void logOut()}>
        Log out
      </button>
    </header>
  )
}
