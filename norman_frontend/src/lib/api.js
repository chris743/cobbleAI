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

/**
 * Stream a POST request as SSE. Calls onEvent for each parsed event.
 * Returns when the stream closes.
 */
export async function apiPostStream(url, body, onEvent) {
  const headers = await authHeaders()
  const res = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  })

  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.error || `${res.status} ${res.statusText}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() // keep incomplete line in buffer

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6))
          onEvent(event)
        } catch (e) {
          // skip malformed events
        }
      }
    }
  }
}
