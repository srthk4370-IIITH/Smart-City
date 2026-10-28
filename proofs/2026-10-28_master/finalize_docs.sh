#!/usr/bin/env bash
# Fill the "<<filled from FILE: what>>" markers in ppt.md + teach.md from the overnight status files, then commit + push.
# Standalone (WSL): bash /mnt/c/Users/hp/Desktop/qidk/proofs/detach.sh finalize_docs <this>
# Runs when RSN_V2_RETRY.md AND RAG_STATUS.md exist, or at 10:40 IST, whichever is first. A missing file -> "not deployed / pending".
# Value = the file's "**Result:**" line (else its first non-heading line), max 300 chars. Test mode: FD_TEST_DIR=<dir> (no wait, no git).
R=/mnt/c/Users/hp/Desktop/qidk; M=$R/proofs/2026-10-28_master
GIT="/mnt/c/Program Files/Git/cmd/git.exe"; WR='C:\Users\hp\Desktop\qidk'
log(){ echo "$(date -u +%FT%TZ) $*"; }
if [ -z "$FD_TEST_DIR" ]; then
  exec >> $M/finalize_docs.log 2>&1 < /dev/null
  CUT=$(TZ=Asia/Kolkata date -d "2026-10-29 10:40" +%s)
  log "=== finalize_docs: wait for RSN_V2_RETRY.md + RAG_STATUS.md or 10:40 IST"
  until { [ -s $M/RSN_V2_RETRY.md ] && [ -s $M/RAG_STATUS.md ]; } || [ $(date +%s) -ge $CUT ]; do sleep 60; done
  sleep 30   # let a writer finish the file
  D=$R; S=$M
else D=$FD_TEST_DIR; S=${FD_TEST_STATUS:-$M}; fi
python3 - "$D" "$S" <<'P'
import re, sys, os
d, s = sys.argv[1], sys.argv[2]
def value(f):
    p = os.path.join(s, f)
    if not os.path.isfile(p) or os.path.getsize(p) == 0:
        return f"not deployed / pending ({f} not written)"
    lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
    v = next((l.split("**Result:**", 1)[1] for l in lines if "**Result:**" in l), None)
    if v is None:
        v = next((l for l in lines if l.strip() and not l.lstrip().startswith("#")), "written, no result line")
    v = " ".join(v.replace("|", "/").split())
    return v if len(v) <= 300 else v[:297] + "..."
pat = re.compile(r"<<filled from ([A-Za-z0-9_.]+)[^>]*>>")
for name in ("ppt.md", "teach.md"):
    p = os.path.join(d, name); b = open(p, "rb").read().decode("utf-8"); n = len(pat.findall(b))
    b = pat.sub(lambda m: value(m.group(1)), b); open(p, "wb").write(b.encode("utf-8"))
    print(f"{name}: {n} markers filled")
P
[ -n "$FD_TEST_DIR" ] && exit 0
log "markers filled"
cd $R || exit 1
"$GIT" -C "$WR" add -- ppt.md teach.md
"$GIT" -C "$WR" commit -m "ppt.md, teach.md: fill final-night results (finalize_docs)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- ppt.md teach.md && log "committed"
for i in 1 2 3; do
  "$GIT" -C "$WR" push origin htpd-window-ux && { log "pushed"; break; }
  log "push failed ($i): rebase on origin"; "$GIT" -C "$WR" pull --rebase --autostash origin htpd-window-ux; sleep 30
done
log "=== finalize_docs done"
