# QIDK Setup: Every Road We Took, Where Each One Ends, and How to Bring Up a New Board

**Purpose.** This is a field guide for setting up an LLM on a Qualcomm QIDK / Snapdragon 8 Gen 3 class
board from zero, written from a project that actually shipped one (Llama 3.2 3B, fine-tuned, running on
the Hexagon NPU, fully standalone on the board). It records the approaches that were explored, the ones
that failed, **why** they failed, what the error messages actually mean, and the decisions taken at each
fork. The last third is a step-by-step bring-up procedure.

**Audience.** You, on a different QIDK, on a possibly different laptop, with no guarantee that the old
board is attached. Nothing here needs the original device.

**How to read it.** If you want to be running in a day, read §0, then jump to §7 (bring-up) and keep §8
(error → fix) open in another window. Read §2–§6 when something breaks or when someone asks you "why not
llama.cpp?" in a review.

**Honesty markers.** `[verified]` = we observed it directly. `[inferred]` = our best reading of the
evidence, not proven. `[untested]` = plausible, never tried by us. Treat `[inferred]` and `[untested]`
as leads, not facts, and re-verify on your board.

---

## 0. The 60-second version

What worked, after six weeks of detours:

```
Qualcomm AI Hub (cloud compile)  ->  Genie bundle (w4a16 context binaries)
         |                                   |
         | fine-tuned weights                | adb push
         v                                   v
  QLoRA on a 6 GB laptop GPU        /data/local/tmp/genie_bundle/
                                             |
                                    genie-t2t-run-2.50 (runs as the SHELL user)
                                             |
                                    Hexagon NPU (HTP V75) ~19 tok/s
```

The five decisions that mattered:

1. **Use Qualcomm AI Hub to compile, not the local QAIRT SDK.** The local path needs a CUDA box with
   tens of GB of VRAM and 80 GB of RAM+swap for quantisation. AI Hub does it in the cloud for free.
2. **Use the Genie runtime, not raw QNN APIs.** Genie is Qualcomm's ready-made LLM runtime
   (KV cache, sampler, tokenizer, chat template). Raw QNN means writing all of that yourself.
3. **Run the model as the `shell` user, never inside an app sandbox.** On this firmware an
   `untrusted_app` is refused by the DSP service. Shell can open the NPU; apps cannot.
4. **Never run two NPU sessions at once.** It is slower *and* it took the board down once.
5. **Check the tokenizer BOS.** A duplicated `<|begin_of_text|>` cost us 15 accuracy points and looked
   exactly like a quantisation problem.

**Biggest single lesson:** on this platform, most "the model is dumb after quantisation" bugs are
actually *plumbing* bugs — a double BOS token, a sampler left at temperature 0.8, an untied KV cache
encoding, a truncated download. Rule out plumbing before you touch quantisation.

---

## 1. What the board is (so you can tell your board apart from ours)

| Property | Value on our unit | How to check |
|---|---|---|
| SoC | SM8650, Snapdragon 8 Gen 3 | `adb shell getprop ro.board.platform` |
| NPU | Hexagon HTP **V75** | implied by SoC; needed for `dsp_arch` |
| `soc_model` id | **57** | used in `htp_backend_ext_config.json` |
| OS | Android 14, **userdebug** | `getprop ro.build.type` |
| Root | `adb root` works | `ro.debuggable=1` |
| adb auth | **none** (`ro.adb.secure` unset) | no "allow this computer" prompt |
| SELinux | Enforcing | `getprop ro.boot.selinux`, `getenforce` |
| RAM | 11.6 GB total, ~9.2 GB free | `cat /proc/meminfo` |
| `/data` free | 19 GB before cleanup, 33 GB after | `df -h /data` |
| RTC | **boots in 2023** until NTP syncs | `adb shell date` |
| Thermal zones | NPU `nsphvx`/`nsphmx`, skin `skin-msm-therm` | `/sys/class/thermal/thermal_zone*/type` |

**If your board differs**, these are the fields that must change:
- A different SoC → different `soc_model` number and `dsp_arch` (V73 for 8 Gen 2, V79 for 8 Elite). The
  context binaries are **compiled per DSP architecture** and will not load on the wrong one.
- A **user** build instead of userdebug → no `adb root`, so the adb-loopback trick in §6.5 cannot be
  enabled, and you are limited to laptop-attached operation or a properly signed system app.
- adb auth enabled → you must accept the RSA prompt on the device's screen once.

**Record these before you do anything else.** A `device_inventory` dump at hour zero saves hours later:

```bash
adb shell getprop | grep -Ei "board.platform|build.type|debuggable|adb.secure|product.model|build.version"
adb shell "cat /proc/meminfo | head -3; df -h /data; ls /vendor/lib/rfsa/adsp | head"
adb shell "ls /dev/*rpc* 2>/dev/null; getenforce; date"
```

---

## 2. Every approach we explored, and where each one ends

Summary table first; details follow. "Cost" is engineering time to a working LLM, from our experience.

| # | Approach | Result | Cost | Use it when |
|---|---|---|---|---|
| A1 | llama.cpp on CPU | works, slow | hours | smoke test, tiny models, no NPU needed |
| A2 | llama.cpp + GGML_QNN fork | abandoned | days–weeks | research; you need GGUF tooling on NPU |
| A3 | llama.cpp + OpenCL on Adreno GPU | not tried `[untested]` | days | GPU is free and NPU is busy |
| A4 | SNPE (legacy SDK) | not used | — | pre-2023 projects only; superseded by QAIRT |
| A5 | QAIRT/QNN SDK, hand-built context binaries | not used for LLM | 1–3 weeks | custom ops, LoRA adapters, non-LLM models |
| A6 | ONNX Runtime + QNN EP | not used on device | days | ONNX-native stacks, non-LLM |
| A7 | ExecuTorch / MLC-LLM | not tried `[untested]` | days–weeks | PyTorch-native or Vulkan-first teams |
| A8 | **AI Hub → Genie bundle** | **shipped** | 1–3 days | **default choice for an LLM** |
| A9 | Laptop web app + `adb shell` per call | worked, then dropped | hours | first demo, debugging |
| A10 | Go binary on device as shell + PWA | worked | 2–3 days | laptop-free, no APK needed |
| A11 | APK running Genie inside the sandbox | **failed (14001)** | — | only with vendor/system privileges |
| A12 | **APK + local adbd loopback** | **shipped** | 2–3 days | dev kit, laptop-free, needs userdebug |
| A13 | JNI against the Genie C API | deferred `[untested]` | 1–2 weeks | production app, lowest latency |

