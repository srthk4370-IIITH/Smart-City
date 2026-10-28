# htpd v8: a LoRA adapter on the synthesizer context only

Status: built and host-tested on 2026-10-22; **not run on the QIDK yet** (see `run_p0_device.sh`).
Source: `Code/smart-city-edge-agent/app/htpd/htpd.cpp` (v7 + about 60 lines). Design background:
`../REASONER_DESIGN.md`, section B.4 and the P0 row.

## Why
One process and one model in NPU memory serve two things:
- the domain agents, on the base v2 weights, exactly as today;
- a reasoner or chat model, which is the same weights plus a small LoRA adapter.

llama.cpp attaches adapters **per context** (`llama_set_adapters_lora`). htpd already keeps the agent context
and the synthesizer context apart and swaps between them. So the adapter goes on the synth context only, and
the agent context never sees it.

## Command line and environment
| flag | env (same meaning; the flag wins) | meaning |
|---|---|---|
| `--lora-synth PATH` | `HTPD_LORA_SYNTH=PATH` | GGUF LoRA adapter, loaded once at start with `llama_adapter_lora_init`. If loading fails, htpd exits with code 1. |
| `--lora-synth-scale S` | `HTPD_LORA_SYNTH_SCALE=S` | default scale, 1.0 if not set |

The environment form lets the app's `htpd_profile` `env=` line turn the adapter on without changing the
backend. **Do not do this until P4:** with no `"lora"` key in the request, every synthesizer call gets the
adapter.

Without `--lora-synth` (and without `HTPD_LORA_SYNTH`), v8 behaves **exactly like v7**: same code paths and
the same response bytes. This was checked on the host; see the results below.

## Protocol (additions only; all v7 keys and behaviour are unchanged)
- **Request**, any kind other than `"agents"` (today that is `"synth"`). The key is ignored when no adapter is
  loaded.
  - `"lora": false` turns the adapter off for this request: base model.
  - `"lora": true` uses the default scale.
  - `"lora": S` uses scale S; 0 means off.
  - If the key is missing, the default scale is used.
- **Agents requests** never get the adapter. The agent contexts are created without one, and htpd never
  calls `llama_set_adapters_lora` on them.
- **Response**, only when an adapter is loaded: `"lora_scale": S`, the scale actually used (0 means the base
  model). It is on every result line, so agents results always carry `0`. It comes after `total_ms`, before
  `"id"`. Clients ignore unknown keys (the v7 rule).

Example:
```
-> {"kind":"synth","prompt":"<|begin_of_text|>...","lora":false}
<- {"outputs":[{"text":"...","tokens":96,"ttft_ms":2100.0,"ms":5400.0,"stop":"json"}],"prefill_ms":2050.0,"swap_ms":310.0,"total_ms":5710.0,"lora_scale":0}
```

## Implementation
- The synth context is still freed and recreated on every swap. The adapter belongs to the model, so it
  survives. After `use(-1)`, htpd calls:
  - `llama_set_adapters_lora(ctx, &adapter, 1, &scale)` when the scale is not 0;
  - `llama_set_adapters_lora(ctx, nullptr, 0, nullptr)` when it is 0.

  llama.cpp skips the call when nothing changed. A change marks the scheduler for re-reserve, so the first
  request after an on/off toggle pays one graph reserve.
- **Prefix cache** (`HTPD_SYNTH_PREFIX_CACHE=1`): a system-turn KV computed with the adapter is different
  from one computed without it.
  - While an adapter is active, each cache key gets one extra negative "token" that identifies the scale.
    Token ids are never negative, so these keys cannot collide with real ones.
  - With no adapter, the keys are exactly the v7 keys.
  - Each adapter scale therefore has its own entry. Host check: on → off → on gives identical "on" texts, and
    "off" equals v7.
- The API at llama.cpp 620d2225 is `llama_adapter_lora_init`, `llama_set_adapters_lora` (plural, with a
  scales array), `llama_adapter_meta_val_str` and `llama_adapter_lora_free`. There is no
  `llama_set_adapter_lora` singular at this commit.
- **Naming:** the device binary is `htpd_v8lora`. The name `htpd_v8` is already used by the latency-ladder
  patch (`proofs/2026-10-21_latency_ladder/patches/htpd_v8.patch`: `HTPD_DRAFT_ROWS`, `HTPD_DRAFT_DYN`,
  `HTPD_PREFIX_CACHE_MAX`), which has not been applied to the source. That patch edits the same prefix-cache
  lines (the `mkey`/`key` lookups), so merging the two needs a small manual rebase. The adapter tag line is
  one statement after each key.

## Adapter format for the Hexagon backend
- **Use F16.** `convert_lora_to_gguf.py --outtype f16`.
- **Not Q8_0, for two reasons** (source review of ggml-hexagon at 620d2225):
  1. **Shape:** `lora_b` has `ne0 = r` (16 or 32). Q8_0 needs rows that are a multiple of 32, and the HTP
     Q8_0 matmul additionally requires `ne0 % 32 == 0`, so r=16 cannot be Q8_0 at all.
  2. **Repacking:** HTP runs Q8_0 weights from a *repacked (tiled)* layout. Repacking only happens when the
     buffer usage is WEIGHTS. `llama_adapter_lora_init` allocates its buffers without setting that usage, so
     a Q8_0 adapter tensor would be copied untiled and could be misread. This is a risk to verify, not
     something we measured.

  F16 `MUL_MAT` is supported on HTP (`docs/ops/Hexagon.csv` 281/281). It takes the HVX path when HMX is not
  eligible, which is the case for the small `lora_b` K = r.
