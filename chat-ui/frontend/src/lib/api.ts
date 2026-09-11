// Attaches the shared-secret token (embedded by backend.py's index() into a
// <meta name="api-token"> tag) to requests that hit gated backend routes.
// A no-op in the default loopback-bound deployment — the backend only
// enforces the token once BIND_HOST opts into exposing the app beyond
// loopback. See chat-ui/auth.py.
export function apiToken(): string {
  return document.querySelector('meta[name="api-token"]')?.getAttribute('content') ?? ''
}

export function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = apiToken()
  if (!token) return fetch(input, init)
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${token}`)
  return fetch(input, { ...init, headers })
}
