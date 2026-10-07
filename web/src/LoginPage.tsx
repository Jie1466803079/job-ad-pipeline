import { useState } from 'react'
import { api, messageOf } from './api.ts'

export function LoginPage({ onLogin }: { onLogin: (username: string) => void }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string>()
  const [busy, setBusy] = useState(false)

  async function logIn() {
    setBusy(true)
    setError(undefined)
    try {
      const me = await api.login(username, password)
      onLogin(me.username)
    } catch (reason) {
      setError(messageOf(reason))
      setPassword('')
      setBusy(false)
    }
  }

  return (
    <main className="login">
      <h1>Job ad review</h1>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          void logIn()
        }}
      >
        <label>
          Username
          <input autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy}>
          Log in
        </button>
      </form>
    </main>
  )
}