### A1. llama.cpp on the CPU

**What it is.** Build `llama-cli` for `arm64-v8a` with the Android NDK, push a GGUF file, run it.

**Status.** Artifacts from an early attempt were still on our board months later (`libllama*.so`,
`libggml*.so`, `llama-cli` sitting inside the Genie folder) and were deleted during cleanup `[verified]`.
No performance numbers were ever recorded, which tells you it never became the main path.

**Why it is not the answer here.** Decode speed on a 3B model is bound by memory bandwidth. The CPU
competes with everything else on the board, burns battery, and heats the SoC — and the whole point of a
QIDK is the NPU sitting idle next to it. Our NPU numbers were ~19 tok/s decode and ~1160 tok/s prefill;
CPU inference on the same class of device is typically several times slower for a 3B at 4-bit `[inferred]`.

**Where it *is* the right tool:**
- **Hour-one sanity check.** It is by far the fastest way to prove "a language model runs on this board
  at all" before you have fought a single Qualcomm toolchain. Worth doing on day one.
- **Tiny models** (0.5B–1B) where CPU speed is acceptable.
- **A CPU fallback path** in your app when the NPU is busy or unavailable.
- **Tokenizer/prompt debugging.** `llama-cli` will happily show you exactly how your prompt tokenises,
  which is how you'd catch a double-BOS bug in ten minutes instead of two days (see §4.6).

**How to use it, if you want it:**
```bash
# on the laptop, with NDK installed
cmake -B build-android -DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake \
      -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-28 -DGGML_OPENMP=OFF
cmake --build build-android -j --target llama-cli
adb push build-android/bin/llama-cli model-q4_k_m.gguf /data/local/tmp/
adb shell "cd /data/local/tmp && chmod 755 llama-cli && ./llama-cli -m model-q4_k_m.gguf -p 'hi' -n 32"
```
Keep it in `/data/local/tmp`, not in your Genie folder — ours polluted the Genie directory and made the
later cleanup risky.

### A2. llama.cpp with the QNN/Hexagon backend

**What it is.** Community forks add `-DGGML_QNN=ON`, which offloads GGML ops to the Hexagon NPU through
QNN. Our repo still contains the build scripts for exactly this (`build_android.sh`,
`build_qnn_master.sh`, pointing at an NDK r26d and a local QAIRT 2.50 tree) `[verified]`.

**Status: abandoned with no notes.** The scripts exist, the source trees and the SDK folder they
reference are gone, and there is not a single recorded result. The conversation history shows the
project "oscillating between Genie and GGUF" with no output for days before switching decisively to
Genie `[verified]`.

**Why it fails in practice.**
- The QNN backend in llama.cpp has historically been **partial** — a subset of ops accelerated, the rest
  falling back to CPU, so you inherit the complexity of both worlds and the speed of neither.
- It tracks a moving QNN API across SDK versions; a fork that worked on 2.2x may not build on 2.50.
- GGUF quantisation formats (Q4_K_M and friends) are not what the HTP wants. The HTP wants per-channel
  int4 weights with static activation encodings. Converting between the two is where the accuracy goes.
- You get no KV-cache management, no graph partitioning for prompt vs token phases — which is precisely
  what Genie gives you for free.

**Where it could work `[untested]`:** research into op coverage; a model with no AI Hub recipe where you
already have GGUF tooling; teams who need llama.cpp's sampler/grammar features specifically. Budget
weeks, not days, and expect to read the fork's source.

### A3. llama.cpp with OpenCL on the Adreno GPU `[untested]`

Never attempted here. On paper it is the easiest "accelerated" option — Adreno 750 supports OpenCL,
llama.cpp has an OpenCL backend, and you avoid the whole Qualcomm NN toolchain. Expect something between
CPU and NPU speed, and expect the GPU to fight your UI for cycles. Worth a day if the NPU path stalls.

### A4. SNPE (Snapdragon Neural Processing Engine)

The predecessor to QAIRT. Our board had SNPE benchmark leftovers (`snpe_bench`, `snpebm`,
`snpe_run`, `libSnpeHtpV75Skel.so`) from an earlier project `[verified]`. **Do not start a new project on
SNPE.** QAIRT is the successor and subsumes it; SNPE's LLM story is effectively nonexistent. Mentioned
only so you recognise the files when you find them on a second-hand board.

### A5. QAIRT / QNN SDK directly (hand-built context binaries)

**What it is.** Download the Qualcomm AI Runtime SDK; use `qairt-converter` to turn ONNX into a QNN
graph, `qnn-context-binary-generator` to compile it into a `.bin` for a specific DSP architecture, and
`qnn-net-run` (or your own C++ host) to execute it.

**This is the path you took with Antigravity, and this is where the pain came from.** The specific
problems recorded `[verified]`:

1. **Version matrix hell.** The SDK version you can *download* is not necessarily the version the
   compiler service *accepts*, nor the version on the *device*. The exact error:
   > `QAIRT version 2.42 is not supported by AI Hub Workbench. Available versions are:
   > QAIRT v2.45 | 2.45.0.260326154327, QAIRT v2.49 | ..., QAIRT v2.50 | ... default, latest`

   Meanwhile the locally available SDK zip was **2.43**, and the device runtime ended up being **2.50**.
   You spent a cycle downloading 2.50 to resolve it.
   **The rule:** three versions must be reconciled — (a) the SDK/toolchain you compile with, (b) the
   runtime `.so` libraries you push to the device, (c) the `buildId` baked into the context binary. The
   runtime libs on the device must be **≥** the compile version. We shipped binaries compiled by 2.45
   running on 2.50 device libs with no problem `[verified]`, so forward compatibility holds; backward
   does not.

2. **Converting a 3B LLM to ONNX locally kills the machine.** `optimum.exporters.onnx` on
   Llama 3.2 3B simply printed `Terminated` while loading checkpoint shards `[verified]` — the Linux OOM
   killer. The fp32 ONNX is ~14.4 GB, plus the exporter's working set. AI Hub itself warns:
   > `⚠️ Warning: Insufficient memory — Recommended memory (RAM + swap): 80 GB (currently 9 GB)`

3. **The quantisation step needs a CUDA box.** Qualcomm's own recipe uses AIMET with Sequential MSE,
   documented as wanting ~40 GB of VRAM for a 3B model `[verified from the recipe]`. A 6 GB laptop GPU is
   not in the conversation.

