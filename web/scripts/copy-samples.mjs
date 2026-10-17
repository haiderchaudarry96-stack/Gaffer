// Copies the real Phase 3 sample outputs from ../samples into public/sample/,
// so the dev server and the static build can fetch them. Runs before dev/build/test.
// Later the FastAPI backend serves the same resources; only src/data/ changes then.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = resolve(here, '..', '..', 'samples')
const dest = resolve(here, '..', 'public', 'sample')

// Only the files the app reads (see src/data/matches.ts).
const NEEDED = {
  w900_1260: [
    'match_state_top_w900_1260_4fps.json',
    'match_state_top_w900_1260_4fps.teams.json',
    'alerts_llm.jsonl',
    'explanations.json',
    'report_w900_1260.json',
    'report_w900_1260.md',
    'report_llm.json',
    'trace_llm.jsonl',
    'evt_003.jpg',
  ],
}

if (!existsSync(src)) {
  console.error(`copy-samples: ${src} not found. Run from a full clone of the Gaffer repo.`)
  process.exit(1)
}

rmSync(dest, { recursive: true, force: true })
let bytes = 0
let count = 0
for (const [match, files] of Object.entries(NEEDED)) {
  const from = join(src, match)
  const available = new Set(readdirSync(from))
  mkdirSync(join(dest, match), { recursive: true })
  for (const f of files) {
    if (!available.has(f)) {
      console.error(`copy-samples: missing ${join(from, f)}`)
      process.exit(1)
    }
    cpSync(join(from, f), join(dest, match, f))
    bytes += statSync(join(from, f)).size
    count += 1
  }
}
console.log(`copy-samples: ${count} files, ${(bytes / 1e6).toFixed(2)} MB -> public/sample/`)
