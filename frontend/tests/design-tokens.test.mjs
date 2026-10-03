import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'

const styles = new URL('../src/styles/', import.meta.url)
const files = readdirSync(styles).filter(name => name.endsWith('.css'))
const read = name => readFileSync(new URL(name, styles), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '')

test('colors live in theme.css tokens, not in component CSS', () => {
  for (const name of files.filter(name => name !== 'theme.css')) {
    const literals = read(name).match(/#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(/g) ?? []
    assert.deepEqual(literals, [], `${name} has color literals; add a token to theme.css instead`)
  }
})

test('every CSS custom property that is used is defined', () => {
  const css = files.map(read).join('\n')
  const defined = new Set([...css.matchAll(/(--[\w-]+)\s*:/g)].map(match => match[1]))
  const used = new Set([...css.matchAll(/var\(\s*(--[\w-]+)/g)].map(match => match[1]))
  assert.deepEqual([...used].filter(name => !defined.has(name)), [])
})

test('components use classes instead of inline style objects', () => {
  const components = new URL('../src/components/', import.meta.url)
  const offenders = []
  const visit = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const url = new URL(entry.name + (entry.isDirectory() ? '/' : ''), dir)
      if (entry.isDirectory()) visit(url)
      else if (entry.name.endsWith('.tsx') && readFileSync(url, 'utf8').includes('style={{')) offenders.push(entry.name)
    }
  }
  visit(components)
  assert.deepEqual(offenders, [], 'move the style into a class in styles/components.css')
})
