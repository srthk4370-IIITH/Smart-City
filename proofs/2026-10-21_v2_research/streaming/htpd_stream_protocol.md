# htpd streaming protocol proposal (`"stream":true`)

Status: the client side is done and tested (`app/backend/htpdclient.go`, `htpdstream_test.go`).
`app/htpd/htpd.cpp` is not changed. Until htpd implements this, the app works exactly as it
does today, and each answer still arrives whole at the end of its batch.

## Why

Today htpd writes one result line after the whole batch, so the operator sees nothing for the
full batch time: about 16-24 s for 10 agents (prefill about 7 s, then decode), and about the
same again for the report. The dashboard, SSE hub and reasoner can already stream token by
token. The only step that waits for the end is htpd.

## Request

The request is unchanged, plus one optional key:

```
{"kind":"agents","prompts":["...", ...],"stream":true}
{"kind":"synth","prompt":"...","stream":true}
```

Today's htpd looks up only `kind`, `prompts` and `prompt` (`find_key`), so it ignores the extra key.

## Response with `"stream":true`

Zero or more progress lines come first. The **unchanged** result line comes last and is still
the authority:

```
{"kind":"toks","t":["<piece s0>","","<piece s2>", ...]}     <- one line per decode step (preferred)
{"kind":"tok","i":2,"t":"<piece>"}                          <- or one line per stream and piece (also accepted)
...
{"outputs":[{"text":...,"tokens":...,"ttft_ms":...,"ms":...,"stop":...}],"prefill_ms":...,"total_ms":...}
```

Rules:

1. **What to send.** `t[s]` is exactly the text appended to stream `s` in this step, in the order
   it was passed to `scan[s].feed(...)`. With batched drafting, accepted draft tokens are joined
   into one string. Send `""` for streams that are finished, parked, or did not advance. Index
   = position in `prompts`, and `synth` uses index 0.
2. **Send raw pieces.** Do not apply the action trim to them. The client runs the same
   `answerScanner` as the Genie paths. It holds back the last 16 bytes and cuts at
   `, "action"`, so trimmed text never reaches the screen. The final `text` decides what was
   generated, and the client emits only `final[len(shown):]` at the end.
3. **Whole UTF-8 characters only.** Byte-level tokens split characters such as `°` and `µ`.
   Keep a per-stream pending buffer of an incomplete trailing UTF-8 sequence and send it with
   the next piece. Otherwise `json_escape` writes invalid UTF-8, the Go JSON decoder turns it
   into U+FFFD, and the streamed prefix no longer matches the final text. The client then stops
   streaming that answer: nothing breaks, but the operator sees the tail appear late.
4. **One `write()` per step**, after `llama_decode` and sampling for that step. Do not send a
   line per token per stream: 10 streams would mean 10 syscalls a step. TCP_NODELAY is not
   needed because the backend reads line by line.
5. **Leave the prefill alone.** Send no lines during prefill. An optional
   `{"kind":"first","i":s,"ttft_ms":x}` is allowed (the client ignores unknown kinds), but it is
   not needed: the dashboard already shows "Reading the readings" from the backend's `batch` event.
6. **Errors.** If the batch fails after progress lines were sent, still finish with
   `{"error":"..."}` as the last line. The client treats it as today: it kills htpd and falls
   back to per-call.

Cost on device: one `json_escape` and one `write` per decode step, about 10 short strings.
That is tiny next to a ~60-150 ms step. Model output is unchanged, because this only reports
what the stop scanner already sees.

## Sketch for htpd.cpp (for the owner of that file)

```cpp
// run_batch(..., bool stream, int fd)
std::vector<std::string> step_txt(n), utf8_pend(n);
auto handle = [&](int s, llama_token t) {
    ...
    std::string p = piece(t);
    if (stream) step_txt[s] += p;            // raw piece, same bytes as scan[s].feed(p)
    if (scan[s].feed(p)) { ... }
};
auto flush_step = [&] {                       // after each decode step
    if (!stream) return;
    std::string line = "{\"kind\":\"toks\",\"t\":[";
    bool any = false;
    for (int s = 0; s < n; ++s) {
        std::string t = utf8_pend[s] + step_txt[s];
        size_t cut = complete_utf8_prefix(t);   // drop a trailing partial sequence into pend
        utf8_pend[s] = t.substr(cut); t.resize(cut);
        any |= !t.empty();
        line += (s ? ",\"" : "\"") + json_escape(t) + "\"";
        step_txt[s].clear();
    }
    line += "]}\n";
    if (any) (void) !write(fd, line.data(), line.size());
};
```

`run_single_spec` (synth) does the same with a single stream: one line per verified step.

## Evidence (laptop, fake htpd with the same line protocol)

`e2e_fake_htpd.json` covers the whole backend: fake htpd, client, Prefetch/Run, reasoner sinks
and SSE hub. It uses 4 agents plus the report, a 300 ms fake prefill and 15 ms per step:

| | today's htpd | streaming htpd |
|---|---|---|
| first visible token | 1322 ms (end of batch) | 555 ms (prefill + first step) |
| token events per agent | 1 (whole answer) | 36-96 |
| report token events | 1 | 49 |
| median gap between events | 1363 ms | 16 ms |
| duplicated answers on the dashboard | 0 (before this change: every batched answer was sent twice, by Prefetch and again by Run) | 0 |

On the device, expect first visible token at about the prefill time (about 7 s for 10 agents)
instead of the batch time (about 16-24 s).
