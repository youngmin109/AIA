/** Preparation steps the server reports while a protected run starts (EPIC-021 TASK-102). */
export interface StartupInfo {
  current?: string | null
  steps?: Array<{ step: string; started_at: string; ended_at: string | null }>
  progress?: { stage: string; done: number; total: number | null }
}

export interface StartupView {
  label: string
  detail: string | null
  index: number
  total: number
  startedAt: string | null
  /** 0..100 while files are copied or re-checked; null when the total is unknown. */
  percent: number | null
  largeFolder: boolean
}

const STEPS = ['checkpoint', 'sensors', 'readiness', 'launch', 'conversation'] as const
type Step = typeof STEPS[number]

const LABELS: Record<Step, string> = {
  checkpoint: '기준점 저장 중',
  sensors: '감시 장치 시작 중',
  readiness: '보호 준비 확인 중',
  launch: 'Codex 시작 전 최종 확인 중',
  conversation: 'Codex 대화 연결 중',
}

/** Above this many files or bytes the checkpoint visibly slows the start. */
export const LARGE_FOLDER_FILES = 1000
export const LARGE_FOLDER_BYTES = 50 * 1024 * 1024

function count(value: number): string {
  return value.toLocaleString('ko-KR')
}

/** Display only: names the step that is running; it never claims a step succeeded. */
export function startupView(startup?: StartupInfo | null): StartupView | null {
  const current = startup?.current
  const index = STEPS.indexOf(current as Step)
  if (!current || index < 0) return null
  const progress = current === 'checkpoint' ? startup?.progress : undefined
  let detail: string | null = null
  let percent: number | null = null
  if (progress) {
    if (progress.stage === 'scan') detail = `파일 확인 ${count(progress.done)}개`
    else if (progress.total) {
      detail = `${progress.stage === 'copy' ? '파일 복사' : '바뀌지 않았는지 다시 확인'} ${count(progress.done)}/${count(progress.total)}`
      percent = Math.min(100, Math.round((progress.done / progress.total) * 100))
    }
  }
  const last = startup?.steps?.at(-1)
  return {
    label: LABELS[current as Step],
    detail,
    index: index + 1,
    total: STEPS.length,
    startedAt: last?.step === current ? last.started_at : null,
    percent,
    largeFolder: Boolean(progress && Math.max(progress.done, progress.total ?? 0) >= LARGE_FOLDER_FILES),
  }
}

/** New-run sheet notice for a folder that will start slowly; null when it is small. */
export function largeFolderNotice(estimate?: { files: number; bytes: number; complete: boolean } | null): string | null {
  if (!estimate || (estimate.complete && estimate.files < LARGE_FOLDER_FILES && estimate.bytes < LARGE_FOLDER_BYTES)) return null
  const megabytes = Math.round(estimate.bytes / (1024 * 1024))
  const size = estimate.complete ? `파일 ${count(estimate.files)}개(${count(megabytes)}MB)인` : `파일 ${count(estimate.files)}개가 넘는`
  return `${size} 큰 폴더예요. 시작할 때 폴더 전체를 기준점으로 저장하고 다시 확인해서 1분 넘게 걸릴 수 있어요. 작업할 하위 폴더만 고르면 빨라져요.`
}
