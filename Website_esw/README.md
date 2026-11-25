# Website_esw
Home + /report/ (report-viewer) + /fleet/ (fleet-viewer). Build: `sh build.sh` (regenerates fleet config.js if missing).
Deploy (wrangler v4 turns new projects into Workers; use v3 for Pages): `npx wrangler@3.114.0 pages deploy dist --project-name smart-city-esw --branch main` -> https://smart-city-esw.pages.dev
dist/ and config.js are gitignored.
