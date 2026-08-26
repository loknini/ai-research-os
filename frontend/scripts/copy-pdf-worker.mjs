// Copy pdfjs-dist worker file from node_modules to public/.
//
// Why this exists:
//   - react-pdf's <Document> loads its PDF.js worker via `new Worker(url, {type:'module'})`.
//   - In Vite dev mode, `import 'pdfjs-dist/build/pdf.worker.min.mjs?url'` returns a
//     relative URL (`/node_modules/...`). Vite serves that path with HMR client
//     injected at the top (`import { injectQuery } from "/@vite/client"`), which
//     breaks when Web Worker tries to resolve it (becomes
//     `/node_modules/pdfjs-dist/build/@vite/client` → 404).
//   - Copying the worker to public/ gives us `/pdf.worker.min.mjs` as a static URL.
//     Vite serves public/ files directly (no HMR injection), and FastAPI static
//     hosting also serves them in production.
//
// The bundled dist already has its own hashed copy (`dist/assets/pdf.worker.min-*.mjs`)
// via `?url` import — that path still works in production, but the public/ copy is
// the dev-safe default so we don't have to maintain a different workerSrc per env.

import { copyFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, '..');

const SRC = resolve(ROOT, 'node_modules/pdfjs-dist/build/pdf.worker.min.mjs');
const DEST = resolve(ROOT, 'public/pdf.worker.min.mjs');

if (!existsSync(SRC)) {
  console.warn(`[copy-pdf-worker] source not found: ${SRC}`);
  console.warn('[copy-pdf-worker] skipping (run `npm install` first, then re-run install)');
  process.exit(0);
}

mkdirSync(dirname(DEST), { recursive: true });
copyFileSync(SRC, DEST);
console.log(`[copy-pdf-worker] copied: ${SRC} -> ${DEST}`);