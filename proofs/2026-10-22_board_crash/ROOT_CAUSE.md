# QIDK "switched off" incidents, 2026-10-22: root-cause analysis

Status: **analysis only**. Nothing here has been run on the board yet. The read-only commands in section 4
are the next step, and the rules in section 5 apply from now on. Sources are listed in section 7.

## 1. What we know

| # | What was happening when the board dropped | NPU state |
|---|---|---|
| 1 | `adb push` of a 2.8 GB GGUF to /sdcard, then `cp` to /data/local/tmp | the app's htpd_v7 had the v2 model resident; the app was running |
| 2 | on-device `md5sum` of the 2.8 GB GGUF | the app's htpd_v7 was resident; the app was running |
| 3 | starting a second, standalone htpd (older v6 binary) on a different 2.8 GB GGUF | the app had just been force-stopped and htpd_v7 `pkill`ed. Nothing waited for it to exit |
| 4 | some time after the app's htpd_v7 loaded the new 3d GGUF | the app swapped models through `htpd_profile`, which takes the "args changed" path: kill, then start (see 3.1) |

Facts from `collect.log`:
- `uptime` showed `up 0 min`, so the **kernel** restarted, not just Android. A framework (system_server)
  watchdog kill only restarts the Java framework, and kernel uptime keeps counting.
- `sys.boot.reason = ro.boot.bootreason = reboot` every time. AOSP defines `reboot` as the catch-all value
  that "generally means the ramoops state is unknown and the hardware state is unknown" [S1]. **It does not
  rule out a kernel panic, a watchdog bite or a PMIC reset.** bootstat can only refine the reason
  (for example to `kernel_panic,...`) when pstore/ramoops holds the last kernel log, and here
  `/sys/fs/pstore` is empty [S1][S2].
- The `kernel log this boot` section of collect.log is **empty**. `dmesg` was run before `adb root`, so
  it printed nothing. We have no kernel evidence from any boot yet.
- dropbox recorded `SYSTEM_TOMBSTONE` x2 and `SYSTEM_FSCK` at boot time. The RTC resets to 2023 on
  every boot, so the timestamps are meaningless. BootReceiver imports tombstones that were written
  before the reboot, so these two may be from just before the drop. Check what they are (section 4).
- `/data/vendor/ssrdump` holds only a 2024 Bluetooth dump. No CDSP SSR dump has ever been written,
  which fits SSR or ramdumps being disabled for CDSP.
- Counter-evidence:
  - The same htpd_v7 + v2 model ran chaos tests at NSP 93–95 °C, with the thermal guard tripping, and
    did not drop. Heavy steady-state NPU load and heat alone do not reset the board.
  - The 14x1024 layout failed with `ggml-hex: fastrpc_mmap failed`. That gave a user-space SIGABRT
    and a tombstone, not a reboot. Running out of DSP address space inside **one** process is handled
    cleanly.
  - Push to /data plus md5 worked fine with the app stopped and the board cool.

**Common factor:** every drop happened while an NPU process was resident and something disturbed it.
Either a process was being killed or (re)started near another one, or heavy I/O and page-cache churn
ran under a resident 2.8 GB model.

## 2. Relevant platform behaviour (from sources)

- **One Hexagon session (PD) can map about 3.5 GB in total** [S5]. Our layout is 2.8 GB of weights plus
  10x1280 KV and compute buffers. That is close to the limit, which is why 14x1024 already fails
  `fastrpc_mmap` (HANDBOOK 2.12).
- The weights live in rpcmem/dma-buf buffers. These are **unmovable and unreclaimable** while
  mapped. HANDBOOK 2.37 measured that GPU/NPU buffers must fit in the ~7.26 GB Normal zone. Two resident
  3B models made the OOM killer pick **system** processes, and Android rebooted (HANDBOOK 2.27, 2.37;
  seen on 2026-10-07 and 2026-10-14).