4. **AIMET is Linux-only** and announces it loudly on every import:
   > `Quantized models require the AIMET-ONNX package, which is only supported on Linux.`
   On Windows you are in WSL whether you like it or not.

5. **It gets you a graph, not an LLM.** Even after a successful conversion you have a tensor-in/tensor-out
   context binary. You still need to write: tokenization, the chat template, a KV-cache ring buffer,
   prompt-vs-token graph switching, a sampler, and stop-token handling. That is the work Genie already
   did.

**So why does the SDK exist in your life at all?** Two legitimate reasons:
- **LoRA adapters at runtime.** Genie supports swapping LoRA adapters (`-l`), but **only if the base
  context binaries were compiled LoRA-aware**, using `qairt-converter --lora_weight_list` and
  `qnn-context-binary-generator --adapter_weight_config`. AI Hub does not expose those flags. We asked;
  the answer was that this is outside AI Hub's scope `[verified]`. If you need multiple adapters
  hot-swapped on one loaded base model, **the local SDK is your only road**, and you should budget weeks.
- **Non-LLM models** (vision, audio, classifiers). For those the SDK path is normal, well-trodden and far
  less painful — no 14 GB ONNX, no 80 GB quantisation.

**If you must go local-SDK, the order is:** install SDK → `source bin/envsetup.sh` → convert ONNX →
quantise (needs the CUDA box) → generate context binary for your `dsp_arch` → push with the matching
runtime libs → run `qnn-net-run` with a tiny input to prove the graph loads *before* you write any host
code.

### A6. ONNX Runtime with the QNN Execution Provider

**Status.** We used ONNX Runtime heavily, but **on the host**, as a calibration tool — not on the device
`[verified]`. It replaced AIMET when AIMET ran out of memory (§4.5).

**On-device assessment `[inferred]`.** The QNN EP is a reasonable path for conventional models. For a 3B
LLM it inherits the same problems as A5 (you must still produce a quantised graph, and you must still
hand-roll the LLM loop), with an extra layer of ORT abstraction between you and the HTP. Not recommended
for LLMs; perfectly sensible for a CNN.

### A7. ExecuTorch, MLC-LLM, TFLite `[untested]`

None of these were tried. Noted for completeness and because reviewers ask:
- **ExecuTorch** has a Qualcomm backend and is the most likely future competitor to the AI Hub path for
  PyTorch-native teams. Worth a look if you're starting fresh in 2026+.
- **MLC-LLM** compiles via TVM to Vulkan/OpenCL — i.e. the GPU, not the NPU.
- **TFLite** with the QNN delegate exists; irrelevant for a modern decoder-only LLM.
- We found **MediaPipe/Gemma** (`gemma-3n-E2B-it-int4.task`) and TFLite demo apps left on the board by a
  previous user `[verified]` — further evidence that people do try these, and that boards accumulate junk.

### A8. Qualcomm AI Hub → Genie bundle — **the one that shipped**

**What it is.** AI Hub is Qualcomm's free cloud service. You hand it a model (or just name one from their
catalogue), it compiles — and for LLMs, quantises — on their infrastructure, and hands back the artifacts.
With `--target-runtime genie` the artifacts are a **Genie bundle**: a set of context binaries plus the
configs that Genie's runtime needs.

**Why it won, point by point:**

| Problem | Local SDK | AI Hub |
|---|---|---|
| 14 GB ONNX export | your RAM | their machines |
| Quantisation needing ~40 GB VRAM | your GPU | their GPUs |
| AIMET encodings for Llama | you generate them | **published, pre-computed** |
| Matching the right QAIRT version | you juggle it | pinned by a flag |
| Known-good config for the SoC | you write it | emitted for you |
| Cost | a workstation | free account |

**The decisive advantage** is the third row. Qualcomm publishes the activation encodings for their
catalogue models (for Llama 3.2 3B w4a16: 1,233 weight and 11,711 activation encodings). We **reused
those published encodings with our own fine-tuned weights** `[verified]` — which is the trick that let a
laptop-trained model reach the NPU without ever running the heavyweight calibration ourselves.

**Commands that actually work (2026, qai-hub-models 0.63.0):**
```bash
pip install qai-hub-models==0.63.0
qai-hub configure --api_token <your token from aihub.qualcomm.com>

# stock model, straight to a Genie bundle
qai-hub-models export llama_v3_2_3b_instruct \
  --device "Samsung Galaxy S24 (Family)" \
  --target-runtime genie --skip-profiling --output-dir ./genie_bundle

# your own fine-tuned weights
... --checkpoint /path/to/merged-or-quantised-checkpoint ...
```

**Gotchas we hit `[verified]`:**
- The `qai-hub` CLI has **no `compile` subcommand**. It is `submit-compile-job`, and it takes no
  `--output-dir`. The convenient wrapper is `qai-hub-models export`, a different package. We burned
  several cycles on `qai-hub: error: argument command: invalid choice: 'compile'`.
- `hub.upload_model(<HF folder>)` fails: *"Model directory must contain exactly one .onnx file."* AI Hub
  does not accept a Hugging Face checkpoint folder directly for this path; use `qai-hub-models export`,
  which handles the export for you.
- **Llama is a gated model.** Accept the licence on Hugging Face and export `HF_TOKEN`, or you get a 401
  that looks like an AI Hub problem but is not.
- The default target runtime is `geniex_qairt`, which does **not** emit a `genie_config.json`. Pass
  `--target-runtime genie` explicitly.
- Our SoC (8 Gen 3) has been quietly dropped from the published `supported_chipsets` list, but the export
  still works — nothing enforces the list `[verified]`. Compile for "Samsung Galaxy S24 (Family)", which
  is the same silicon.
- **Uploads are the bottleneck**: ~14 GB at ~1.3 MB/s, with each S3 connection capped around 30–40 KB/s.
  We patched boto3's transfer config to 16 concurrent 64 MB parts via a `sitecustomize.py` hook; that
  turned a day into a few hours `[verified]`.
- **Verify every downloaded part.** One of ours arrived truncated — 561 MB of an expected 901 MB file.
  It was a clean byte-prefix, so nothing complained until Genie failed. Each context binary's header
  carries `[u64 header_size][u64 blob_size]`; the sum must equal the file size. Write `SHA256SUMS.txt`
  immediately after a good download and check it on every later copy `[verified]`.

