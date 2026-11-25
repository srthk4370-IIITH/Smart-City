# QIDK report viewer

Static page that opens the signed incident QR codes from the board (`GET /api/incidents/{id}/qr`).
The whole report is in the URL fragment (never sent to a server). It verifies the Ed25519 signature,
shows a clean report and prints / saves as PDF. No external requests.

Files in `dist/`: `index.html`, `viewer.js` (UI), `core.js` (Ed25519 verify + decode), `config.js` (trust list).

## Trust list
Add each board's public key (board: Share as QR > Technical details, or `pubkey` in the API reply) to
`dist/config.js`: `window.QR_TRUST = { "<board_id>": "<64 hex>" }`. Unlisted boards show "NOT verified".

## Board settings
`SCE_QR_VIEWER` / profile key `qr_viewer`: viewer URL (default `https://qidk-report.pages.dev/`).
`SCE_BOARD_ID` / `board_id`: id shown as "Signed by board". Signing key: `state/qr_key` (created at first use, 0600).

## Deploy (owner / main session; not run by the agent)
```
cd Code/smart-city-edge-agent/report-viewer
wrangler pages project create qidk-report --production-branch main   # first time only
wrangler pages deploy dist --project-name qidk-report --branch main
```
No `--commit-dirty`.