- **FastRPC teardown is a remote call.** When a process closes the fastrpc device, which happens on any
  exit including SIGKILL, the kernel sends a "kill PD" request to the DSP. Upstream Qualcomm engineers
  describe this failure chain:
  1. If the DSP does not answer, the request times out and the error is ignored.
  2. The session's SMMU mappings are then removed while the PD is still running.
  3. The DSP's next access causes an SMMU fault, which "leads to a panic".

  They proposed a `BUG_ON` there, and Greg KH rejected it because "it just crashed the machine" [S3][S4].
  In short: **killing an NPU process while its DSP side is busy or unresponsive can panic the kernel.**
- **On Qualcomm SoCs a remote-processor (CDSP/ADSP) crash causes a kernel panic** when recovery or
  coredump is disabled, so that a full RAM dump can be taken. Recovery is set per remoteproc
  (`.../remoteprocN/recovery`) [S6]. Qualcomm's debug guide says SSR is "recommended on commercial
  devices and not during the development phase", and that SSR is disabled to get full dumps [S7].
  This is a dev kit, so a CDSP root-PD crash most likely becomes a full board reset. If download mode is
  off, that reset looks like a plain "reboot", with no tombstone and no pstore. This matches what we saw.
- A crash inside **our** DSP code (user PD) is reported as "Process on cDSP CRASHED" and only kills that
  PD, with no reboot. Example: the llama.cpp v68 bring-up crash in `libggml-htp-*.so` [S8]. A board
  reset needs the root PD, the SMMU or the kernel to fail.
- Other kernel-level reset paths that leave the same "reboot, no pstore" footprint:
  - **Apps watchdog:** if the kernel cannot pet the non-secure watchdog for ~11 s it barks, then bites.
    The TEE then lets the PMIC drop PS_HOLD and the whole system resets [S9].
  - **TSENS (thermal) or PMIC faults** also cause hardware resets [S9].
  - **hung_task / softlockup panics**, if those sysctls are set to 1.
  - **init:** a `critical` native service that crashes more than 4 times in 4 minutes makes init reboot
    the device, by default into the bootloader [S10]. We would see the board sitting in fastboot, so
    this is unlikely here.
- **Two concurrent model loads on the NPU** reboot this board. This was reproduced twice (HANDBOOK 2.27).
  Free RAM beforehand was 5.8 GB, so a free-memory check is not a guard.

## 3. Ranked hypotheses

### H1 (most likely). Our own lifecycle code overlaps two NPU processes
More than one NPU client is briefly resident: a new 2.8 GB model loads while the previous htpd is still
loading or still tearing down. This is the known two-models reboot (2.27/2.37), triggered by our code
paths and not by a deliberate second model. The repo has these concrete windows:

1. **Supervisor double start (`backend/htpdclient.go` `superviseHtpd`).**
   - htpd binds port 8091 only **after** the model has loaded (`htpd.cpp`: `ready` at line ~914,
     `bind` at line ~924).
   - `start()` waits 15 s for `htpdUp()` (a TCP dial). The 15 s tick then calls `start()` again whenever
     the port is still closed. It never checks whether an htpd **process** already exists.
   - Warm loads take 2–5 s (`htpd: ready in 1892–5314 ms` in proofs). A cold load can take much longer:
     a freshly pushed GGUF not yet in page cache, a load right after boot, or a load during heavy I/O
     (cases 1, 2, 4).
   - So the next tick, about 30 s after launch, starts a **second htpd that loads a second 2.8 GB
     model**, and further ticks can start more.
2. **"args changed" swap (case 4).** Changing `htpd_profile` (`model=` line) runs `htpdKill` (SIGKILL).
   The code then waits only until the **port** closes, at most 10 s, and starts the new model about 1 s
   later. A closed port does not mean the process has exited or that its DSP PD and dma-bufs are
   released. The listening socket can close before the fastrpc fd's release finishes.
