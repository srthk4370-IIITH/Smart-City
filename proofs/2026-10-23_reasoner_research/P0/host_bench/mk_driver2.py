"""driver.sh -> driver2.sh: same logic plus a HEARTBEAT watchdog (owner rule 2026-10-23: GPU jobs die with the session)."""
s = open("driver.sh").read()
a = s.index("stop_ours() {")
b = s.index("start_server() {")
stop = s[a:b]
s = s[:a] + s[b:]
w = s.index("# ---------------------------------------------------------------- RAM watcher")
s = s[:w] + stop + "DRV=$$\n" + s[w:]
s = s.replace("    sleep 30\n  done\n) &", """    hb=$HB/results/HEARTBEAT
    if [ ! -f $hb ] || [ $(( $(date +%s) - $(stat -c %Y $hb) )) -gt 900 ]; then log "HEARTBEAT stale (>15 min): stopping"; stop_ours; kill $DRV; exit 0; fi
    sleep 30
  done
) &""")
s = s.replace("# Unattended P0 host-bench driver (WSL).",
              "# P0 host-bench driver (WSL), run as the session's background task; exits and stops its llama-server when\n"
              "# results/HEARTBEAT is older than 15 min (owner rule 2026-10-23).")
open("driver2.sh", "w").write(s)