**What a Genie bundle contains:**
```
llama_v3_2_3b_instruct_part_1_of_3.bin   # context binaries (prompt + token graphs)
llama_v3_2_3b_instruct_part_2_of_3.bin
llama_v3_2_3b_instruct_part_3_of_3.bin
tokenizer.json
genie_config.json                        # dialog/engine/sampler config
htp_backend_ext_config.json              # {"soc_model":57,"dsp_arch":"v75", ...}
```
The runtime itself (`genie-t2t-run`, `libGenie.so`, `libQnn*.so`, the V75 skels) comes from the **QAIRT
SDK**, not from AI Hub. This is the one place you genuinely need the SDK download — see §7.3.

### A9. Laptop web app driving `adb shell` per request

**What it was.** A FastAPI app in WSL. For each request it wrote the prompt to the device, ran
`genie-t2t-run` over `adb shell`, and parsed stdout.

**Good for:** the first demo, and for debugging — you see the raw Genie output on your own screen.

**Why we moved on:**
- **Not actually edge.** Unplug the laptop and the demo dies.
- **Every call is cold.** `~4 s` of HTP initialisation per call, which dominated everything. The attempt
  to keep the dialog warm with Genie's `-s` save-state flag failed with **error 14001** — the FastRPC
  context does not survive crossing process boundaries that way `[verified]`. Latency sat at 25–29 s for
  a multi-agent turn, and the only real fix was architectural: collapse four model calls into one,
  which took it to ~7 s.
- **WSL cannot see USB.** `adb` inside WSL finds no device; you must call the **Windows** `adb.exe`. We
  lost a working demo for an hour when a repo restructure moved `platform-tools` and the code silently
  fell back to WSL's own `adb` `[verified]`.

### A10. Native Go binary on the device (shell user) + PWA

**What it was.** Cross-compile a single static Go binary (`GOOS=linux GOARCH=arm64`), push it to
`/data/local/tmp`, start it detached with `setsid nohup`, serve a dashboard on `127.0.0.1:8000`, and open
it in the device's Chrome as a PWA.

**This works and is laptop-free** `[verified]` — the process survives unplugging USB. It is the lowest-
effort way to get a genuinely standalone demo, because a shell-user process **can** open the NPU.

**Limits:** it is not an app. There is no icon, no notifications, nothing restarts it after a reboot, and
"open Chrome and type an address" is a weak demo. That is what pushed us to A12.

### A11. An APK that runs Genie inside the app sandbox — **this fails**

**The single most expensive dead end, so understand it properly.**

Attempt: package `genie-t2t-run` as a native lib inside the APK, copy the model into the app's private
storage, set `ADSP_LIBRARY_PATH` to the app's own directory, and run it in-process.

The error:
```
[ERROR] "Failed to create device: 14001"
[ERROR] "Device Creation failure"
```
With logcat showing the real story:
```
remote_handle_control_domain failed for request ID 2 on domain 3 (errno Permission denied)
open_device_node: no access to default device of domain 3, open thru HAL
open_device_node failed
```

**Root cause `[verified by elimination]`.** An `untrusted_app` is refused a cDSP session by the vendor's
`dspservice`. Critically: **this is not SELinux.** We set the device to permissive (`setenforce 0`) and
got the identical 14001 `[verified]`. We also confirmed `libcdsprpc.so` is in
`/vendor/etc/public.libraries.txt`, so it is not a library-loading problem, and that `/dev/adsprpc-smd`
is `system:system 0664` with no `/dev/fastrpc*` node for apps to use. The vendor HAL simply does not
serve app UIDs on this firmware.

**Two secondary traps found on the way:**
- **Go binaries die under the app's seccomp filter** with `SIGSYS: bad system call` inside
  `syscall.faccessat2`, reached from `os/exec.LookPath`. Android's app seccomp policy kills
  `faccessat2`, which Go uses to resolve a **bare command name**. Fix: always exec by absolute path
  (`/system/bin/getprop`, never `getprop`) `[verified]`.
- **Name collisions between ARM and DSP libraries.** `libQnnSystem.so` and
  `libQnnHtpNetRunExtensions.so` exist in *both* the aarch64 and the Hexagon sets. Flattening them into
  one APK lib directory silently breaks things. Keep them in separate directories and point
  `LD_LIBRARY_PATH` and `ADSP_LIBRARY_PATH` at the right one each `[verified]`.

**When this approach *would* work `[inferred]`:** if your app is signed with the platform key and
installed as a system/privileged app, or if the vendor ships an NPU HAL/service that accepts app clients,
or on a board whose firmware has a more permissive `dspservice` policy. **Test this on day one of any new
board** — it changes your whole architecture. The test is in §7.6.

### A12. APK + local adbd loopback — **what shipped**

**The idea.** Android will not let the app touch the NPU, but it *will* let the `shell` user. The `shell`
user is reachable from inside the device itself, through the board's own adb daemon listening on
`127.0.0.1:5555`. So the app speaks the adb wire protocol to its own device, and asks adbd to start the
real backend as `shell`. Same technique as Shizuku and LADB.

```
APK (untrusted_app, no NPU)
  └── foreground service
        └── TCP 127.0.0.1:5555  ──►  adbd (system)
                                        └── starts edge-agent as uid shell
                                              └── genie-t2t-run ──► NPU ✓
        └── WebView ──► http://127.0.0.1:8000 (served by that backend)
```

**One-time enable (needs userdebug + root):**
```bash
adb root
adb shell setprop persist.adb.tcp.port 5555
adb unroot      # IMPORTANT: go back to a normal shell afterwards
```
Note: `setprop persist.adb.tcp.port` **fails silently as plain shell** — "Failed to set property". It
must be done while adbd is root. The `persist.` prefix makes it survive reboots `[verified]`.

**Properties that make this work and what to watch:**
- Our board has **no adb authentication**, so the app's handshake is trivial. On a board with auth, the
  app must present a key the device has already accepted — materially harder.
- **Restarting adbd kills everything it started.** `adb root` / `adb unroot` during development will take
  your backend down with adbd's cgroup; a supervisor loop should restart it (ours does, in ~6 s)
  `[verified]`.
- **Security: this opens an unauthenticated root-capable shell on TCP 5555.** If the board joins Wi-Fi,
  anyone on that network has your device. Ours ended up on a campus network at `10.248.245.x` before we
  noticed `[verified]`. Keep the board off shared networks, or firewall 5555 to loopback, or turn it off
  when not demoing. Revert with `adb root; adb shell setprop persist.adb.tcp.port ""; adb unroot`.