3. **EdgeService restart (`EdgeService.backendStart`).** It runs `pkill -x genied; pkill -x edge-agent`
   but leaves htpd running. If `healthy()` fails, for example because edge-agent's HTTP server stalls
   under I/O pressure (cases 1, 2), a new edge-agent starts. If the old htpd is not listening at that
   moment (still loading, or wedged before bind), the new supervisor starts a second one.
4. **Scripts.**
   - `htpd_v2.sh start` kills `edge-agent`, `htpd` and `genied` but **not `htpd_v7`** (`pkill -x htpd`
     does not match the comm `htpd_v7`). It then waits a fixed `sleep 2` and launches.
   - Case 3 is this pattern: `pkill` returns immediately, and a second binary loaded a second 2.8 GB
     model right after.
   - Also, `am force-stop` does not stop `edge-agent` or `htpd`. Both are started via adbd (shell uid)
     with `setsid`, so the supervisor can relaunch htpd_v7 after a manual `pkill` unless edge-agent is
     killed first.

Why the board reboots: two resident models (or one resident plus one in teardown) exhaust unmovable
memory, the OOM killer takes system or critical processes, and the kernel or init resets. Or the DSP
fails as in H2.

How it fits: explains cases 3 and 4 directly. It explains 1 and 2 if a supervisor or EdgeService
restart fired during the I/O stall.

### H2 (likely, can combine with H1). Killing htpd while its CDSP PD is busy or unresponsive panics the kernel
`htpdKill` sends **SIGKILL** on every batch or call error and on the 150 s timeout, which is exactly when
the DSP is likely stalled. `pkill` sends SIGTERM, but htpd has no handler, so it dies the same way.
Neither path calls `llama_free` / `llama_backend_free`, so the DSP session is never closed in an orderly
way.

Two documented outcomes:
- the PD-kill times out, mappings are removed under a live PD, an SMMU fault occurs, and the kernel
  panics [S3][S4];
- the CDSP root PD faults, and because recovery is disabled on this dev build the kernel panics [S6][S7].

Opening a new PD and mapping about 3 GB within 1–2 s of that (supervisor restart, `htpd_v2.sh start`)
widens the window. The repo already saw teardown overlap fail on the Genie path: "loading a different
set of context binaries straight after a teardown intermittently fails" (`genie.go`, HANDBOOK 2.20). On
Genie that only gave an error, because Genie unwinds cleanly. A SIGKILLed process cannot.

How it fits: no tombstone, generic `reboot`, empty pstore, and no SSR dump all match. Cases 3 and 4
(kill, then immediate reload) match. Cases 1 and 2 match if the I/O stall pushed a batch past 150 s and
the backend SIGKILLed htpd.

### H3 (plausible for cases 1 and 2). Heavy I/O plus page-cache churn under ~3+ GB of pinned NPU memory leads to a kernel-level stall
A multi-GB push, cp or md5 fills page cache and dirty writeback while about 3 GB is pinned in dma-buf.
Reclaim, compaction and f2fs writeback can then stall tasks in D state for long periods. That leads to:
- a `hung_task` or softlockup panic, if enabled;
- an apps watchdog bark and bite if a CPU spins with IRQs off [S9];
- or lmkd/OOM killing a vendor-critical process (for example pd-mapper, qrtr, rmt_storage or a
  critical HAL), which escalates to a reset.

The existing note "FUSE stalls system_server, the Android watchdog reboots" is **incomplete**. That
watchdog only restarts the framework, and kernel uptime would not reset to 0. A kernel-level reset needs
one of the mechanisms above, or H1/H2 triggered by the stall.

How it fits: this is the only hypothesis that covers case 2 (md5 only) without a process restart. Check
first whether the backend restarted htpd during cases 1 and 2 (the agent.log and htpd.log greps below).

