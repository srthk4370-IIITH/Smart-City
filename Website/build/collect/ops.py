"""Ops datasets: crashes, reboots, sleeps, thermals, disk, power events, across laptop and QIDK."""
from _lib import *

S = __file__
T = "ops"
RV = PROOFS / "2026-10-17_retrain_v2"

INCIDENTS = [
    # date, machine, what, cause, fix, evidence
    ("2026-10-07", "laptop", "screen black; Windows force-hibernated 21 times during v1 training",
     "critical thermal event, ACPI zone TZ01 at its 100 C limit; training slowed 27 -> 36.8 s/step",
     "GPU thermal guard (pause 83 C / resume 75 C), CPU capped 75%, WSL 9 GB / 8 cores, checkpoints every ~20 steps, auto-restart, GPU 35 W cap",
     "2.1b"),
    ("2026-10-07", "QIDK", "board crashed during a parallel Genie test", "two Genie sessions (~3.7 GB each) exhausted RAM",
     "NPU calls strictly sequential (one session at a time)", "5"),
    ("2026-10-08", "QIDK", "'Safety check rejected' shown after reboot/idle", "HTP refused a new session for seconds (err 1002, DSP memory) and the empty output looked like a policy rejection",
     "Genie retries after 3, 7, 15 s with the same prompt; timeline says 'NPU temporarily unavailable (hardware)'", "4.1"),
    ("2026-10-08", "QIDK", "dates shown as 'Thu 25 Oct 2029'", "RTC boots in 2023; saved laptop offset applied after NTP sync",
     "offset applied only while the device clock is before 2025; incidents ordered by ID", "4.1"),
    ("2026-10-13", "laptop", "WSL would not start (E_UNEXPECTED)", "the NPU export filled C: to 0 bytes",
     "disk_guard.sh free-space floor; wsl --shutdown; diskpart compact vdisk 171.1 -> 41.0 GB", "2.9"),
    ("2026-10-13", "laptop", "export produced a bundle that would not load (err 1002)", "export launched from the w4 checkpoint instead of w4a16",
     "check args.json and the -genie-w4a16- path before trusting an export; checkpoint rebuilt and backed up byte-exact", "2.9"),
    ("2026-10-14", "QIDK", "genied idled at 359% CPU, board 94 C, thermal guard blocked all analysis", "Genie poll=true busy-waits; a daemon never exits",
     "poll off for the daemon: 0% idle CPU, same speed", "2.24"),
    ("2026-10-14", "QIDK", "board rebooted (up 0 min)", "base 3B loaded beside genied's fine-tuned 3B (5.8 GB free was not enough)",
     "never two models resident: port lock, no CLI while genied lives", "2.27"),
    ("2026-10-14", "QIDK", "UI change invisible after APK update", "service worker Cache Storage survives app updates",
     "WebView storage wiped per install; no-cache headers; SW fetches with cache: no-cache", "2.30"),
    ("2026-10-15", "QIDK", "board rebooted during chaos (peak load)", "USB supply brownout: boot reason 'reboot', AC/USB online = false",
     "use the DC adapter for the evaluation; store survives torn writes", "2.34"),
    ("2026-10-15", "QIDK", "board 75 C at idle", "dashboard redesign: 22 px backdrop blurs under 60 fps animations (~220% CPU)",
     "solid bars, 2 fps indicators, 1 Hz sparklines: 5-11% CPU, 43 C", "2.35"),
    ("2026-10-15", "QIDK", "13-agent chaos incident reached 94 C", "the guard only held work between incidents",
     "thermal pacing before each NPU call at >= 88 C (wait <= 15 s for 82 C): chaos peak ~90 C", "2.35"),
    ("2026-10-16", "QIDK", "Android rebooted during GPU tests", "GPU (kgsl) and NPU buffers are unmovable and must fit the 7.26 GB Normal zone; the OOM killer picked system processes",
     "llama.cpp at oom_score_adj 1000, drop_caches + compact_memory before each load, one rung at a time", "2.37"),
    ("2026-10-16", "QIDK", "htpd chaos peaks 95-96 C, guard tripped", "htpd works the NPU harder (batched sweeps)",
     "heatsink/fan for the demo and field; guard queues work", "2.37"),
    ("2026-10-16", "QIDK", "900-window accuracy rerun stopped after 39 windows", "one-off socket stall at 91 C",
     "rerun still to do", "2.37"),
    ("2026-10-17", "laptop", "WSL sessions exited at once (3x)", "Start-Process split the bash -lc command string", "start_v2.sh wrapper", "2.40"),
    ("2026-10-17", "laptop", "Windows down to 0.3-0.7 GB free RAM", "WSL page cache holding model files", "WSL capped; supervisor drops the WSL cache below 2.5 GB free", "2.40"),
    ("2026-10-17", "laptop", "blue screen (BSOD) during training", "bugcheck 0xD1 DRIVER_IRQL_NOT_LESS_OR_EQUAL in vfpext.sys (Hyper-V virtual switch filter used by WSL networking)",
     "WSL networkingMode=none while training; checkpoints every 14 steps; auto-resume at logon", "2.40"),
    ("2026-10-17", "laptop", "training frozen 2.6 h", "thermal sleep (Sleep Reason: Thermal Zone) with the GPU guard at 81 C",
     "GPU pause threshold 81 -> 76 C", "2.40"),
    ("2026-10-17", "laptop", "training supervisor died twice", "it was a child of the assistant's shell", "launched via WMI (Win32_Process Create)", "2.40"),
    ("2026-10-18", "laptop", "training frozen 7.7 h overnight", "lid closed -> Modern Standby froze WSL", "keep the lid open; lid action 'Do nothing' in full mode", "2.40"),
    ("2026-10-18", "laptop", "training ran on battery", "AC unplugged", "battery guard stops cleanly below 40%", "2.40"),
]


