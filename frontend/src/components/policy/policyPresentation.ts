import type { IconName } from '../common/Icon'
import type { PolicyRule } from './policyModel'

export const POLICY_ICONS: Record<string, IconName> = {
  PROTECTED_DEVELOPMENT: 'shieldPlain', BASIC_DEVELOPMENT: 'chat',
  CONSERVATIVE_SECURITY: 'lock', FREE_DEVELOPMENT: 'search', CUSTOM: 'settings',
}

const DEPENDENCIES = ['pyproject.toml', 'uv.lock', 'requirements*.txt', 'package.json', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock']
const INFRASTRUCTURE = ['Dockerfile', 'docker-compose*.yml', 'docker-compose*.yaml', '*.tf']
type RuleInfo = { title: string; description: string; icon: IconName }
type NamedTarget = RuleInfo & { patterns: string[]; command?: boolean }
const TARGETS: NamedTarget[] = [
  { title: '비밀 설정 파일', description: '.env와 하위 폴더의 .env 계열 파일을 대상으로 해요.', icon: 'lock', patterns: ['.env', '.env.*', '**/.env', '**/.env.*'] },
  { title: '루트 비밀 설정 파일', description: '작업 폴더 바로 아래의 .env 파일 하나를 대상으로 해요.', icon: 'lock', patterns: ['.env'] },
  { title: '비밀 설정 내용 출력', description: '.env 내용을 화면에 출력하는 대표 명령을 대상으로 해요.', icon: 'lock', command: true, patterns: ['type .env*', 'cat .env*', 'Get-Content .env*', 'more .env*', 'cmd /c type .env*', 'powershell* get-content* .env*'] },
  { title: '패키지·라이브러리 설정 파일', description: '설치할 패키지 목록과 버전 고정 파일을 대상으로 해요.', icon: 'file', patterns: DEPENDENCIES },
  { title: '배포·서버 설정 파일', description: 'Docker와 Terraform 설정 파일을 대상으로 해요.', icon: 'file', patterns: INFRASTRUCTURE },
  { title: '접속 설정 파일', description: '서비스 접속 설정(connection-check) 파일을 대상으로 해요.', icon: 'lock', patterns: ['release/connection-check.json'] },
  { title: '고객정보 원장 파일', description: '서비스가 쓰는 고객정보 원장(customer-ledger) 파일을 대상으로 해요.', icon: 'file', patterns: ['data/customer-ledger.csv'] },
  ...[
    ['데이터베이스 삭제', '데이터베이스 전체를 없애는 명령', 'DROP DATABASE'],
    ['데이터 테이블 삭제', '테이블 구조와 데이터를 없애는 명령', 'DROP TABLE'],
    ['테이블 데이터 비우기', '테이블 안의 데이터를 지우는 명령', 'TRUNCATE'],
    ['데이터베이스 이전 버전으로 변경', '데이터베이스 구조를 이전 버전으로 되돌리는 명령', 'alembic downgrade'],
    ['Git 작업 내용 강제 초기화', '저장하지 않은 작업 내용을 버릴 수 있는 명령', 'git reset --hard'],
    ['Git 미추적 파일 정리', 'Git에 등록하지 않은 파일을 삭제하는 명령', 'git clean -fd'],
    ['Git 제외 파일까지 정리', 'Git 제외 파일까지 삭제하는 명령', 'git clean -fdx'],
  ].flatMap(([title, description, pattern]): NamedTarget[] => [
    { title, description: `${description}과 뒤에 공백·인수가 붙은 형태를 대상으로 해요.`, icon: 'terminal', command: true, patterns: [pattern] },
    { title, description: `${description}과 뒤에 인수가 붙은 형태를 대상으로 해요.`, icon: 'terminal', command: true, patterns: [`${pattern}*`] },
  ]),
  { title: '파일 삭제·프로세스 강제 종료', description: '일괄 삭제와 강제 종료에 쓰이는 대표 명령을 대상으로 해요.', icon: 'block', command: true, patterns: ['rm -rf*', 'rmdir /s*', 'rd /s*', 'del *', 'erase *', 'Remove-Item*', 'Stop-Process*', 'taskkill /f*'] },
]

// Names describe the actual targets, not rule IDs: edited targets must never
// retain a misleading built-in name. Raw patterns remain in advanced settings.
function signature(patterns: string[]) { return [...patterns].sort().join('\n') }
export function rulePresentation(rule: PolicyRule): RuleInfo {
  const command = Boolean(rule.command_patterns)
  const patterns = rule.command_patterns ?? rule.path_patterns ?? []
  const known = TARGETS.find(target => Boolean(target.command) === command && signature(target.patterns) === signature(patterns))
  if (known) return known
  return command
    ? { title: '직접 지정한 명령', description: `${patterns.length}개 명령 패턴에 적용해요. 고급 설정에서 대상을 확인해 주세요.`, icon: 'terminal' }
    : { title: '직접 지정한 파일·폴더', description: `${patterns.length}개 경로 패턴에 적용해요. 고급 설정에서 대상을 확인해 주세요.`, icon: 'folder' }
}

export function ruleEffects(rule: PolicyRule): Array<{ effect: string; operations: string[] }> {
  return ['DENY', 'AUDIT', 'ALLOW'].flatMap(effect => {
    const operations = Object.entries(rule.operation_effects).filter(([, value]) => value === effect).map(([operation]) => operation)
    return operations.length ? [{ effect, operations }] : []
  })
}

// One color per effect, shared by the guide, badges, rule card edges and operation tiles.
export const EFFECT_LOOK: Record<string, { tone: string; badge: string; icon: IconName }> = {
  DENY: { tone: 'is-deny', badge: 'is-bad', icon: 'block' },
  AUDIT: { tone: 'is-audit', badge: 'is-warn', icon: 'records' },
  ALLOW: { tone: 'is-allow', badge: 'is-ok', icon: 'check' },
}
export function effectTone(effect: string | undefined) { return effect ? EFFECT_LOOK[effect]?.tone ?? '' : '' }
export function effectBadge(effect: string | undefined) { return `badge ${effect ? EFFECT_LOOK[effect]?.badge ?? 'is-neutral' : 'is-neutral'}` }
/** The strictest effect a rule applies colors its card edge. */
export function ruleCardClass(rule: PolicyRule) { return `custom-rule ${effectTone(ruleEffects(rule)[0]?.effect)}`.trim() }

export const RULE_STARTERS: Array<{ key: string; label: string; path_patterns?: string[]; command_patterns?: string[]; asset_type: string; operation_effects: Record<string, string> }> = [
  { key: 'folder', label: '내 파일·폴더 보호', path_patterns: ['protected/**'], asset_type: 'WORKSPACE', operation_effects: { DELETE: 'DENY', MODIFY: 'AUDIT' } },
  { key: 'secret', label: '비밀 설정 파일 보호', path_patterns: ['.env', '.env.*', '**/.env', '**/.env.*'], asset_type: 'SECRET', operation_effects: { READ: 'DENY', CREATE: 'DENY', MODIFY: 'DENY', DELETE: 'DENY', MOVE: 'DENY', RENAME: 'DENY' } },
  { key: 'command', label: '특정 명령 실행 금지', command_patterns: ['git reset --hard*'], asset_type: 'REPOSITORY', operation_effects: { EXECUTE: 'DENY' } },
]

export function makeRule(key: string, id: string): PolicyRule {
  const starter = RULE_STARTERS.find(item => item.key === key) ?? RULE_STARTERS[0]
  const { key: _key, label: _label, ...rule } = starter
  return { ...rule, rule_id: id, priority: 1100, operation_effects: { ...rule.operation_effects },
    ...(rule.path_patterns ? { path_patterns: [...rule.path_patterns] } : { command_patterns: [...(rule.command_patterns ?? [])] }) }
}
