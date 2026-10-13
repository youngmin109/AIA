import { Icon } from '../common/Icon'
import {
  PERMISSION_OPTIONS, PERMISSION_TITLE, permissionAllowed, permissionOption,
  type PermissionMode, type PermissionProfile,
} from '../../api/permissionMode'

/** The Codex app's permission menu: its three choices, words and order; one Codex forbids is greyed out. */
export function PermissionMenu({ mode, profiles, disabled, onChoose }: {
  mode: PermissionMode | null
  profiles: PermissionProfile[]
  disabled: boolean
  onChoose: (mode: PermissionMode) => void
}) {
  return (
    <div className="permission-menu" role="radiogroup" aria-label={PERMISSION_TITLE}>
      <p className="permission-menu-title">{PERMISSION_TITLE}</p>
      {PERMISSION_OPTIONS.map(option => {
        const allowed = permissionAllowed(option, profiles)
        const selected = option.mode === mode
        return (
          <button
            key={option.mode} type="button" role="radio" aria-checked={selected} disabled={disabled || !allowed}
            className={`permission-option${selected ? ' is-selected' : ''}${option.mode === 'full_access' ? ' is-full' : ''}`}
            onClick={() => onChoose(option.mode)}
          >
            <Icon name={option.icon} size={16} />
            <span>
              <strong>{option.label}</strong>
              <small>{allowed ? option.note : 'Codex 설정에서 허용하지 않아 고를 수 없어요'}</small>
            </span>
            {selected && <span className="permission-check"><Icon name="check" size={16} /></span>}
          </button>
        )
      })}
    </div>
  )
}

/** Permission for the next requests, like the Codex app's composer chip. The AIA Hook checks every command either way. */
export function PermissionChip({ mode, profiles, disabled, onChoose, open, onOpenChange }: {
  mode: PermissionMode | null
  profiles: PermissionProfile[]
  disabled: boolean
  onChoose: (mode: PermissionMode) => boolean
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const current = permissionOption(mode)
  return (
    <span className="usage-chip">
      <button type="button" className={`chip is-small permission-chip${mode === 'full_access' ? ' is-full' : ''}`} aria-expanded={open} onClick={() => onOpenChange(!open)}>
        {current && <Icon name={current.icon} size={13} />}{current?.chip ?? '권한 확인 중'}
      </button>
      {open && (
        <span className="usage-pop glass-card permission-pop" role="dialog" aria-label="권한">
          <PermissionMenu mode={mode} profiles={profiles} disabled={disabled}
            onChoose={next => { if (next === mode || onChoose(next)) onOpenChange(false) }} />
          <small className="faint-note">다음 요청부터 적용되고, 바꾼 기록은 이번 실행 결과에 남아요. AIA는 모든 명령을 실행 전에 검사해요.</small>
        </span>
      )}
    </span>
  )
}