### H4 (lower). Power: PMIC UVLO or OCP
HANDBOOK 2.34 once traced a reboot to a USB brownout. The board now runs on its own wall adapter, and the
cases 1 and 2 load (UFS plus an idle or moderately busy NPU) is far below chaos peak load, which did not
drop the board. To rule this out, read the PMIC PON/reset reason (section 4). A software or watchdog
reset shows a PS_HOLD or warm reset. A power fault shows UVLO, OCP or SMPL.

### H5 (lowest). Thermal (TSENS hardware reset)
Temperatures were modest at the drops. Chaos runs at 95 °C, well past what these events reached, did not
reset the board. Keep this only until the PON log rules it out.

## 4. Evidence to collect next (read-only; run right after the board reconnects, app stopped)

Running `adb root` is required for `dmesg`, debugfs, `/data/tombstones` and `/data/vendor`. Kernel log
lines from early boot roll out of the ring buffer, so collect the kernel lines first.

```sh
A=adb
$A root; $A wait-for-device
# 0) stop everything first (supervisor before daemon), and WAIT for exit
$A shell 'am force-stop com.iiith.smartcityedge; pkill -x edge-agent; for p in $(pgrep "^htpd"); do kill $p; done;
          for i in $(seq 1 60); do pgrep "^htpd" >/dev/null || break; sleep 1; done; pgrep -l "^htpd|genied|edge-agent"; true'

# 1) why the PMIC/bootloader restarted us (PS_HOLD/warm = software or watchdog, UVLO/OCP/SMPL = power, TSENS = thermal)
$A shell 'cat /proc/cmdline | tr " " "\n" | grep -iE "bootreason|reset|dload|ramoops|pstore|minidump"'
$A shell 'dmesg | grep -iE "pon|power.?on reason|power.?off reason|reset reason|warm.?reset|hard.?reset|ps_hold|uvlo|ocp|smpl|s3.?reset|tsens|wdog|watchdog|bark|bite" | head -80'

# 2) remote processors / SSR configuration and state
$A shell 'for r in /sys/class/remoteproc/remoteproc*; do echo "$r name=$(cat $r/name) state=$(cat $r/state) recovery=$(cat $r/recovery 2>/dev/null) coredump=$(cat $r/coredump 2>/dev/null)"; done'
$A shell 'ls /sys/kernel/debug/remoteproc/ 2>/dev/null; for r in /sys/kernel/debug/remoteproc/remoteproc*; do echo "$r recovery=$(cat $r/recovery 2>/dev/null) coredump=$(cat $r/coredump 2>/dev/null)"; done'
$A shell 'for s in /sys/bus/msm_subsys/devices/subsys*; do echo "$s $(cat $s/name) level=$(cat $s/restart_level) crashes=$(cat $s/crash_count 2>/dev/null)"; done 2>/dev/null'   # older kernels only
$A shell 'getprop | grep -iE "ssr|restart_level|ramdump|dload|minidump|crash|boot.reason|logpersist"'
$A shell 'grep -hsE "ssr|restart_level|ramdump|dload" /vendor/etc/init/*.rc /vendor/etc/init/hw/*.rc | head -40'
$A shell 'cat /sys/module/qcom_dload_mode/parameters/download_mode /sys/kernel/dload/dload_mode 2>/dev/null; ls /sys/module | grep -iE "ramoops|pstore|minidump|dload|wdt|watchdog"'

# 3) which panic sources are armed
$A shell 'for f in panic panic_on_oops panic_on_warn hung_task_panic hung_task_timeout_secs softlockup_panic; do echo "$f=$(cat /proc/sys/kernel/$f 2>/dev/null)"; done; echo panic_on_oom=$(cat /proc/sys/vm/panic_on_oom)'

# 4) CDSP / fastrpc / SMMU traces in THIS boot (and any crash that landed before the reset)
$A shell 'dmesg | grep -iE "remoteproc|cdsp|q6v5|fastrpc|adsprpc|smmu|context fault|ssr|subsys|crash detected" | head -80'
$A shell 'logcat -d -b all | grep -iE "adsprpc|fastrpc|cdsp|remote_handle|apps_mem|ssr" | tail -60'
$A shell 'ls -la /data/vendor/ramdump /data/vendor/ssrdump /data/vendor/tombstones 2>/dev/null; ls /sys/class/devcoredump/ 2>/dev/null'
$A shell 'ls /sys/kernel/debug/adsprpc/ 2>/dev/null'   # per-process fastrpc sessions (if exposed); must be empty with htpd stopped

# 5) what the two boot-time tombstones are (may be from just before the reset)
$A shell 'ls -la /data/tombstones/; dumpsys dropbox --print SYSTEM_TOMBSTONE | grep -E "^Cmdline|^pid|Abort message|signal " | tail -20'
$A shell 'dumpsys dropbox --print SYSTEM_BOOT | tail -20; dumpsys dropbox | grep -iE "LAST_KMSG|kernel_panic|SYSTEM_RESTART"'

# 6) did OUR code kill/restart htpd, or start two? htpd.log is appended across restarts; agent.log is truncated at every backend start (see 5.4)
$A shell 'D=/data/local/tmp/smart_city_edge/state; for f in $D/htpd.log.1 $D/htpd.log; do echo "== $f"; grep -nE "htpd: ready|bind/listen|Address already in use|model load failed|fastrpc|context swap failed|llama_model_loader: loaded meta" $f | tail -40; done'
$A shell 'grep -nE "htpd: (killing|started|warm-up)|args changed|batch failed|call failed|thermal" /data/local/tmp/smart_city_edge/state/agent.log | tail -40'
$A shell 'logcat -d | grep -iE "SmartCityEdge|EdgeService|NPU backend start" | tail -30'

# 7) memory picture with exactly one model resident (run again after the app's htpd is up)
$A shell 'grep -E "MemTotal|MemAvailable|Unevictable|Mlocked|Shmem|KReclaimable|DmaBuf" /proc/meminfo; cat /proc/pressure/memory; dmabuf_dump 2>/dev/null | tail -20'
$A shell 'grep -E "^Node|zone|nr_free_pages| min | low | high " /proc/zoneinfo | head -30'
```

