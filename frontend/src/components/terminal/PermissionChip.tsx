import { Icon } from '../common/Icon'
import { PERMISSION_OPTIONS, permissionChipText, type PermissionMode } from '../../api/permissionMode'

/** AI permission for the next requests: full access (YOLO) stands out; the AIA Hook checks every command either way. */
export function PermissionChip({ mode, disabled, onChoose, open, onOpenChange }: {
  mode: PermissionMode | null
  disabled: boolean
  onChoose: (mode: PermissionMode) => boolean
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const yolo = mode === 'full_access'
  return (
    <span className="usage-chip">
      <button type="button" className={`chip is-small permission-chip${yolo ? ' is-yolo' : ''}`} aria-expanded={open} onClick={() => onOpenChange(!open)}>
        <Icon name={yolo ? 'bolt' : 'lock'} size={13} />{permissionChipText(mode)}
      </button>
      {open && (
        <span className="usage-pop glass-card permission-pop" role="dialog" aria-label="AI 권한">
          {PERMISSION_OPTIONS.map(option => (
            <button
              key={option.mode} type="button" disabled={disabled}
              className={`permission-option${option.mode === mode ? ' is-selected' : ''}${option.mode === 'full_access' ? ' is-yolo' : ''}`}
              aria-pressed={option.mode === mode}
              onClick={() => { if (option.mode === mode || onChoose(option.mode)) onOpenChange(false) }}
            >
              <strong>{option.label}{option.badge && <span className="yolo-badge">{option.badge}</span>}</strong>
              <small>{option.note}</small>
            </button>
          ))}
          <small className="faint-note">다음 요청부터 적용되고, 바꾼 기록은 이번 실행 결과에 남아요.</small>
        </span>
      )}
    </span>
  )
}
