# htpd v7 protocol (2026-10-21)

htpd v7 is a superset of v6. **With no v7 env flags, no `--agent-layouts` and no new request keys, it behaves
byte-for-byte like v6** (same stop rule, same sampling, same response line). This was checked on the host:
the v7 stop scanner equals the v6 one on all 4738 device outputs, and v7 with flags off matches the v6 binary
end to end (`host_e2e.py`).

Source: `Code/smart-city-edge-agent/app/htpd/htpd.cpp`. The pure logic is in `htpd_logic.h` (scanner, label
trie, JSON abort, draft table, streaming lines, JSON parser) and is unit-tested by `test_logic.cpp`.

Transport is unchanged: TCP on 127.0.0.1, one JSON request line in. Without `"stream":true` exactly one
response line comes back. With it, zero or more progress lines come first and the result line comes last.

## Request

```json
{"kind":"agents","prompts":["...", "..."],
 "labels":[["stable","spike"], {"pattern":["stable"],"status":["normal","warning"]}, null],
 "draft":["reference completion", ["c1","c2"], null],
 "logprobs":true, "stream":true, "id":"inc-42"}
{"kind":"synth","prompt":"...", "stream":true}
```

| key | kinds | meaning |
|---|---|---|
| `kind`, `prompts`, `prompt` | as v6 | unchanged |
| `labels` | agents | One element per prompt. A bare array means the allowed `pattern` values. An object maps each top-level key to its allowed values. `null` means none. Used by `HTPD_PATTERN_TRIE` and by the `HTPD_JSON_ABORT` length rule. |
| `draft` | agents | One element per prompt: a string, an array of strings, or `null`. These are reference completions for `HTPD_ROLE_DRAFT`. They are turned into an n-gram table, which is cached per distinct text set (up to 16 sets). |
| `logprobs` | agents | `true` adds the top-5 log-probabilities of each stream's **first generated token**, i.e. the first token of the pattern value. They come from the raw logits, before any label constraint. |
| `stream` | both | `true` sends progress lines (see below). |
| `id` | both | Echoed back as `"id"` on the result line, including on errors. |

Unknown keys are ignored. The request is now parsed by a real JSON parser (v6 used substring search). A line
that is not a JSON object gets `{"error":"bad request"}`.

## Response

Result line (always last). The v6 fields are unchanged. The added fields appear **only when their feature is on**:

```json
{"outputs":[{"text":"...","tokens":87,"ttft_ms":812.0,"ms":5321.4,"stop":"action",
             "forced":0,
             "logprobs":[{"tok":"stable","lp":-0.0123},{"tok":"step","lp":-4.9}, ...]},
            {"text":"step 0, 0 1-1\n","tokens":9,"ttft_ms":...,"ms":...,"stop":"abort","abort_why":"control byte in string"}],
 "prefill_ms":5400.2,"swap_ms":0.0,"total_ms":11021.7,"id":"inc-42"}
```

- `stop` is one of `json` | `action` | `eog` | `max` | `ctx` | **`abort`** (new, `HTPD_JSON_ABORT`). An
  aborted text is the generated text up to and including the byte that broke the rule. It is never valid JSON
  of the agent schema, so `checkAgent` rejects it exactly as it rejected the runaway.
- `abort_why`: present only when `stop` is `abort`.
- `forced`: present when the label constraint is active for any stream of the request. It counts the tokens
  where the constraint replaced the plain argmax. 0 means the output is plain greedy.
- `logprobs`: present only if the request asked for it.
- `id`: present only if the request had one.

### Streaming (`"stream":true`), as in `proofs/2026-10-21_v2_research/streaming/htpd_stream_protocol.md`

```json
{"kind":"toks","t":["<new text of stream 0>","","<new text of stream 2>"]}
```

- One line per decode step. `t[s]` holds exactly the bytes fed to stream `s`'s stop scanner in that step:
  raw pieces, no action trim. Accepted draft tokens are joined. The index is the position in `prompts`;
  synth uses index 0.
- No lines during prefill. The first line follows prefill and carries every stream's first token.
- Only whole UTF-8 characters are sent. A trailing partial sequence is held back per stream and sent with the
  next piece. A step in which no stream gained a whole character sends no line.
- Lines are written by a writer thread. The decode loop only appends to a queue, so a slow client cannot
  stall decoding. `send(MSG_NOSIGNAL)` is used, so a vanished client does not kill htpd. The result line goes
  through the same queue, so it is always the last line.
- If the request is split over several layouts (see below), the sub-batches stream one after another, each
  under its streams' request indices.

## Env flags (all default off)

