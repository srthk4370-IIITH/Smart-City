# Vendored libraries

All files were downloaded once, on 2026-10-19, with `npm pack <name>@<version>` from the npm registry
(registry.npmjs.org). The site loads nothing from a CDN at runtime.

| Library | Version | Files here | Licence | SHA-256 (main file) |
|---|---|---|---|---|
| Apache ECharts (`echarts`) | 5.6.0 | `echarts/echarts.min.js` | Apache-2.0 (`echarts/LICENSE`, `echarts/NOTICE`) | `bf4a2235...c07b1` |
| PDF.js (`pdfjs-dist`), legacy build | 4.10.38 | `pdfjs/pdf.min.js`, `pdfjs/pdf.worker.min.js` (renamed from `.mjs` so every static host serves them as JavaScript), `pdfjs/cmaps/`, `pdfjs/standard_fonts/` | Apache-2.0 (`pdfjs/LICENSE`) | `44ec6f01...75fe2` / worker `bd888051...30afd41d` |
| bcryptjs | 2.4.3 | `bcryptjs/bcrypt.min.js` | MIT (`bcryptjs/LICENSE`) | `afd4bd29...5923783` |
| pptx-preview | 1.0.7 | `pptx-preview/pptx-preview.umd.js` | ISC (per its `package.json`; the npm package is free for personal and commercial use, see `pptx-preview/README.upstream.md`) | `98bcf8fb...7fe2` |
| Inter (`@fontsource/inter`) | 5.2.5 | `fonts/inter-latin-{400,500,600}-normal.woff2` | SIL OFL 1.1 (`fonts/LICENSE-Inter.txt`) | |
| JetBrains Mono (`@fontsource/jetbrains-mono`) | 5.2.5 | `fonts/jetbrains-mono-latin-{400,500}-normal.woff2` | SIL OFL 1.1 (`fonts/LICENSE-JetBrainsMono.txt`) | |

Notes
- PDF.js 4.10.38 is past the CVE-2024-4367 fix (4.2.67); the deck viewer also sets `isEvalSupported: false`.
- pptx-preview is loaded only when a `.pptx` is dropped (1.4 MB, it bundles its own JSZip/ECharts copy).
- To upgrade: `npm pack <name>@<new>`, copy the same files, update this table, rebuild.