- Build the APK **without Gradle** if you want speed and reproducibility: `aapt2` → `javac` (JDK 17) →
  `d8` → `zip` → `zipalign` → `apksigner`, using only `build-tools` and `platform-34`. Ours is a 40-line
  shell script. Two traps: `aapt2 -R` rejects an overlay that doesn't override anything (pass `res.zip`
  positionally instead), and you need the `zip` binary installed `[verified]`.

### A13. JNI against the Genie C API `[untested]`

The "proper" version of A12: link `libGenie.so` into your app and call it through JNI, keeping the model
loaded between calls (saves the ~0.7 s init per call). **We deferred it, and on this firmware it would
not have helped anyway** — the sandbox cannot open the NPU regardless of whether you call Genie via CLI
or via its C API (A11). It only becomes attractive on a board where apps *can* reach the DSP.

---

## 3. How the pieces fit on the device

Knowing the layout prevents most "it can't find the library" errors.

```
/data/local/tmp/genie_bundle/
├── genie-t2t-run-2.50              # the runner (from the QAIRT SDK), chmod 755
├── *.bin                           # context binaries (from AI Hub)
├── tokenizer.json
├── smartcity_agent.json            # your Genie config (sampler, token limits)
├── htp_backend_ext_config.json     # {"soc_model":57,"dsp_arch":"v75",...}
├── qairt_2_50_libs/                # ARM64 libs, found via LD_LIBRARY_PATH
│   ├── libGenie.so
│   ├── libQnnHtp.so
│   ├── libQnnHtpNetRunExtensions.so
│   ├── libQnnHtpV75Stub.so         # the "stub" is the ARM side
│   └── libQnnSystem.so
└── dsp_2_50/                       # Hexagon libs, found via ADSP_LIBRARY_PATH
    ├── libQnnHtpV75Skel.so         # the "skel" is the DSP side
    └── ...
```

Every call needs both paths set, and **`ADSP_LIBRARY_PATH` is semicolon-separated** (not colon — this
catches everyone):

```bash
cd /data/local/tmp/genie_bundle
LD_LIBRARY_PATH=$PWD/qairt_2_50_libs \
ADSP_LIBRARY_PATH="$PWD/dsp_2_50;/vendor/dsp/cdsp;/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp" \
./genie-t2t-run-2.50 -c smartcity_agent.json --prompt_file /data/local/tmp/p.txt
```

**Stub vs skel.** `...V75Stub.so` runs on the ARM cores and marshals calls; `...V75Skel.so` runs on the
Hexagon DSP and does the work. Missing the skel path is the single most common cause of a device-creation
failure. If you ever want to prove which files are really in use, run a call and read
`/proc/<pid>/maps` — that is how we decided what was safe to delete during cleanup `[verified]`.

---

## 4. Model export and quantisation: what actually goes wrong

### 4.1 The accuracy cliff, and the real reasons for it

Our numbers, same weights, measured on the same held-out windows `[verified]`:

| Stage | Pattern accuracy |
|---|---|
| Host, bf16 (ceiling) | 91.3 % |
| Host, 4-bit NF4 (what training reported) | ~94 % |
| **First device run** | **54.3 %** |
| After GPTQ weights | 67.4 % |
| **After fixing the double BOS** | **82.6 %** |
| Final, larger test set | **85.2 %** |

Read that table again: **the largest single jump came from deleting one token from the prompt**, not from
anything to do with quantisation. The second largest came from using a proper quantisation algorithm.

### 4.2 Host 4-bit ≠ device 4-bit

The misconception that cost us the most time: "it scores 94 % at 4 bits on my laptop, so 4 bits is fine."
Laptop NF4 uses **block-wise scales (block size 64)**. The HTP uses **per-channel int4** — roughly 3×
coarser. They are not the same number of bits in any meaningful sense. Validate with a host fake-quant
that mimics *the device's* scheme before you blame the runtime.

### 4.3 Use GPTQ, not naive round-to-nearest

Converting weights straight to per-channel int4 was poor. **GPTQ** (error-compensating, per-channel
symmetric int4, act-order, calibrated on ~128 samples of *your own* prompts) took the host fake-quant
from ~74 % to 89 % `[verified]`. Verify the integers land exactly on the grid — ours reproduced with
0 mismatches across 1,232 tensors — and write exact scales into the encodings.

**What did not work:** MSE-clipped weight scales made things *worse* (39 %) `[verified]`. Clipping
removes the rare large weights that LLMs depend on. Do not reach for it reflexively.

### 4.4 Precision choices on this SoC

- **w4a16** (int4 weights, int16 activations): **works on 8 Gen 3.** This is what to use.
- **w4** (int4 weights, fp16 activations): compiles fine, **does not load on 8 Gen 3** — fails with
  `err 1002` on context 2, or `err 5005` on the async path. Qualcomm's performance tables list it only
  for 8 Elite / X Elite `[verified]`. Do not burn a day on this like we did.
- **w8a16**: not supported for this model.

Note also: Qualcomm's "a16" means **int16 with static encodings**, not fp16. Mis-reading this sends you
looking for precision bugs that aren't there.

### 4.5 Calibration without a workstation

AIMET's QuantSim for a 3B model wants more than 30 GB of RAM. On Kaggle (30 GB hard cap, **no swap**) it
dies at ~7 minutes with exit 137 / `Killed` `[verified]`. Colab/Kaggle cgroups will not let you swap your
way out.

What worked instead: a **lean ONNX Runtime min/max calibrator** reimplementing AIMET's delta/offset
formula, sharded across 4 parallel Kaggle jobs over ~149k tokens `[verified]`:
```
asymmetric: delta = (max - min) / (2^bw - 1);  offset = round(min / delta)
symmetric:  delta = max / floor(steps/2);      offset = -pos - 1
```
Two traps: ORT's `BASIC` graph optimisation was too slow (use `ENABLE_ALL`), and Kaggle auto-selects a
T4 which then OOMs — force CPU with `CUDA_VISIBLE_DEVICES=""`.

**Was it worth it?** Honestly: no. Our recalibrated ranges only *matched* Qualcomm's published ranges once
the BOS bug was fixed, so we shipped the published ones `[verified]`. **Start by reusing the published
encodings.** Only calibrate if you can prove they are the bottleneck.

### 4.6 The double-BOS bug — check this first, always

