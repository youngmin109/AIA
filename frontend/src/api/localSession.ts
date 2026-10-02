let pending: Promise<string> | null = null
/** Ephemeral local capability, memory-only. Not an account or login token. */
export function localSessionToken(): Promise<string> {
  if (!pending) pending = fetch('/api/local-session', { cache: 'no-store' }).then(async response => {
    if (!response.ok) throw new Error('로컬 보호 연결을 확인할 수 없습니다. 앱을 새로 열어주세요.')
    const body = await response.json()
    if (typeof body.token !== 'string') throw new Error('로컬 연결 정보가 올바르지 않습니다.')
    return body.token
  }).catch(error => { pending = null; throw error })
  return pending
}
/** Forget the cached capability; the local server issues a new one each time it starts. */
export function resetLocalSessionToken(): void {
  pending = null
}