- **Where adapter tensors go:** they land in the same buffer type as the base tensor (HTP0), because the
  Hexagon backend registers no CPU extra buffer type. The device run checks this from the log:
  - the `LoRA buffer size` lines;
  - no `cannot use buft ... fallback to CPU`;
  - `graph splits` for the synth context with the adapter on, compared with off.

## Host results (x86 CPU, 4 threads; `host/checks.json`, `host/results.json`, `host/htpd_host.log`)
**All 8 checks pass** (`host/checks.json`):

| check | result |
|---|---|
| B: v8 with no flag is byte-identical to v7 on every response (agents, 2 synth, agent-prompt-as-synth), timings aside | pass |
| B: v8 `--lora-synth`: agents identical to v7 | pass |
| B: `lora:false` synth identical to v7, also after adapter runs (prefix cache keyed per adapter) | pass |
| B: on → off → on: the two "on" texts are identical | pass |
| B: `lora_scale` is 1 when on and 0 when off | pass |
| A: agents identical to v7 on base Llama (the adapter never reaches the agent context) | pass |
| A: `lora:false` synth identical to v7 on base | pass |
| A: **base Llama Q8_0 + v2 LoRA on the synth context equals the merged v2 Q8_0, byte for byte, on 3/3 prompts** | base alone is 0.03–0.35 similar to v2 |

Test B, the effect of the delta adapter, compared with the merged 3d Q4_0 model:
- synth1 is now **exactly the 3d text** (base v2 was 0.69 similar);
- synth0 is unchanged; there the 3d model differs (similarity 0.87), probably from Q4_0 requantisation of the
  merged 3d weights and the 9% truncated delta energy;
- agent-as-synth0 changed (0.85 similar to 3d).

So the delta is real and points the right way, but it is not an exact 3d replica in Q4_0.

**Overhead on the host** (`host/speed_*.json`): one process, plain greedy, interleaved off/on × 3, ~700-token
prompt, 64 new tokens, 4 threads.

| setup | prefill off → on | decode off → on | overhead |
|---|---|---|---|
| v2 Q4_0 + delta r=16 F16 (46 MiB; set with the `HTPD_LORA_SYNTH` env route) | 19.8 → 20.9 s | 9.40 → 8.86 tok/s | prefill +5.4%, decode +6.1% |
| base Q8_0 + v2 r=32 F16 (93 MiB, `--lora-synth`) | 16.2 → 17.3 s | 5.97 → 5.65 tok/s | prefill +6.7%, decode +5.8% |

Texts were stable across rounds. The CPU overhead is under the 10% gate, but the gate is decided on HTP.

Ignore the `speed` numbers in `host/checks.json`: those runs used drafting and a cold page cache. The
`speed_*.json` files are the overhead measurement.

Test setup: both tests use the app's htpd flags
(`HTPD_SPEC=0 HTPD_LEGACY_PREFILL=1 HTPD_DRAFT=1 HTPD_DRAFT_K=8 HTPD_PREFIX_CACHE=1 HTPD_AGENT_MAX_NEW=160
HTPD_JSON_ABORT=2 HTPD_SYNTH_PREFIX_CACHE=1`):
- **B, deployment shape.** The deployed v2 Q4_0 plus a delta adapter, F16, r=16:
  - the delta is 3d step 50 minus v2, an SVD of the exact rank-64 difference, keeping 90.9% of its energy;
  - its norm is 0.8% of the v2 LoRA, so this is a *small, real* change.

  Checks: v8 with no flag is byte-identical to v7; agents are identical with the adapter loaded;
  `lora:false` is identical to v7; and the effect of the adapter compared with the merged 3d model.
- **A, large and predictable effect.** Base Llama-3.2-3B Q8_0 plus the v2 LoRA (r=32, F16) on the synth
  context should reproduce the merged v2 model (v2 Q8_0). The agent context stays the base model and must be
  identical to v7 on the base.

## Files
| file | what |
|---|---|
| `make_delta_lora.py` | exact low-rank delta of two PEFT LoRAs over the same base (QR + SVD of the 2r × 2r core) |
| `host_lora_test.py` | host tests A and B over TCP |
| `run_p0_device.sh`, `p0_client.py`, `compare_p0.py`, `device_inputs/` | the device spike (not run) |
| `C:\Users\hp\gpu_work\htpd_v8\bin\htpd` | Android arm64 build, same toolchain and flags as v7 (md5 in `htpd.md5`) |
| `C:\Users\hp\gpu_work\htpd_v8\adapters\` | `lora_delta3d50_r16_f16.gguf` (device test), `lora_v2_r32_f16.gguf` (host test A), `adapters.md5`, `delta_stats.json` |