**Genie prepends `<|begin_of_text|>` itself.** Our prompts also carried one, to stay byte-identical to
training. Result: every single inference saw a token sequence the model had never seen in training.

Detection is trivial once you think of it: Genie's profile output reported **607 tokens** where the host
tokenizer said **606** `[verified]`. One token.

Fix: `strings.TrimPrefix(prompt, "<|begin_of_text|>")` before writing the prompt file.
Effect: **67 % → 82.6 %**.

**Generalise this.** Before you suspect quantisation, prove that the exact token IDs the device sees
match the exact token IDs the host sees. Dump both. Compare lengths, then compare contents.

### 4.7 The sampler will silently ruin your evaluation

AI Hub's exported `genie_config.json` ships with `temp 0.8, top-k 40` — **random sampling**. Every
benchmark run gives a different answer, caching is impossible, and accuracy numbers are noise. Force
greedy decoding (`temp 0`, `top-k 1`) for anything you intend to measure `[verified]`.

### 4.8 KV-cache encodings must be tied

If you generate your own encodings, Genie refuses the model at load time:
```
[ERROR] "Model Validation Errors found"
[ERROR] "token_ar1_cl4096_2_of_3 : past_key_10_in - Non-identical quantization parameters
         found for the same tensor"
```
**Genie requires each layer's KV-cache input and output to share one quantisation range.** Tie all of
them (56 pairs for this model) in your merge step `[verified]`.

### 4.9 Other export-time facts worth knowing

- Runtime **LoRA swapping is impossible** with AI Hub bundles (see A5). Merge your adapter into the
  weights before export.
- The rope scaling `factor` must match the model (32.0 for Llama 3.2, not 8.0). We had a hand-written
  config carrying the wrong value for a while `[verified]`.
- Context length is compiled in (ours: 4096). If your prompts are ~1.5k tokens, re-exporting at 2048 is
  an estimated 5–10 % speedup `[inferred]`.
- Never work under `/mnt/c` in WSL — it is painfully slow. Keep checkpoints in the Linux filesystem.

---

## 5. Runtime problems on the device

### 5.1 `err 1002` — "Could not create context from binary"

```
[INFO]  "Using create From Binary"
[INFO]  "Allocated total size = 270369280 across 5 buffers"
[ERROR] "Could not create context from binary for context index = 2 : err 1002"
[ERROR] "Create From Binary FAILED!"
[ERROR] "Failed to free device: 14003"
```

This is a **DSP-side allocation/creation failure**, and it has three distinct causes we identified:

1. **Unsupported precision for the SoC** (e.g. a w4 bundle on 8 Gen 3). Permanent — no retry helps.
2. **Switching between two large bundles.** Loading a different set of context binaries immediately after
   tearing one down fails intermittently. Fix: keep a ≥2.5 s gap on a bundle switch, or better, use **one
   bundle for everything** `[verified]`.
3. **Transient, after a reboot or a long idle.** Reproduced ~40 s after boot. `dmesg` shows
   `adsprpc ... fastrpc_wait_for_completion: poll mode timeout`. It clears on its own within ~10 s.

For cause 3, **one short retry is not enough** — ours retried once after 4 s, that failed too, and the
empty output got misreported to the user as a *model safety rejection*, which sent us debugging the wrong
subsystem entirely. Correct handling:
- Retry with backoff (we use 3 s, 7 s, 15 s) using the identical prompt and model, so results are
  unchanged.
- Re-run the failed unit of work at the end of the batch, when the NPU has recovered.
- **Report hardware failure as hardware failure.** Never let an empty model output be classified as a
  content/validation failure. This is a design rule, not a bug fix.

### 5.2 `14001` — "Failed to create device"

You cannot open the DSP at all. Two causes seen:
- **Wrong UID** (running inside an app sandbox) — see A11. This is the common one.
- **Trying to serialise/restore a Genie dialog across processes** with `-s` over adb — the FastRPC
  context cannot cross that boundary `[verified]`.

Note: an old document of ours claimed 14001 means "`/data/local/tmp` was wiped on reboot". **That is
wrong** — `/data/local/tmp` persists across normal reboots on this board `[verified]`. Don't chase it.

### 5.3 Never run two NPU sessions in parallel

We measured this properly `[verified]`:

| Mode | Wall time | Notes |
|---|---|---|
| Sequential, back-to-back | 33.8 s | second call ran at **9.4** tok/s — it overlapped the first's teardown |
| **Sequential, 0.6 s gap** | **23.6 s** | both at ~19 tok/s |
| Parallel | 76.5 s | second waited ~54 s just to initialise; first dropped to 4.9 tok/s |

And on the first parallel attempt the **board went down and had to be physically replugged**. Each Genie
session holds ~3.2–3.7 GB RSS; two of them pushed `MemAvailable` from 9.2 GB to 3.3 GB and the kernel
killed one.

**Rules:** one NPU call at a time, enforced by a mutex; insert a ~0.6 s gap after a session exits so the
HTP finishes tearing down; parallelise only CPU work. When you stop generation early, send **SIGINT
first** so Genie releases the HTP cleanly, and only `SIGKILL` if it hasn't exited in ~1.5 s.

### 5.4 Thermal

The NPU junction hit **94 °C** during a long test session `[verified]`. Build a guard in: defer
background work above ~88 °C NPU or ~60 °C skin, and make benchmark runs wait for a cold start
(< 80 °C) or your numbers will drift downward through the session.

### 5.5 The clock

The RTC boots in 2023 until NTP syncs. If you compensate with a fixed offset captured at install time,
**you must make it conditional** — once Wi-Fi corrects the clock, adding the offset again put our
timestamps in **2029** `[verified]`. Apply the offset only while the device year is implausible.

### 5.6 Second-hand boards are full of junk

Ours arrived (or accumulated) with: SNPE benchmark suites, YOLO/HRNet models, a MediaPipe Gemma task
file, 16 third-party apps including Termux and an app store, llama.cpp binaries *inside* the Genie folder,
and a `part_2_of_3.bad.bin`. Reclaiming it took `/data` from 13 GB to 33 GB free `[verified]`.

**Safe cleanup method:** run one real inference, read `/proc/<pid>/maps` to list every file actually
mapped, move everything else to a `_trash` directory, re-run the inference to prove it still works, then
delete. Some vendor libs are root-owned and will refuse to move — leave them.

---

## 6. Host-side problems (these cost us more hours than the board did)

