import test from 'node:test'
import assert from 'node:assert/strict'
import { applyEvents, EMPTY_CONVERSATION } from '../src/components/terminal/codexConversation.ts'

const question = {
  sequence: 1,
  type: 'question.requested',
  question_id: 'question-1',
  questions: [
    { id: 'scope', header: 'Scope', question: 'Which files?', options: [{ label: 'All', description: '' }], allow_other: true, secret: false },
    { id: 'token', header: 'Token', question: 'Paste it', options: [], allow_other: false, secret: true },
  ],
  auto_resolve_at: null,
}

test('a Codex question stays pending until it is answered, and a secret answer is never kept', () => {
  const asked = applyEvents(EMPTY_CONVERSATION, [question])
  assert.deepEqual(asked.pendingQuestions.map(item => item.question_id), ['question-1'])
  assert.equal(asked.items[0].kind, 'question')
  assert.equal(asked.items[0].outcome, null)

  const answered = applyEvents(asked, [{ sequence: 2, type: 'question.answered', question_id: 'question-1', skipped: false, answers: { scope: ['All'], token: null } }])
  assert.deepEqual(answered.pendingQuestions, [])
  assert.equal(answered.items[0].outcome, 'answered')
  assert.deepEqual(answered.items[0].answers, { scope: ['All'], token: null })
  assert.equal(answered.items[0].request.questions.length, 2, 'the question text survives the answer')
})

test('skipped, resolved by Codex, and cancelled questions each close the card', () => {
  const asked = applyEvents(EMPTY_CONVERSATION, [question])
  assert.equal(applyEvents(asked, [{ sequence: 2, type: 'question.answered', question_id: 'question-1', skipped: true, answers: {} }]).items[0].outcome, 'skipped')
  assert.equal(applyEvents(asked, [{ sequence: 2, type: 'question.resolved', question_id: 'question-1', reason: 'resolved_by_codex' }]).items[0].outcome, 'resolved')
  const cancelled = applyEvents(asked, [{ sequence: 2, type: 'question.resolved', question_id: 'question-1', reason: 'cancel' }])
  assert.equal(cancelled.items[0].outcome, 'cancelled')
  assert.deepEqual(cancelled.pendingQuestions, [])
  assert.deepEqual(applyEvents(asked, [{ sequence: 2, type: 'session.exited', unexpected: true }]).pendingQuestions, [])
})

test('an MCP input request closes with its action and keeps no submitted values', () => {
  const asked = applyEvents(EMPTY_CONVERSATION, [{
    sequence: 1, type: 'elicitation.requested', elicitation_id: 'elicitation-1', server: 'tracker', mode: 'form', message: 'Need input',
    fields: [{ name: 'project', title: 'Project', description: '', required: true, kind: 'select', options: [{ value: 'web', label: 'web' }] }],
    url: null, url_host: null, supported: true,
  }])
  assert.deepEqual(asked.pendingElicitations.map(item => item.elicitation_id), ['elicitation-1'])
  const done = applyEvents(asked, [{ sequence: 2, type: 'elicitation.resolved', elicitation_id: 'elicitation-1', action: 'accept' }])
  assert.deepEqual(done.pendingElicitations, [])
  assert.equal(done.items[0].action, 'accept')
  assert.equal(done.items[0].request.server, 'tracker')
  assert.equal(JSON.stringify(done.items[0]).includes('content'), false)
})

test('a permission request closes with the decision and summarises what it widens', async () => {
  const { grantSummary, widensBeyondProtection } = await import('../src/api/permissionGrants.ts')
  const request = { network: true, filesystem: [{ access: 'write', target: 'D:/shared', scope: 'outside' }, { access: 'read', target: '작업 폴더 / docs', scope: 'inside' }] }
  const asked = applyEvents(EMPTY_CONVERSATION, [{ sequence: 1, type: 'permissions.requested', permissions_id: 'permissions-1', reason: 'sync', ...request }])
  assert.equal(asked.pendingPermissions.length, 1)
  const granted = applyEvents(asked, [{ sequence: 2, type: 'permissions.resolved', permissions_id: 'permissions-1', decision: 'session' }])
  assert.deepEqual(granted.pendingPermissions, [])
  assert.equal(granted.items[0].decision, 'session')
  assert.equal(grantSummary({ ...request, scope: 'session' }), '인터넷 · 쓰기 D:/shared · 읽기 작업 폴더 / docs · 실행 내내')
  assert.equal(widensBeyondProtection([{ granted_at: 't', scope: 'turn', ...request }]), true)
  assert.equal(widensBeyondProtection([{ granted_at: 't', scope: 'turn', network: false, filesystem: [{ access: 'read', target: 'x', scope: 'inside' }] }]), false)
})