def incidents():
    rows = [list(r) for r in INCIDENTS]
    cnt = {}
    for r in INCIDENTS:
        k = (r[1], r[0])
        cnt[k] = cnt.get(k, 0) + 1
    write(T, "ops_incidents", "Every operational incident: crashes, reboots, sleeps, thermals (laptop and QIDK)", "incidents",
          [ser("laptop", [pt(d, c) for (m, d), c in sorted(cnt.items()) if m == "laptop"], "alt"),
           ser("QIDK", [pt(d, c) for (m, d), c in sorted(cnt.items()) if m == "QIDK"], "ours")],
          [hb_section(r[5]) for r in INCIDENTS] + [RV / "RESULTS.md", RV / "power_events.txt", RV / "crash_0xD1_analysis.txt"],
          S, n=len(rows), chart={"type": "timeline"},
          table={"columns": ["date", "machine", "what happened", "cause", "fix", "HANDBOOK section"], "rows": rows},
          claim="Every crash had a plumbing cause, and each now has a guard",
          why="Credibility: the system survives the failures it will meet in the field.")


def power_events():
    pe = text(RV / "power_events.txt")
    evs = []
    for line in pe.splitlines():
        m = re.match(r"(\d\d)-(\d\d)-(\d{4}) (\d\d:\d\d:\d\d)\s+(\d+) (.*)", line.strip())
        if not m:
            continue
        msg = m.group(6)
        kind = ("BSOD (bugcheck)" if "bugcheck" in msg else "unclean reboot" if m.group(5) in ("41", "6008") else
                "thermal sleep" if "Thermal Zone" in msg else "standby: lid" if "Reason: Lid" in msg and "entering" in msg else
                "standby: other" if "entering Modern Standby" in msg else "resume")
        evs.append(pt(f"{m.group(3)}-{m.group(2)}-{m.group(1)}T{m.group(4)}", kind, event_id=int(m.group(5))))
    write(T, "ops_power_events", "Windows power events during retrain v2 (event log)", "events",
          [ser("events", evs, "ref")], [RV / "power_events.txt"], S, n=len(evs), chart={"type": "timeline"},
          notes="Event IDs: 41/6008 unclean shutdown, 1001 bugcheck, 42 sleep, 506/507 Modern Standby enter/exit.")
    sup = text(RV / "supervisor.log.txt")
    drops = {}
    for d in re.findall(r"\[(\d{4}-\d\d-\d\d) [\d:]+\] Windows RAM [\d.]+ GB free: dropped WSL page cache", sup):
        drops[d] = drops.get(d, 0) + 1
    write(T, "ops_ram_guard", "Supervisor RAM guard: WSL page-cache drops per day (Windows < 2.5 GB free)", "drops",
          [ser("cache drops", [pt(d, c) for d, c in sorted(drops.items())], "ours")], [RV / "supervisor.log.txt"], S, chart={"type": "bar"})


def disk_thermal():
    write(T, "ops_disk", "Disk space recoveries", "GB",
          [ser("before", [pt("WSL VHDX compact (2026-10-13)", 171.1), pt("WSL disk compact (2026-10-17)", 138), pt("QIDK free space (cleanup 2026-10-07)", 13), pt("laptop C: free (2026-10-17)", 18)], "alt"),
           ser("after", [pt("WSL VHDX compact (2026-10-13)", 41.0), pt("WSL disk compact (2026-10-17)", 51), pt("QIDK free space (cleanup 2026-10-07)", 33), pt("laptop C: free (2026-10-17)", 105)], "ours")],
          [hb_section("2.9"), hb_section("5"), RV / "RESULTS.md", RV / "admin_cleanup.log.txt"], S, chart={"type": "bar"},
          notes="WSL 2.6.3 disables sparse VHD; diskpart compact vdisk was used instead. The w4a16 export needs ~32 GB swap.")
    write(T, "ops_v1_thermal_fix", "v1 training heat fixes (2026-10-07): measured effect", "-",
          [ser("forced hibernations", [pt("before fixes", 21), pt("after fixes (whole v1 run)", 0)], "ours"),
           ser("v1 run thermal pauses", [pt("pauses", 405), pt("minutes paused", 67.9)], "ref")],
          [hb_section("2.1b"), hb_section("2.7"), TRAIN / "results/agents_20261006_2101/train.log"], S, chart={"type": "bar"},
          notes="Guard test: 5 pauses of 10 s over 6 min (~13% slower), peak 86 C. Windows pagefile had peaked at 13 GB before WSL was capped.")


def main():
    incidents(); power_events(); disk_thermal()


if __name__ == "__main__":
    main()
