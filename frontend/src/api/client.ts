const JSON_HEADERS = { 'Content-Type': 'application/json' }

async function parseJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    const message = typeof body?.error === 'string' ? body.error : `요청 실패 (${response.status})`
    throw new Error(message)
  }
  return body as T
}

export function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return fetch(path, { signal }).then((response) => parseJson<T>(response))
}

export function apiPost<T>(path: string, payload?: unknown, signal?: AbortSignal): Promise<T> {
  return fetch(path, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: payload === undefined ? undefined : JSON.stringify(payload),
    signal,
  }).then((response) => parseJson<T>(response))
}