test('usage shows the tightest window and hides when Codex reports nothing', async () => {
  const { usageChip, windowLabel, resetLabel, tokensLabel } = await import('../src/api/usageView.ts')
  assert.equal(usageChip({ limits: null, tokens: null }), null)
  const chip = usageChip({ limits: { windows: [{ used_percent: 42, window_minutes: 300, resets_at: null }, { used_percent: 85, window_minutes: 10080, resets_at: null }] }, tokens: null })
  assert.deepEqual(chip, { text: '주간 한도 15% 남음', low: true })
  assert.deepEqual(usageChip({ limits: null, tokens: { total_tokens: 12345, context_window: 200000 } }), { text: '이번 대화 12,345 토큰 · 문맥 6% 사용', low: false })
  assert.deepEqual([windowLabel(300), windowLabel(1440), windowLabel(90), windowLabel(null)], ['5시간', '하루', '90분', '사용 한도'])
  const now = Date.parse('2026-10-07T10:00:00Z')
  assert.equal(resetLabel('2026-10-07T12:10:00Z', now), '2시간 10분 뒤 초기화')
  assert.equal(resetLabel('2026-10-09T13:00:00Z', now), '2일 3시간 뒤 초기화')
  assert.equal(resetLabel(null, now), null)
  assert.equal(tokensLabel(null), null)
  const state = applyEvents(EMPTY_CONVERSATION, [{ sequence: 1, type: 'usage.limits', limits: { windows: [] } }, { sequence: 2, type: 'usage.tokens', tokens: { total_tokens: 5, context_window: null } }])
  assert.deepEqual(state.usage, { limits: { windows: [] }, tokens: { total_tokens: 5, context_window: null } })
})

test('model chip names the chosen model and effort, and efforts follow the model', async () => {
  const { effortLabel, effortsFor, modelChipText } = await import('../src/api/modelView.ts')
  const models = [
    { model: 'gpt-fast', display_name: 'GPT Fast', description: '', is_default: true, default_effort: 'medium', efforts: [{ effort: 'low', description: '' }, { effort: 'medium', description: '' }] },
    { model: 'gpt-deep', display_name: 'GPT Deep', description: '', is_default: false, default_effort: 'high', efforts: [{ effort: 'xhigh', description: '' }] },
  ]
  assert.deepEqual(effortsFor(models, null).map(item => item.effort), ['low', 'medium'])
  assert.deepEqual(effortsFor(models, 'gpt-deep').map(item => item.effort), ['xhigh'])
  assert.equal(modelChipText(models, 'gpt-deep', 'xhigh'), 'GPT Deep · 아주 깊게')
  assert.equal(modelChipText(models, null, null, 'gpt-fast'), 'GPT Fast · 기본값')
  assert.equal(modelChipText([], null, null, null), 'Codex 기본 모델 · 기본값')
  assert.equal(effortLabel('turbo'), 'turbo')
  const state = applyEvents(EMPTY_CONVERSATION, [{ sequence: 1, type: 'settings.changed', model: 'gpt-deep', effort: 'xhigh' }])
  assert.deepEqual(state.turnSettings, { model: 'gpt-deep', effort: 'xhigh' })
})

test('the latest Codex plan replaces the previous one', () => {
  const state = applyEvents(EMPTY_CONVERSATION, [
    { sequence: 1, type: 'plan.updated', turn_id: 't1', explanation: 'fix', steps: [{ step: 'read', status: 'inProgress' }] },
    { sequence: 2, type: 'plan.updated', turn_id: 't1', explanation: 'fix', steps: [{ step: 'read', status: 'completed' }, { step: 'test', status: 'pending' }] },
  ])
  assert.deepEqual(state.plan.steps.map(step => step.status), ['completed', 'pending'])
})
