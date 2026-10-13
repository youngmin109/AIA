/** Files and folders the user picks to protect inside the work folder (sent as protected_paths). */
export const MAX_PROTECTED_PATHS = 100

function normalize(path: string): string {
  return path.trim().replace(/\//g, '\\').replace(/\\+$/, '')
}

/** The path relative to the work folder, or null for the folder itself or anything outside it. Windows paths compare case-insensitively. */
export function insideWorkspace(workspace: string, path: string): string | null {
  const root = normalize(workspace)
  const candidate = normalize(path)
  if (!root || !candidate) return null
  const prefix = `${root.toLowerCase()}\\`
  if (!candidate.toLowerCase().startsWith(prefix)) return null
  const relative = candidate.slice(prefix.length)
  return relative && !relative.split('\\').includes('..') ? relative : null
}

/** A typed entry as an absolute path: kept when absolute, otherwise joined to the work folder. */
export function absoluteInWorkspace(workspace: string, entry: string): string {
  const value = normalize(entry)
  return /^[A-Za-z]:\\|^\\\\/.test(value) ? value : `${normalize(workspace)}\\${value.replace(/^\\+/, '')}`
}

/** Adds paths inside the work folder once each; counts the ones left out as outside or over the limit. */
export function addProtectedPaths(current: string[], additions: string[], workspace: string): { paths: string[]; outside: number; overLimit: number } {
  const paths = [...current]
  let outside = 0
  let overLimit = 0
  for (const raw of additions) {
    const path = normalize(raw)
    if (!insideWorkspace(workspace, path)) { outside += 1; continue }
    if (paths.some(existing => existing.toLowerCase() === path.toLowerCase())) continue
    if (paths.length >= MAX_PROTECTED_PATHS) { overLimit += 1; continue }
    paths.push(path)
  }
  return { paths, outside, overLimit }
}