How to read the results:
- **H1** is proven by any of these: an `Address already in use` line, two `loaded meta` banners without
  a `ready` between them, `htpd: started` twice within about 30 s, or a `NPU backend start` right before
  the drop.
- **H2** is proven by `htpd: killing pid ...` (batch failed/timeout/args changed) shortly before a drop.
  A `crash detected in cdsp` or `context fault` line (if anything survives) confirms it.
- **H3** gets more likely if `hung_task_panic=1` or `softlockup_panic=1`, or if the PON reason is a
  watchdog bite with no htpd restart logged.
- **H4/H5** are confirmed by a UVLO/OCP/SMPL or TSENS PON reason.

### To catch the next one (the most valuable single step)
The kernel log of the crashing boot is lost because pstore is empty. Capture it off-board instead:
- **During any risky step** (model swap, large transfer, first load of a new GGUF), stream the logs to
  the laptop. Whatever leaves the board before the reset survives:
  `adb logcat -b kernel,crash,system,main -v uptime > proofs/<date>_<step>/live.log` (or
  `adb shell dmesg -w` after `adb root`).
- **logpersist** (userdebug only; this board allows `adb root`):
  `setprop persist.logd.logpersistd.buffer kernel,crash,system,main; setprop persist.logd.logpersistd logcatd`.
  It writes to `/data/misc/logd/` and survives reboots [S11]. The last seconds before a reset may still
  be in the page cache and get lost, so the live laptop stream is the more reliable of the two.

## 5. Safe operating rules (effective now)

1. **One NPU client, always, including during teardown.** Never start htpd, genied or a Genie CLI while
   any other NPU process exists. Check processes (`pgrep '^htpd'`, `pidof genied`), not ports.