- **WSL cannot see USB.** Always call the Windows `adb.exe`, including from inside WSL
  (`/mnt/c/.../platform-tools/adb.exe`). Hard-code one path and check it on startup.
- **`adb` daemon failures.** `could not read ok from ADB Server` / `failed to start daemon` → kill every
  `adb.exe`, `adb kill-server`, `adb start-server`. Two adb binaries of different versions fighting over
  port 5037 is the usual cause.
- **PowerShell does not expand globs for adb.** `adb push models\bundle\* /dest/` fails with
  `cannot stat`. Use `Get-ChildItem ... | ForEach-Object { adb push $_.FullName /dest/ }`, or push the
  directory. Ours silently pushed two 1-byte files and then `chmod` failed on a binary that was never
  there `[verified]`.
- **PowerShell treats native stderr as fatal** under `$ErrorActionPreference="Stop"`. `javac`'s
  deprecation notice and `am start`'s "Activity not started, already running" both killed our install
  script. Switch to `"Continue"` around native calls.
- **Laptop thermal shutdown during training.** Windows force-hibernated ours **21 times** for a critical
  thermal event (ACPI zone at its 100 °C limit) `[verified]`. Mitigations that worked: a GPU temperature
  guard that pauses training at ~83 °C and resumes at ~75 °C, capping CPU to 75 % on AC, checkpointing
  every ~20 steps with auto-resume, and disabling sleep/hibernate timeouts. Note that laptop GPU power
  limits are often **VBIOS-locked** (`Changing power management limit is not supported`) — use fan
  profiles instead.
- **WSL memory vs Windows memory.** Giving WSL 12 of 15.6 GB drove the Windows pagefile to 13 GB and made
  everything unstable. 9 GB with `autoMemoryReclaim` was the sweet spot. After editing `.wslconfig` you
  must `wsl --shutdown` for it to apply.
- **Disk.** The export needs ~30 GB of temp plus ~14 GB of intermediates. Our C: drive hit 5 GB free. WSL
  does not return freed space to Windows until you compact the VHDX (`wsl --shutdown`, then `diskpart` →
  `select vdisk file="...\ext4.vhdx"` → `compact vdisk`, as admin). **Keep ≥ 50 GB free.**
- **CRLF.** Editing `.sh` files with Windows tools breaks them inside WSL. Normalise with `sed -i 's/\r$//'`.
- **Git Bash path mangling.** It rewrites `/data/local/tmp/...` into a Windows path on the way to adb.
  Prefix with `MSYS_NO_PATHCONV=1`, or use PowerShell.

---

## 7. Bringing up a new QIDK, step by step

Assumes: a new board, a Windows laptop with WSL2 Ubuntu, nothing set up yet.

### 7.0 Before you touch the board — decide your target

Answer these three questions first; they determine everything downstream.
1. **What model and size?** If it is in the AI Hub catalogue (Llama 3.2 1B/3B, Qwen, Phi variants), you
   are on the easy path. If not, budget weeks and read A5.
2. **Does it need to run with the laptop detached?** If no, stop after §7.5 — you are done in a day.
3. **Does it need to be an installed app?** If yes, run the probe in §7.6 **first**, because the answer
   changes your architecture.

### 7.1 Physical connection and adb (allow 30 minutes)

1. Install **one** copy of platform-tools and use only that one. Note its absolute path.
2. Connect USB. Prefer a rear/direct port over a hub; our board dropped off the bus twice mid-transfer
   on a long cable `[verified]`.
3. On Windows, if the device does not appear in Device Manager, install the Qualcomm/Google USB driver.
4. ```powershell
   C:\path\to\platform-tools\adb.exe kill-server
   C:\path\to\platform-tools\adb.exe devices
   ```
   Expect `<serial>  device`.
   - `unauthorized` → unlock the screen, accept the RSA prompt ("always allow"). Our board never asked,
     because adb auth was disabled; yours may.
   - `no devices` → different cable, different port, check Device Manager.
   - `could not read ok from ADB Server` → kill stray `adb.exe` processes; you have two versions
     fighting.
   - Appears then vanishes → power. Use the supplied adapter, not bus power.
5. **Record the inventory** (the three commands in §1) into a file. Do it now, not later.

### 7.2 Decide root/userdebug now

```bash
adb shell getprop ro.build.type      # expect: userdebug
adb root                             # expect: "restarting adbd as root"
adb unroot
```
If `adb root` is refused, you are on a user build: the loopback trick (§7.7) is unavailable, and you
should plan for laptop-attached operation or a platform-signed app.

### 7.3 Get the QAIRT runtime onto the board (allow 1–2 hours)

You need the **QAIRT SDK** only for the runtime files. Download it from Qualcomm's developer site
(account required). Pick a version **≥** the one you will compile with; we ran 2.50 on the device.

From the SDK, you need exactly these on the device:
```
bin/aarch64-android/genie-t2t-run          -> genie-t2t-run-2.50
lib/aarch64-android/libGenie.so
lib/aarch64-android/libQnnHtp.so
lib/aarch64-android/libQnnHtpNetRunExtensions.so
lib/aarch64-android/libQnnHtpV75Stub.so     # match YOUR dsp arch
lib/aarch64-android/libQnnSystem.so
lib/hexagon-v75/unsigned/libQnnHtpV75Skel.so   # and siblings
```
Push them into the layout in §3 and `chmod 755` the runner. If your SoC is not V75, substitute the
matching stub/skel pair — this is the number-one cause of a dead bring-up.

**Prove the runtime works before you involve a model.** If `genie-t2t-run` runs and complains about a
missing config rather than a missing library, your library paths are right.

### 7.4 Get a model bundle (allow 2 hours – 1 day, mostly upload time)

```bash
# in WSL
python3.11 -m venv ~/venvs/qaihm && source ~/venvs/qaihm/bin/activate
pip install qai-hub-models==0.63.0
qai-hub configure --api_token <token from aihub.qualcomm.com>
export HF_TOKEN=<your hf token>     # Llama is gated; accept the licence on HF first

qai-hub-models export llama_v3_2_3b_instruct \
  --device "Samsung Galaxy S24 (Family)" \
  --target-runtime genie --skip-profiling \
  --output-dir ~/genie_bundle
```
Then:
1. **Verify sizes and hashes** of every `.bin`. Write `SHA256SUMS.txt`.
2. Push everything to `/data/local/tmp/genie_bundle/`.
3. Check `htp_backend_ext_config.json` names **your** `soc_model` and `dsp_arch`.

