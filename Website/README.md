# Evidence website

Static, password-protected site for the evaluators of "Agentic Edge AI for Smart Cities" (spec: `SPEC.md`).
Everything with content is encrypted at build time and decrypted in the visitor's browser after the password.

## Build

One-time build tools (laptop):
```sh
py -3 -m pip install bcrypt cryptography
```
Build (Git Bash; the password is read from the environment and never written anywhere):
```sh
cd Website
SITE_PASSWORD='the-real-password' py -3 build/build.py               # collect -> validate -> encrypt -> dist/
SITE_PASSWORD='the-real-password' py -3 build/build.py --no-collect  # use data/ as it is
SITE_PASSWORD='test-only-pw'      py -3 build/build.py --mock        # dev: fake numbers from src/dev-mock/
```
PowerShell: `$env:SITE_PASSWORD='...'; py -3 build/build.py; Remove-Item Env:SITE_PASSWORD`.

The build fails if a data file is invalid JSON or contains raw-data keys (prompts, readings, windows ...), and it
deletes `dist/` again if the password or any plain data/page file ended up in it.

## Test locally
```sh
py -3 -m http.server 8080 --bind 127.0.0.1 -d dist
# open http://127.0.0.1:8080/
```
Automated checks (headless Chrome, screenshots to `qa/shell/`):
```sh
npm i puppeteer-core            # anywhere; then point PUPPETEER at it
PUPPETEER=<dir>/node_modules/puppeteer-core node qa/shell/qa_shell.js      # gate, deck, kit, 3 viewports
PUPPETEER=<dir>/node_modules/puppeteer-core node qa/shell/qa_realdata.js   # every dataset in the catalog draws
```

## Deploy (Cloudflare Pages)
`dist/` is the whole site; it contains `_headers` (CSP, no-cache for `index.html`/`auth.json`, caching for `vendor/`).
- Dashboard: Workers & Pages -> Create -> Pages -> Upload assets -> drop the `dist` folder.
- CLI: `npx wrangler pages deploy dist --project-name <name>` (first run asks to log in).

Every rebuild makes a new salt and a new key, so old `.enc` files and open sessions stop working: upload the whole
`dist/` each time. Changing the password = rebuild with the new one.

## Layout
```
build/build.py        the build (SHELL)          build/collect/*.py   data collectors (DATA)
src/index.html        gate + nav + router shell   src/pages/*.html|js  one page each (encrypted)
src/css/              tokens.css, base.css, components.css, deck.css
src/js/               app.js (router), crypto.js, data.js, ui.js, charts.js (+ CHARTS.md = page contract), deck.js
src/vendor/           ECharts, PDF.js, bcryptjs, pptx-preview, fonts (versions + licences: VERSIONS.md)
src/dev-mock/data/    fake data in the contract shape (only with --mock or when data/ is empty)
data/                 plain JSON (local only, never deployed in plain)
dist/                 deployable output
qa/shell/             screenshots + results of the shell checks
```

## Security model, in one paragraph
`auth.json` holds a bcrypt hash (cost 12) and a random PBKDF2 salt. The browser checks the password with bcryptjs,
derives an AES-256 key with WebCrypto PBKDF2-SHA256 (600,000 iterations) and decrypts each `*.enc` file
(12-byte random IV + AES-GCM ciphertext; the file path is authenticated data; gzip inside). The key lives in
`sessionStorage` until the tab closes or "lock" is pressed. Anyone with `dist/` can try passwords offline, so use a
long, random password (4+ random words); the content is safe exactly as long as the password is.
