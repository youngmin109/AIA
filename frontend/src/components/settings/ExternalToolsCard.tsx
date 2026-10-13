import { useEffect, useState } from 'react'
import { externalTools, setExternalTools } from '../../api/endpoints'
import { externalToolNote, externalToolsSummary, withToolAllowed, type ExternalToolsState } from '../../api/externalToolsView'

/** Settings: Codex external tools that can run outside the Hook. Protected runs keep only the allowed ones on. */
export function ExternalToolsCard() {
  const [state, setState] = useState<ExternalToolsState | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { externalTools().then(setState).catch(() => setError('외부 도구 목록을 불러오지 못했어요.')) }, [])

  async function toggle(name: string, on: boolean) {
    if (!state) return
    const allowed = withToolAllowed(state.tools.filter(tool => tool.allowed).map(tool => tool.name), name, on)
    setSaving(true); setError('')
    try { setState(await setExternalTools(allowed)) }
    catch (failure) { setError(failure instanceof Error ? failure.message : '설정을 저장하지 못했어요.') }
    finally { setSaving(false) }
  }

  return (
    <section className="glass settings-connection settings-tools" aria-labelledby="settings-tools-title">
      <div className="settings-connection-head">
        <div>
          <h2 id="settings-tools-title">외부 도구</h2>
          <span className="muted">{externalToolsSummary(state)}</span>
        </div>
      </div>
      <p className="settings-tools-lead">
        Codex에 연결된 외부 도구(MCP)는 실행 전 검사(Hook)를 거치지 않을 수 있어서, AIA가 막거나 기록하지 못할 수 있어요.
        그래서 보호 실행에서는 기본으로 꺼 둬요. Codex 설정 파일은 바꾸지 않으니 Codex 앱에서는 그대로 쓸 수 있어요.
      </p>
      {state && state.tools.length > 0 && (
        <ul className="settings-tool-list">
          {state.tools.map(tool => (
            <li key={`${tool.source}:${tool.name}`}>
              <button
                type="button" role="switch" aria-checked={tool.on_in_protected_runs} className="glass-switch"
                disabled={saving || !tool.can_turn_off} onClick={() => toggle(tool.name, !tool.on_in_protected_runs)}
              >
                <span>
                  <span className="mono">{tool.name}</span>
                  <small>{externalToolNote(tool)}{!tool.can_turn_off && ' · 이름 형식 때문에 AIA가 끌 수 없어요'}</small>
                </span>
                <span className="glass-switch-track" aria-hidden="true"><span className="glass-switch-thumb" /></span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="danger-text" role="alert">{error}</p>}
      <p className="faint-note">켜기·끄기는 다음 보호 실행부터 적용돼요. 켜 둔 도구는 Hook을 거치지 않으면 차단·기록되지 않을 수 있어요.</p>
    </section>
  )
}
