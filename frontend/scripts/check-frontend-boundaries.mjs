import { readFileSync, readdirSync } from 'node:fs'
import { dirname, extname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const src = join(root, 'src')
const transport = join(src, 'services', 'api.ts')
const errors = []

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return sourceFiles(path)
    return ['.ts', '.tsx'].includes(extname(entry.name)) ? [path] : []
  })
}

for (const file of sourceFiles(src)) {
  const source = readFileSync(file, 'utf8')
  const executableSource = source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '')
  if (file !== transport && /\bfetch\s*\(/.test(executableSource)) {
    errors.push(`${relative(root, file)} calls fetch directly; use @/services/api`)
  }
}

const pageLimits = new Map([
  [join(src, 'hubs', 'chat', 'ChatHub.tsx'), 400],
  [join(src, 'hubs', 'settings', 'index.tsx'), 300],
])

for (const [file, limit] of pageLimits) {
  const lines = readFileSync(file, 'utf8').split(/\r?\n/).length
  if (lines > limit) errors.push(`${relative(root, file)} has ${lines} lines (limit: ${limit})`)
}

if (sourceFiles(src).some((file) => file.endsWith('apiMonitor.ts'))) {
  errors.push('apiMonitor.ts must not be restored; connectivity belongs in the explicit transport')
}

if (errors.length) {
  console.error(errors.join('\n'))
  process.exit(1)
}

console.log('Frontend boundaries OK: one HTTP transport and thin Hub entry points.')
