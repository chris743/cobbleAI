/**
 * Auth-aware API client. Gets Clerk session token and attaches it to requests.
 */

let getTokenFn = null

export function setGetToken(fn) {
  getTokenFn = fn
}

async function authHeaders() {
  const token = getTokenFn ? await getTokenFn() : null
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  }
}

export async function apiGet(url) {
  const headers = await authHeaders()
  const res = await fetch(url, { headers })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export async function apiPost(url, body) {
  const headers = await authHeaders()
  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`)
  return data
}