| flag | effect | output change |
|---|---|---|
| `HTPD_AGENT_MAX_NEW=N` | New-token cap for agent batches only. Synth keeps `--max-new`. | Only outputs longer than N, which valid answers never are (max ~120, p99 108). Suggested: 160. |
| `HTPD_JSON_ABORT=1` | Stops a stream once its text provably cannot be JSON of the agent schema: a raw control byte inside a string; a byte outside strings that JSON cannot contain; an enum value (`pattern`/`status`/`likely_cause`/`action`/`fault_kind`/`onset`) longer than its longest label. Labels come from the request, else from the prompt's `JSON keys:` list; otherwise the limit is 48 bytes (`HTPD_JSON_ABORT_MAXVAL`). | Valid outputs are byte-identical (0 of 3546 valid device outputs aborted). |
| `HTPD_JSON_ABORT=2` | Level 1, plus three rules that are legal JSON but absent from agent answers: a newline outside strings, nesting deeper than 2, and a top-level key longer than 32 bytes. | Also 0 of 3546. Catches all 30 device runaways (level 1 catches 28). |
| `HTPD_PATTERN_TRIE=1` | Inside a labelled top-level string value, greedy picks the highest-logit token that keeps the value a prefix of an allowed label, and exactly a label when the value closes. Labels come from the request only. | None when the plain argmax is allowed (then it is used unchanged). Otherwise it is an accuracy fix: off-label or garbage becomes the best on-label continuation. |
| `HTPD_PATTERN_TRIE=2` | Same, but with no request labels the prompt's own enum lists are used, for the keys in `HTPD_TRIE_KEYS` (default `pattern,status`). Needs no client change. | Same. |
| `HTPD_ROLE_DRAFT=1` | With `HTPD_DRAFT=1`: a static per-role n-gram table is an extra draft source, after other streams, recent outputs and the stream's own history. Texts come from the request `draft`, else `HTPD_ROLE_DRAFT_FILE` (JSONL `{"match":"You are the Air Quality agent","texts":[...]}`, written by `make_role_draft.py` from TRAIN completions). | None: drafts are verified. |
| `HTPD_LOGITS_READ=1` | With `HTPD_DRAFT=1`: pad rows past a short draft request no logits, so lm_head runs only on rows that are read. | Changes only how many rows lm_head computes. Judge against the 21-24/25 noise floor. |
| `HTPD_SYNTH_PREFIX_CACHE=1` | With `HTPD_PREFIX_CACHE=1`: the synthesizer's system turn (tokens up to the first `<\|eot_id\|>`) is also restored from the host-memory KV cache instead of being prefilled. | None: same KV bytes. Saves about the system-turn prefill time per report. |
| `HTPD_LAYOUT_HEADROOM=T` | Token headroom for the layout choice (default 136 = 128 output + 5 draft cells + slack). | - |

## Command line

- `--agent-layouts A1xC1,A2xC2,...` (new), e.g. `14x1024,10x1280`. These are the agent KV layouts:
  streams × cells per stream, with per-stream KV slices as before. A request runs as **one** batch on the
  current layout if it fits: count ≤ streams, and every prompt's tokens + headroom ≤ cells. Otherwise it runs
  on the first layout that fits. If none fits all prompts, they are split by length (each prompt goes to the
  first layout it fits), the sub-batches run one after another, and the outputs are merged in request order.
  The first layout is created at start. Others are swapped in like the synth context (`swap_ms`). Without the
  flag there is the single `--agents x --agent-ctx` layout, as in v6. A request may hold up to the largest
  layout's stream count.

## What the Go client needs (htpdclient.go, owned by another agent; not edited here)

1. Request: add `"stream":true` (done already per the streaming note), plus optionally `"id"`, `"logprobs"`
   and `"labels"`. `"labels"` is only needed for `HTPD_PATTERN_TRIE=1`; with `=2`, htpd reads the prompt.
2. `htpdOut`: optional `Forced int \`json:"forced"\``, `AbortWhy string \`json:"abort_why"\``, and
   `Logprobs []struct{Tok string; LP float64 \`json:"lp"\`} \`json:"logprobs"\``. Unknown fields are already
   ignored, so nothing breaks without them.
3. `stop:"abort"`: treat it like `"ctx"` / `"max"`. That means not early-stopped, and the text goes to
   `checkAgent`, which rejects it as before. `execViaHtpd` returns `htpd returned no answer` only for empty
   text, and an aborted text is never empty, so that path is unchanged. Optionally re-ask once on abort.
4. Supervisor env (`superviseHtpd`): add the chosen flags, e.g. `"HTPD_AGENT_MAX_NEW=160"`,
   `"HTPD_JSON_ABORT=2"`, `"HTPD_PATTERN_TRIE=2"`,
   `"HTPD_ROLE_DRAFT=1","HTPD_ROLE_DRAFT_FILE="+lib+"/../role_draft_v2.jsonl"`. Flags change the daemon's
   behaviour, so include them in the `htpd_args` restart key.
5. One-batch incidents: `htpdMaxBatch()` 10 → 14, and args `--agents 14 --agent-ctx 1024
   --agent-layouts 14x1024,10x1280`. Add `--agent-layouts` to the `want` string too. `prefetchViaHtpd`
   already chunks by `htpdMaxBatch()`. With 14, a 13-14 agent incident is one request, and htpd decides
   whether it runs as one batch (all prompts ≤ 1024-136 = 888 tokens, i.e. every 4 h prompt) or splits.
