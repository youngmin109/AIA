/**
 * Plain-language summary of a finished run for the result screen.
 * Each axis stays separate: a block decision (CONTAIN) is not a confirmed
 * block, a restore (RESTORED) is not an integrity check (VERIFIED).
 */

export interface SummaryCounts {
  total?: number
  violation?: number
  contain?: number
  blocked?: number
  terminated?: number
}

export interface SummaryInput {
  action_summary?: SummaryCounts | null
  codex_block_confirmation?: string | null
  recovery_status?: string | null
  integrity_status?: string | null
}

/** Headline lines, most important first. Never claims more than the counts prove. */
export function resultHeadline(result: SummaryInput, changedFiles: number | null): string[] {
  const counts = result.action_summary ?? {}
  const lines: string[] = []
  const confirmedBlocks = result.codex_block_confirmation === 'BLOCK_CONFIRMED' ? counts.blocked ?? 0 : 0
  if (confirmedBlocks > 0) lines.push(`위험 요청 ${confirmedBlocks}건을 막았어요`)
  else if ((counts.terminated ?? 0) > 0) lines.push(`프로세스 종료 ${counts.terminated}건을 확인했어요`)
  else if ((counts.contain ?? 0) > 0) lines.push(`위험 요청 ${counts.contain}건을 차단 판정했어요`)
  else if ((counts.violation ?? 0) > 0) lines.push(`정책 사건 ${counts.violation}건이 기록됐어요`)
  else lines.push('위험한 요청은 관찰되지 않았어요')
  if (result.recovery_status === 'RESTORED' && result.integrity_status === 'VERIFIED') lines.push('작업 폴더를 되돌리고 검증했어요')
  else if (changedFiles !== null) lines.push(changedFiles > 0 ? `파일 ${changedFiles}개가 바뀌었어요` : '바뀐 파일은 없었어요')
  return lines
}

export interface FileBreakdown { created: number; modified: number; deleted: number; moved: number }

export function fileBreakdown(files: Array<{ event_type?: string }> | null | undefined): FileBreakdown {
  const counts: FileBreakdown = { created: 0, modified: 0, deleted: 0, moved: 0 }
  for (const file of files ?? []) {
    const type = file.event_type as keyof FileBreakdown
    if (type in counts) counts[type] += 1
  }
  return counts
}

export interface RestoreRecord {
  recovery_status?: string
  planned_operation_count?: number
  succeeded_operation_count?: number
  failed_operation_count?: number
  failed_paths?: string[]
}

export interface IntegrityRecord {
  integrity_status?: string
  missing_paths?: string[]
  unexpected_paths?: string[]
  changed_paths?: string[]
  type_mismatches?: string[]
}

export interface RestoreStep { key: string; label: string; detail: string; state: 'done' | 'warn' | 'fail' }

/** Steps shown after a restore, rebuilt from the server's recovery and integrity records. */
export function restoreSteps(recovery: RestoreRecord | null | undefined, integrity: IntegrityRecord | null | undefined, checkpointLabel: string | null): RestoreStep[] {
  const failed = recovery?.failed_operation_count ?? recovery?.failed_paths?.length ?? 0
  const succeeded = recovery?.succeeded_operation_count ?? 0
  const planned = recovery?.planned_operation_count ?? succeeded + failed
  const mismatches = (integrity?.missing_paths?.length ?? 0) + (integrity?.unexpected_paths?.length ?? 0)
    + (integrity?.changed_paths?.length ?? 0) + (integrity?.type_mismatches?.length ?? 0)
  const restored = recovery?.recovery_status === 'RESTORED'
  const verified = integrity?.integrity_status === 'VERIFIED'
  return [
    { key: 'checkpoint', label: '기준점 확인', detail: checkpointLabel ? `실행 전 ${checkpointLabel}` : '실행 전 기준점', state: 'done' },
    { key: 'restore', label: `파일 되돌리기 ${succeeded}개`, detail: failed > 0 ? `${failed}개 실패 · 계획 ${planned}개` : `계획한 ${planned}개 모두 처리`, state: restored && failed === 0 ? 'done' : failed > 0 ? 'fail' : 'warn' },
    { key: 'integrity', label: '무결성 검증', detail: verified ? `SHA-256 일치 · 불일치 ${mismatches}개` : `확인 필요 · 불일치 ${mismatches}개`, state: verified ? 'done' : 'fail' },
  ]
}