Do not skip step 1. A truncated part fails later with an error that looks like a runtime bug.

### 7.5 First inference — the moment of truth

```bash
adb shell "printf '<|start_header_id|>user<|end_header_id|>\n\nSay OK.<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n' > /data/local/tmp/p.txt"

adb shell "cd /data/local/tmp/genie_bundle && \
  LD_LIBRARY_PATH=\$PWD/qairt_2_50_libs \
  ADSP_LIBRARY_PATH=\"\$PWD/dsp_2_50;/vendor/dsp/cdsp;/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp\" \
  ./genie-t2t-run-2.50 -c genie_config.json --prompt_file /data/local/tmp/p.txt"
```
Expect `[BEGIN]: ... [END]`. If instead you get:
- `Failed to create device: 14001` → wrong UID (are you in an app?) or missing DSP libs → §5.2
- `Could not create context from binary ... err 1002` → §5.1; check precision first, then retry
- missing-library errors → your two `*_LIBRARY_PATH` values; remember **semicolons** for ADSP

**Then immediately, before anything else:** run with `--profile`, and compare the reported prompt token
count against your host tokenizer's count for the same string. If they differ by one, you have the
double-BOS bug (§4.6). Catching it here saves days.

### 7.6 Probe whether apps can use the NPU on *your* firmware (30 minutes, do it early)

This one test determines your architecture. Build a trivial APK that execs `genie-t2t-run` from its own
`nativeLibraryDir`, or simply run as an app UID:
```bash
adb shell run-as <your.package> ./lib/genie-t2t-run -c config.json --prompt_file p.txt
```
- **If it works** → you can ship a normal app (A11/A13). Lucky you.
- **If you get 14001 with `open_device_node ... Permission denied` in logcat** → same firmware policy as
  ours. Go to §7.7. Don't spend a week trying to defeat it; we tried permissive SELinux and it changed
  nothing.

### 7.7 Laptop-free operation (allow 2–3 days)

Simplest (A10): push a self-contained binary, start it with `setsid nohup`, serve a local UI. Done in an
afternoon. Survives USB unplug; does not survive reboot.

Full app (A12):
```bash
adb root && adb shell setprop persist.adb.tcp.port 5555 && adb unroot
```
then an APK that (a) runs a foreground service with a wakelock, (b) speaks adb to `127.0.0.1:5555` to
start the real backend as `shell`, (c) shows a WebView of the local UI, (d) restarts the backend on boot
and when health checks fail. Add device-admin if the board will be out of your hands, and a self-heal
copy of the model files in app storage.

**Re-read the security note in A12 before leaving the board on any network.**

### 7.8 Make it reproducible

Write a single restore script that: checks hashes → pushes the runtime → pushes the model → runs a
"Say OK" smoke test → installs the app. Ours restores a wiped board in one command, and it is the only
reason losing the board for a week would not have been fatal. Do this before you need it.

---

## 8. Error → cause → fix (keep this open)

| Error | Where | Likely cause | Fix |
|---|---|---|---|
| `Failed to create device: 14001` | Genie | app UID cannot open cDSP | run as `shell` (§A12); it is **not** SELinux |
| `Failed to create device: 14001` | Genie `-s` | dialog state can't cross processes | don't use save/restore over adb |
| `Could not create context ... err 1002` | Genie | unsupported precision (w4) | use **w4a16** |
| same, after boot/idle | Genie | transient DSP alloc | retry 3 s / 7 s / 15 s |
| same, when switching models | Genie | overlapping teardown | one bundle, or ≥2.5 s gap |
| `... err 5005` async | Genie | as 1002, async path | same |
| `Failed to free device: 14003` | Genie | follow-on to a failed create | fix the create |
| `Non-identical quantization parameters` | Genie load | KV in/out encodings differ | tie all KV pairs (§4.8) |
| `SIGSYS ... faccessat2` | Go in app | seccomp blocks bare-name lookup | exec absolute paths |
| `open_device_node ... Permission denied` | logcat | vendor HAL refuses app UIDs | §A12 |
| `QAIRT version 2.42 is not supported` | AI Hub | SDK/service version mismatch | use a listed version |
| `Recommended memory (RAM+swap): 80 GB` | AI Hub export | local quantisation path | use cloud compile |
| `Terminated` during ONNX export | WSL | OOM killer | more swap, or cloud |
| `must contain exactly one .onnx file` | qai-hub | HF folder passed to `upload_model` | use `qai-hub-models export` |
| `invalid choice: 'compile'` | qai-hub CLI | wrong tool | `qai-hub-models export` |
| `KernelWorkerStatus.ERROR` / exit 137 | Kaggle | 30 GB cap, no swap | lean ORT calibrator |
| `could not read ok from ADB Server` | laptop | duplicate adb versions | kill all, restart server |
| `cannot stat 'dir\*'` | PowerShell | no glob expansion for adb | `Get-ChildItem | ForEach-Object` |
| device disappears mid-push | USB | cable/port/power | replug, direct port |
| accuracy far below host | model | **double BOS** | compare token counts (§4.6) |
| answers differ every run | model | sampler at temp 0.8 | force greedy |

---

## 9. If I were starting again tomorrow

1. **Day 1, hour 1:** inventory the board; run llama.cpp on the CPU to prove a model runs at all.
2. **Day 1, hour 2:** run the app-sandbox NPU probe (§7.6). Know your architecture before you build it.
3. **Day 1:** QAIRT runtime on the board; `genie-t2t-run` loading a *stock* AI Hub bundle; "Say OK".
4. **Day 2:** token-count parity check host vs device. Fix BOS. Force greedy. Measure a baseline.
5. **Day 3+:** only now, fine-tune and re-export. You will have a known-good reference to compare against,
   which is the thing we lacked for two weeks.
6. Throughout: one NPU call at a time; hash everything you download; keep a restore script current.

**The meta-lesson.** Four separate times we attributed a plumbing bug to the model or the quantiser: the
truncated download, the double BOS, the random sampler, and the hardware retry being reported as a safety
rejection. Each cost days. **Before blaming the hardest-to-debug layer, prove the easy ones are clean.**

---

*Written 2026-10-10 from the Agentic Edge AI for Smart Cities project (Llama 3.2 3B, QLoRA, w4a16 on
Hexagon V75). Companion documents in this repo: `run.md` (setup for this project), `teach.md` (how the
system works), `HANDBOOK.md` (measurements and decisions).*