2. **Stop order: supervisor first, then daemon, then wait.**
   ```sh
   am force-stop com.iiith.smartcityedge; pkill -x edge-agent          # nothing may relaunch htpd
   for p in $(pgrep '^htpd'); do kill -TERM $p; done                    # all builds: htpd, htpd_v7, ...
   for i in $(seq 1 60); do pgrep '^htpd' >/dev/null || break; sleep 1; done   # wait for EXIT, not port close
   pgrep -l '^htpd|genied' && echo "STILL RUNNING - do not start anything" ; sleep 10   # DSP/dma-buf settle
   ```
   Then clean memory before the next load:
   `sync; echo 3 > /proc/sys/vm/drop_caches; echo 1 > /proc/sys/vm/compact_memory` (root).
3. **Never kill htpd in the middle of a batch** unless it has been unresponsive for a long time. Use
   SIGTERM. Planned change, not done yet: htpd should handle SIGTERM by stopping between ubatches, then
   calling `llama_free`, `llama_model_free` and `llama_backend_free` before exiting, so the DSP session
   is closed and not torn down by the kernel.
4. **Model swaps go through a full stop and start, not the live `htpd_profile` "args changed" path.**
   Stop as in rule 2, edit the profile, then start the app.
5. **No multi-GB I/O while a model is resident.** That means push, cp, md5 and backup self-heal. Stop
   everything (rule 2) first, push to `/data/local/tmp/...part`, check md5, `mv`, drop caches, and only
   then load. This is already the transfer rule; extend it to md5 and any big copy.
6. **After loading a new GGUF**, keep the laptop log stream running for the first 5 minutes and do not
   start a second load of any kind.
7. **Cool start.** Load only when NSP is below about 60 °C and `MemAvailable` is above 7 GB with nothing
   else NPU-related running.
8. Standalone experiments (`htpd_v2.sh`, ladders) keep `oom_score_adj 1000` on htpd, so htpd dies
   before system processes. The app path should do the same.

### Code fixes these rules imply (not made; for the owner to approve)
- `htpdclient.go superviseHtpd`:
  - before `start()`, scan `/proc` for any `htpd*` process (the same check as `htpdKill`) and do not
    start while one exists;
  - after `htpdKill`, wait for the **pid** to disappear (up to 60 s), then wait a further 5–10 s;
  - start the 15 s re-check only after the previous launch has exited or bound its port;
  - set `oom_score_adj=1000` on the child.
  - Optionally, bind the port or take `flock(state/htpd.lock)` in htpd **before** loading the model, so
    "up" means "process exists".
- `htpdKill`: send SIGTERM first, wait about 20 s, and SIGKILL only if the process is still there.
- `EdgeService.backendStart`: do not restart edge-agent while an htpd is loading. Use `>>` (or rotate)
  for `state/agent.log` instead of `>`, because every restart currently erases the pre-reboot evidence.
- `htpd_v2.sh start/stop`: kill `htpd*` (all builds) and wait for exit, not `pkill -x htpd; sleep 2`.

## 6. Should we enable SSR and ramdumps?

**Recommendation:**
1. First run the read-only checks in section 4 to see the current values.
2. Then enable SSR (recovery) for **CDSP**, with ramdumps on, for the remaining development and the
   demo. Use the board's own mechanism, typically `persist.vendor.ssr.restart_level=ALL_ENABLE` (find
   the exact property name in `getprop`/`/vendor/etc/init/hw/*.rc`), or
   `echo enabled > /sys/kernel/debug/remoteproc/remoteprocN/recovery` for the CDSP instance [S6].
3. Reboot once and confirm that `recovery=enabled` reads back.

Why this is reasonable on this dev kit:
- With SSR on, a CDSP root-PD crash restarts only the DSP, in seconds. htpd gets an error, and our
  supervisor restarts it, instead of the whole board resetting. Qualcomm describes SSR as the production
  mode [S7].
