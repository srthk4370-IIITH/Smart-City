#!/usr/bin/env bash
# 2026-11-04 website build (+ deploy) for the evaluation. Like proofs/2026-10-28_master/website_final.sh, but: full collect
# (build.py default, the new recent.py datasets), NO git commit / push (owner commits; push is the owner's job).
# The site password is read at run time from the gitignored website_final.sh and never printed or written elsewhere.
#   bash website_1104.sh build    -> collect + build dist/ only
#   bash website_1104.sh deploy   -> build, wrangler deploy --branch main, verify both URLs answer with the password page
# Never touches the board. Log: website_1104.log next to this script.
P=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-11-04_split; SRC=/mnt/c/Users/hp/Desktop/qidk/proofs/2026-10-28_master/website_final.sh
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe; WEBW='C:\Users\hp\Desktop\qidk\Website'
exec >> $P/website_1104.log 2>&1 < /dev/null
log(){ echo "$(date -u +%FT%TZ) $*"; }
ps(){ $PS -NoProfile -NonInteractive -Command "$1" 2>&1 | tr -d '\r'; }
PWX=$(grep -o "SITE_PASSWORD='[^']*'" $SRC | head -1)   # the PowerShell assignment text, quotes included
[ -n "$PWX" ] || { log "ABORT: no password in website_final.sh"; exit 1; }
log "=== website_1104 ${1:-build}"
rm -f /mnt/c/Users/hp/Desktop/qidk/Website/dist/auth.json
ps "\$ErrorActionPreference='Continue'; Set-Location '$WEBW'; \$env:$PWX; py -3 build\build.py; Remove-Item Env:SITE_PASSWORD" > $P/website_1104.build.txt
tail -5 $P/website_1104.build.txt
grep -q '\[build\] ok:' $P/website_1104.build.txt && [ -s /mnt/c/Users/hp/Desktop/qidk/Website/dist/auth.json ] || { log "=== BUILD FAILED"; exit 1; }
log "build ok"
[ "$1" = deploy ] || { log "=== done (build only)"; exit 0; }
ps "Set-Location '$WEBW'; wrangler pages deploy dist --project-name qidk-nasa --branch main" > $P/website_1104.wrangler.txt
url=$(grep -o 'https://[a-z0-9]*\.qidk-nasa\.pages\.dev' $P/website_1104.wrangler.txt | tail -1); log "deployed: ${url:-no url}"
sleep 20
for u in "$url/" "https://qidk-nasa.pages.dev/"; do curl -s -m 30 "$u" | grep -q 'Evidence, on request' && log "verify ok: $u" || log "verify FAILED: $u"; done
log "=== done"
