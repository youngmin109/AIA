import assert from 'node:assert/strict'
import test from 'node:test'

const { parseBlocks, splitTableRow } = await import('../src/components/terminal/markdownBlocks.ts')

test('a pipe table becomes a table block instead of one long paragraph', () => {
  const blocks = parseBlocks([
    '| 경로 | 역할 |',
    '|---|---|',
    '| `src/refund.py` | 원 단위 정수 금액을 검증 |',
    '| `scripts/normal_check.py` | 환불 함수 8개 사례 검증 |',
  ].join('\n'))

  assert.equal(blocks.length, 1)
  assert.equal(blocks[0].kind, 'table')
  assert.deepEqual(blocks[0].header, ['경로', '역할'])
  assert.deepEqual(blocks[0].rows, [
    ['`src/refund.py`', '원 단위 정수 금액을 검증'],
    ['`scripts/normal_check.py`', '환불 함수 8개 사례 검증'],
  ])
})

test('a table right under a sentence still splits from it', () => {
  const blocks = parseBlocks('파일은 7개입니다.\n| a | b |\n| --- | --- |\n| 1 | 2 |\n\n끝')

  assert.deepEqual(blocks.map(block => block.kind), ['paragraph', 'table', 'paragraph'])
  assert.equal(blocks[0].text, '파일은 7개입니다.')
})

test('alignment, short rows and extra cells follow GFM', () => {
  const [table] = parseBlocks('| 이름 | 수 | 메모 |\n|:--|--:|:-:|\n| a | 1 |\n| b | 2 | x | y |')

  assert.deepEqual(table.aligns, ['left', 'right', 'center'])
  assert.deepEqual(table.rows, [['a', '1', ''], ['b', '2', 'x']])
})

test('a pipe inside inline code or escaped stays in its cell', () => {
  assert.deepEqual(splitTableRow('| `a | b` | c \\| d |'), ['`a | b`', 'c | d'])
})

test('without a full delimiter row (still streaming) the lines stay text', () => {
  assert.deepEqual(parseBlocks('| a | b |\n|---').map(block => block.kind), ['paragraph'])
  assert.deepEqual(parseBlocks('| a | b |').map(block => block.kind), ['paragraph'])
})

test('a plain rule and a list are not mistaken for a table', () => {
  assert.deepEqual(parseBlocks('위\n\n---\n\n- a | b\n- c').map(block => block.kind), ['paragraph', 'rule', 'list'])
})
