import { useEffect, useState } from 'react'
import { api, setUnauthorizedHandler } from './api.ts'
import { DetailPage } from './DetailPage.tsx'
import { Header } from './Header.tsx'
import { LoginPage } from './LoginPage.tsx'
import { QueuePage } from './QueuePage.tsx'
import { parseRoute, routeHash, type Route } from './route.ts'
import { useLoader } from './useLoader.ts'

type Session = { state: 'checking' } | { state: 'out' } | { state: 'in'; username: string }

export function App() {
  const [session, setSession] = useState<Session>({ state: 'checking' })
  const route = useHashRoute()

  useEffect(() => {
    setUnauthorizedHandler(() => setSession({ state: 'out' }))
    api.me().then(
      (me) => setSession({ state: 'in', username: me.username }),
      () => setSession({ state: 'out' }),
    )
  }, [])

  if (session.state === 'checking') return <p className="page-message">Loading...</p>
  if (session.state === 'out') {
    return <LoginPage onLogin={(username) => setSession({ state: 'in', username })} />
  }
  return <ReviewApp username={session.username} route={route} onLogout={() => setSession({ state: 'out' })} />
}

function ReviewApp({ username, route, onLogout }: { username: string; route: Route; onLogout: () => void }) {
  const stats = useLoader(routeHash(route), api.stats)
  return (
    <>
      <Header username={username} stats={stats.data} onLogout={onLogout} />
      <main>
        {route.page === 'posting' ? (
          <DetailPage key={route.id} id={route.id} onChange={stats.reload} />
        ) : (
          <QueuePage tab={route.tab} counts={stats.data?.tabs} />
        )}
      </main>
    </>
  )
}

function useHashRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash))
  useEffect(() => {
    const update = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return route
}
