/**
 * Plain-language view of a protected run that ended in FAILED.  The server keeps
 * the raw reason in `status.error` ("ErrorType: message"); a run that failed while
 * preparing never opened a conversation, so this is the only place it explains.
 */
export interface StartupFailureView {
  title: string
  reason: string
  /** The folder or file the reason is about, shown relative to the work folder. */
  item: string | null
  hint: string | null
  /** The raw server reason, kept for a bug report. */
  detail: string | null
}

const UNREADABLE = /(?:Workspace (?:directory|file) cannot be read|Workspace entry cannot be inspected): (.+)$/
const CHANGED = /(?:disappeared during checkpoint|changed during (?:checkpoint|copy)|changed type during copy)/
const OVERLAP = /control_root and workspace must not overlap/

/** Windows paths: compare without case and with either separator. */
function comparable(path: string): string {
  return path.replace(/\//g, '\\').toLowerCase()
}

function withinWorkspace(path: string, workspace?: string | null): string {
  if (!workspace) return path
  const root = workspace.replace(/[\\/]+$/, '')
  if (comparable(path).startsWith(`${comparable(root)}\\`)) return path.slice(root.length + 1)
  return path
}

export function startupFailureView(error: string | null | undefined, workspace?: string | null): StartupFailureView {
  const detail = error?.trim() || null
  const unreadable = detail?.match(UNREADABLE)
  if (unreadable) {
    return {
      title: '보호를 시작하지 못했어요',
      reason: '작업 폴더 안에 AIA가 읽을 수 없는 항목이 있어, 시작 전에 되돌릴 기준점을 만들지 못했어요.',
      item: withinWorkspace(unreadable[1].trim(), workspace),
      hint: '다른 계정이 만든 항목일 수 있어요. 예를 들어 Codex를 \'승인 요청\'(샌드박스)으로 실행할 때 생긴 폴더는 내 계정으로 읽을 수 없어요. 그 항목을 작업 폴더 밖으로 옮기거나 관리자 권한으로 권한을 되찾은 뒤 다시 시작해 주세요.',
      detail,
    }
  }
  if (detail && OVERLAP.test(detail)) {
    return {
      title: '이 폴더는 작업 폴더로 고를 수 없어요',
      reason: 'AIA가 증거와 기준점을 보관하는 기록 폴더가 이 폴더 안에 있어요. 감시 대상과 증거 보관소가 겹치면 에이전트가 증거를 건드릴 수 있어서 막았어요.',
      item: null,
      hint: '드라이브 전체나 사용자 폴더 대신, 작업할 프로젝트 폴더를 골라 주세요.',
      detail,
    }
  }
  if (detail && CHANGED.test(detail)) {
    return {
      title: '보호를 시작하지 못했어요',
      reason: '기준점을 만드는 동안 작업 폴더의 내용이 바뀌었어요.',
      item: null,
      hint: '다른 프로그램이 이 폴더에 파일을 쓰고 있지 않은지 확인한 뒤 다시 시작해 주세요.',
      detail,
    }
  }
  return {
    title: '보호 실행이 실패로 끝났어요',
    reason: detail ? '아래 오류 원문에 이유가 있어요.' : '서버가 실패 이유를 남기지 않았어요.',
    item: null,
    hint: null,
    detail,
  }
}
