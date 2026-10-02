import { localSessionToken, resetLocalSessionToken } from './localSession.ts'

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

/**
 * Only the local browser boundary answers 403, before the request reaches any
 * handler, so a 403 is retried once with a freshly issued capability: the
 * server hands out a new one each time it restarts.
 */
async function postWithLocalToken(path: string, payload: unknown, signal?: AbortSignal): Promise<Response> {
  const send = async () => fetch(path, {
    method: 'POST',
    headers: { ...JSON_HEADERS, 'X-AIA-Local-Token': await localSessionToken() },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    signal,
  })
  const response = await send()
  if (response.status !== 403) return response
  resetLocalSessionToken()
  return send()
}

export async function apiPost<T>(path: string, payload?: unknown, signal?: AbortSignal): Promise<T> {
  return parseJson<T>(await postWithLocalToken(path, payload, signal))
}

/**
 * Like apiPost, but never throws on a non-2xx response -- it returns the
 * parsed body regardless of status. Some endpoints (e.g. /api/hook/verify)
 * return structured failure detail (reason/next_step) with no `error` key
 * on 4xx/5xx, which parseJson's throw-on-!ok path would otherwise discard.
 */
export async function apiPostTolerant<T>(path: string, payload?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await postWithLocalToken(path, payload, signal)
  return (await response.json().catch(() => ({}))) as T
}