- With ramdumps or coredump on, the crash leaves an SSR dump in `/data/vendor/ramdump` or `ssrdump`, or
  `/sys/class/devcoredump/devcdN/data` [S6]. That is the evidence we are missing.
- It is reversible (set the property back, or write `disabled`) and does not touch the
  bootloader or partitions.

Caveats:
- It does **not** help if the reset is H1 OOM, H2 SMMU-fault panic on the apps side, H3 hung task or
  watchdog, or H4/H5 hardware. Do not treat "SSR enabled" as a fix.
- A CDSP dump can be tens to hundreds of MB. Check `/data/vendor/ramdump` after events and delete old
  dumps.
- Do **not** enable download (dload) mode or full RAM dump mode. A panic would then leave the board
  stuck in Qualcomm crash-dump/EDL mode waiting for a host tool, which is worse for an unattended demo.
- Do not change panic sysctls (`hung_task_panic` etc.) to hide resets. Read them only.

## 7. Sources

- [S1] AOSP, Canonical boot reason: https://source.android.com/docs/core/architecture/bootloader/boot-reason
- [S2] Halium docs, reading kernel logs (last_kmsg / pstore console-ramoops): https://docs.halium.org/en/latest/porting/debug-build/dmesg.html
- [S3] LKML, "misc: fastrpc: Trigger a panic using BUG_ON in device release" (PD kill timeout -> SMMU mappings removed under a live PD -> SMMU fault -> panic): https://lkml.rescloud.iu.edu/2407.3/06277.html
- [S4] LKML, review of the above (Greg KH / author reply): https://lkml.iu.edu/hypermail/linux/kernel/2408.0/03964.html
- [S5] llama.cpp Hexagon backend developer doc (PD limited to ~3.5 GB of mappings; NDEV split): https://huggingface.co/OpenTransformer/llama.cpp-prismml/blob/main/docs/backend/snapdragon/developer.md
- [S6] Qualcomm Dragonwing docs, Configure remoteproc subsystems (kernel panic on remoteproc crash when coredump disabled; recovery/coredump nodes; devcoredump): https://dragonwingdocs.qualcomm.com/System/Kernel/configure-the-remoteprocessor-remoteproc-subsystems
- [S7] Qualcomm Dragonwing docs, Debug overview (SSR; disable SSR for full dumps; SSR recommended for commercial, not development): https://dragonwingdocs.qualcomm.com/System/Debug-Subsystem/debug-overview
- [S8] llama.cpp PR #17394 (cDSP user-process crash in libggml-htp, "Process on cDSP CRASHED"): https://github.com/ggml-org/llama.cpp/pull/17394
- [S9] Qualcomm Dragonwing docs, Debug common system issues (NS watchdog bark 11 s -> bite -> TEE -> PS_HOLD system reset; TSENS/PMIC hardware resets): https://dragonwingdocs.qualcomm.com/System/Debug-Subsystem/debug-common-system-issues
- [S10] AOSP init `critical` services (more than 4 crashes in 4 min -> reboot to bootloader): https://android.googlesource.com/platform/system/core/+/9fa02c56c/init/README.md and https://gerrit.omnirom.org/plugins/gitiles/android_system_core/+/45215ae6e5742d9dff5468d744a02013e3efbef7%5E%21
- [S11] AOSP logcatd / logpersist (persist.logd.logpersistd, /data/misc/logd, survives reboot): https://android.googlesource.com/platform/system/logging/+/383804f3
- Repo: HANDBOOK.md 2.12, 2.20, 2.27, 2.34, 2.35, 2.37; `app/backend/htpdclient.go` (`superviseHtpd`, `htpdKill`, `htpdUp`);
  `app/htpd/htpd.cpp` (bind after load, no signal handling); `app/android/.../EdgeService.java` (`backendStart`, `healScript`);
  `training/v2/post/device_eval_v2/htpd_v2.sh`; `app/backend/genie.go` (teardown-overlap gap).
