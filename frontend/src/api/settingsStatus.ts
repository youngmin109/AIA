/** Connection traffic lights for the settings screen. Display only. */

export interface LightCheck { name: string; ok: boolean; detail?: string }
export interface LightInput {
  checks?: LightCheck[]
  hook_trust?: { status?: string }
  hook_activation?: { status?: string }
}
export type LightState = 'ok' | 'warn' | 'checking'
export interface Light { key: string; label: string; state: LightState; note: string }

export function connectionLights(preflight: LightInput | null | undefined): Light[] {
  if (!preflight) {
    return [
      { key: 'hook', label: 'Hook 연결', state: 'checking', note: '확인 중' },
      { key: 'trust', label: 'Codex 신뢰', state: 'checking', note: '확인 중' },
      { key: 'delivery', label: '실제 요청 전달', state: 'checking', note: '확인 중' },
    ]
  }
  const check = (name: string) => preflight.checks?.find(item => item.name === name)
  const hook = check('pretool_hook')
  const trust = check('codex_hook_trust')
  const delivery = check('hook_verification')
  const trustStatus = preflight.hook_trust?.status
  const activation = preflight.hook_activation?.status

  const hookLight: Light = !hook
    ? { key: 'hook', label: 'Hook 연결', state: 'checking', note: '확인 중' }
    : hook.ok
      ? { key: 'hook', label: 'Hook 연결', state: 'ok', note: '정상 · 실행 전 검사 켜짐' }
      : { key: 'hook', label: 'Hook 연결', state: 'warn', note: '설치 또는 갱신 필요' }

  const trusted = trust ? trust.ok : ['TRUSTED', 'MANAGED'].includes(trustStatus ?? '')
  const trustKnown = Boolean(trust) || Boolean(trustStatus && trustStatus !== 'UNKNOWN')
  const trustLight: Light = !trustKnown
    ? { key: 'trust', label: 'Codex 신뢰', state: hook?.ok === false ? 'warn' : 'checking', note: hook?.ok === false ? 'Hook 설치 뒤 확인' : '확인 중' }
    : trusted
      ? { key: 'trust', label: 'Codex 신뢰', state: 'ok', note: '정상 · Codex에서 신뢰됨' }
      : { key: 'trust', label: 'Codex 신뢰', state: 'warn', note: 'Codex /hooks에서 Trust 필요' }

  const delivered = delivery ? delivery.ok : activation === 'CURRENTLY_VERIFIED'
  const deliveryLight: Light = delivered
    ? { key: 'delivery', label: '실제 요청 전달', state: 'ok', note: '정상 · 전달 확인됨' }
    : activation === 'OBSERVED_IN_PAST'
      ? { key: 'delivery', label: '실제 요청 전달', state: 'warn', note: '예전에 확인됨 · 다시 확인 필요' }
      : { key: 'delivery', label: '실제 요청 전달', state: 'warn', note: '연결 검증 필요' }

  return [hookLight, trustLight, deliveryLight]
}
