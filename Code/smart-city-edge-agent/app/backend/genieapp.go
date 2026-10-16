package main

// Batched Genie calls: pay model init once per incident instead of once per agent.
//
// NOT WIRED IN. This is a measured, working mechanism waiting on the Mode-3 refactor described at
// the bottom. Nothing in the serving path calls it today.
//
// The problem. genie.go spawns one genie-t2t-run per request, so every call pays model init.
// Profiler on the live fine-tuned bundle, 548-token prompt, 59 generated tokens:
//
//	init 687 / 700 / 697 ms      prefill 395 / 401 / 395 ms      decode 2613 / 2664 / 2662 ms
//
// Init is 18% of end-to-end, spent reloading a model that never changes. Mode 3 runs one call per
// flagged sensor plus a synthesizer, so a 4-sensor incident pays it five times - about 3.5 s of an
// incident spent loading the same 2.6 GB five times over.
//
// What works. The QAIRT 2.50 SDK ships genie-app for aarch64-android: the same Genie API driven by
// a script of commands. One invocation can create the dialog once and then run many queries:
//
//	dialog config create CFG smartcity_agent.json
//	dialog create D CFG
//	dialog reset D
//	dialog query D <prompt file>        <- repeated, init already paid
//	exit
//
// Measured by running N queries in one process, bracketed with logcat marks (shell wall-clock is
// not trustworthy here - see the header of tools/bench_device.sh):
//
//	N=1  3.920 s     N=2  7.022 s     N=3  10.120 s     N=5  16.537 s
//	steady state = (16.537 - 3.920) / 4 = 3.15 s per query, vs 3.74 s per separate CLI call
//
// So the first query in a batch costs the usual ~3.7 s and every one after it costs ~3.15 s:
// roughly 630 ms saved per extra agent in the incident.
//
// Output is unchanged. Three consecutive queries on one dialog all produced
// md5 b35b74c0123cc1ce28a118db70c2bf2f, identical to the per-call CLI answer. "dialog reset D"
// clears the KV cache between queries, so each one sees exactly the context a fresh process would,
// and decoding is greedy (temp 0, top-k 1) - the same determinism the prompt cache already relies
// on. Weights, bundle and sampler are untouched.
//
// Why this is a batch and not a resident daemon. The obvious design is one long-lived genie-app
// fed queries over a pipe. It cannot work: genie-app reads its whole script to EOF before it
// executes anything. Measured with a producer that wrote two commands, slept 10 s, then closed:
//
//	09:26:27.371 SCEMARK : STREAM start
//	09:26:37.441 SCEMARK : STREAM eof-now
//	09:26:37.475 dsp-manager: openSession: device fd 7 opened for domain 3   <- 34 ms after EOF
//
// Ten seconds idle, then init. Plain piped stdin with no --script produces no output at all; only
// "--script /dev/stdin" is read, and still only at EOF. So the set of prompts has to be known
// before the process starts, which is exactly true of one incident's agents and false of
// request-by-request serving.
//
// Streaming survives. genie-app prints each answer to stdout between "[BEGIN]:" and "[END]" as it
// decodes, the same markers genie.go already parses, so the UI can still receive tokens live -
// runBatch calls onToken(i, text) with the index of the query being answered.

import (
	"bufio"
	"context"
	"crypto/sha256"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// batchBin is the genie-app binary. It sits next to genie-t2t-run in the runtime dir; on the
// Android app it would be packaged as a native lib the same way the CLI is.
func batchBin(runtimeDir string) string {
	if v := os.Getenv("SCE_GENIE_APP_BIN"); v != "" {
		return v
	}
	return filepath.Join(runtimeDir, "genie-app")
}

// runBatch answers every prompt in one genie-app invocation, paying model init once.
//
// prompts are the full prompt texts, in order; the returned slice has one entry per prompt, holding
// the text between [BEGIN]: and [END]. The second slice is the number of stdout chunks each answer
// arrived in - what the rest of this package reports as "tokens" (see streamStats in genie.go).
// onToken, if non-nil, is called with (prompt index, chunk) as each chunk arrives. An entry is
// empty if that query produced no answer.
func (g *GenieRunner) runBatch(ctx context.Context, b ModelBundle, prompts []string, onToken func(int, string)) ([]string, []int, error) {
	if len(prompts) == 0 {
		return nil, nil, nil
	}
	bin := batchBin(g.runtime)
	if _, err := os.Stat(bin); err != nil {
		return nil, nil, fmt.Errorf("genie-app not present: %w", err)
	}

	stamp := time.Now().UnixNano()
	var files []string
	defer func() {
		for _, f := range files {
			os.Remove(f)
		}
	}()
	var script strings.Builder
	fmt.Fprintf(&script, "dialog config create CFG %s\ndialog create D CFG\n", b.Config)
	for i, p := range prompts {
		f := filepath.Join(g.promptDir, fmt.Sprintf("b_%d_%d.txt", stamp, i))
		// Genie's tokenizer adds BOS itself, so strip ours - same reason as in GenieRunner.exec.
		if err := os.WriteFile(f, []byte(strings.TrimPrefix(p, "<|begin_of_text|>")), 0o644); err != nil {
			return nil, nil, err
		}
		files = append(files, f)
		// reset clears the KV cache so each query sees a fresh context, like a new process would
		fmt.Fprintf(&script, "dialog reset D\ndialog query D %s\n", f)
	}
	script.WriteString("exit\n")

	sf := filepath.Join(g.promptDir, fmt.Sprintf("b_%d.script", stamp))
	if err := os.WriteFile(sf, []byte(script.String()), 0o644); err != nil {
		return nil, nil, err
	}
	files = append(files, sf)

	rt := g.runtime
	cmd := exec.CommandContext(ctx, bin, "--script", sf)
	cmd.Dir = b.Dir
	cmd.Env = append(os.Environ(),
		"LD_LIBRARY_PATH="+envOr("SCE_GENIE_LD", rt+"/qairt_2_50_libs:"+rt+"/aarch64-android:"+rt),
		"ADSP_LIBRARY_PATH="+envOr("SCE_GENIE_ADSP", rt+"/dsp_2_50;"+rt+"/dsp;"+rt+"/dsp/unsigned;/vendor/dsp/cdsp;/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp;/dsp"))
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, nil, err
	}
	var stderr strings.Builder
	cmd.Stderr = &stderr
	t0 := time.Now()
	if err := cmd.Start(); err != nil {
		return nil, nil, err
	}

	out := make([]string, len(prompts))
	counts := make([]int, len(prompts))
	idx := -1 // answer currently being streamed; -1 between answers
	next := 0 // which prompt the NEXT [BEGIN]: belongs to
	var cur strings.Builder
	rd := bufio.NewReaderSize(stdout, 1<<16)
	buf := make([]byte, 512)
	var tail string // carries a marker split across two reads
	for {
		n, rerr := rd.Read(buf)
		if n > 0 {
			chunk := tail + string(buf[:n])
			tail = ""
			for chunk != "" {
				if idx < 0 {
					i := strings.Index(chunk, "[BEGIN]:")
					if i < 0 {
						// the prompt echo also lands here; keep only enough to match a split marker
						if len(chunk) > 16 {
							tail = chunk[len(chunk)-16:]
						} else {
							tail = chunk
						}
						break
					}
					idx = next
					next++
					if idx >= len(out) { // more answers than prompts: should not happen
						idx = len(out) - 1
					}
					cur.Reset()
					chunk = strings.TrimLeft(chunk[i+len("[BEGIN]:"):], " ")
					continue
				}
				if i := strings.Index(chunk, "[END]"); i >= 0 {
					if i > 0 {
						cur.WriteString(chunk[:i])
						counts[idx]++
						if onToken != nil {
							onToken(idx, chunk[:i])
						}
					}
					out[idx] = strings.TrimSpace(cur.String())
					chunk = chunk[i+len("[END]"):]
					idx = -1
					continue
				}
				// no end marker in this chunk: hold back a few bytes in case "[END]" is split
				emit := chunk
				if len(emit) > 8 {
					tail, emit = emit[len(emit)-8:], emit[:len(emit)-8]
				} else {
					tail, emit = emit, ""
				}
				if emit != "" {
					cur.WriteString(emit)
					counts[idx]++
					if onToken != nil {
						onToken(idx, emit)
					}
				}
				break
			}
		}
		if rerr != nil {
			break
		}
	}
	if idx >= 0 { // stream ended mid-answer
		out[idx] = strings.TrimSpace(cur.String())
	}
	werr := cmd.Wait()
	trace("runBatch: %d prompts in %v", len(prompts), time.Since(t0))

	got := 0
	for _, s := range out {
		if s != "" {
			got++
		}
	}
	if got == 0 {
		tailMsg := stderr.String()
		if len(tailMsg) > 400 {
			tailMsg = tailMsg[len(tailMsg)-400:]
		}
		return out, counts, fmt.Errorf("genie-app batch produced no answers: %v: %s", werr, tailMsg)
	}
	return out, counts, nil
}

// batchEnabled gates the whole mechanism. Default OFF: the demo keeps today's behaviour unless the
// batch is explicitly switched on with SCE_GENIE_BATCH=1.
// NOTE on batching vs the action trim: runBatch streams whole answers out of one genie-app process
// and cannot abort an individual query mid-script, so the trim (HANDBOOK 2.18) does NOT apply to
// batched agent calls - they still generate the `action` field that policy.go then overwrites.
// That costs ~199 ms per batched agent, against the ~1331 ms batching saves per extra agent, so
// batching still wins by a wide margin. The trim keeps its full value on single-agent incidents,
// which is where it matters most because there is no batch to amortise init across.
//
// Batching is ON by default: measured 2026-10-14 on a real 2-agent Mode-3 incident at 965 ms saved
// (18691 -> 17726 ms total), and verify_batch.py proved the answers byte-identical 16/16 across all
// five roles. It must be a code default rather than an env var, because the Android watchdog
// restarts the backend without our environment. Set SCE_GENIE_BATCH=0 to fall back to per-call.
func batchEnabled() bool { return os.Getenv("SCE_GENIE_BATCH") != "0" }

// Prefetch answers several prompts in one NPU process and drops the answers into the prompt cache,
// so the normal Run path finds them without changing how callers are written.
//
// It removes two per-call overheads for every prompt after the first:
//   - model init, ~695 ms (paid once for the batch)
//   - the inter-call gap Run enforces (250 ms since 2026-10-14, was 600), because there is only
//     one process
//
// so roughly 1.3 s per extra prompt. A four-agent incident goes from ~4 x 4.34 s to
// ~0.7 s + 4 x 3.15 s.
//
// Answers are proven to match the per-call path: training/export/verify_batch.py runs the same
// prompts both ways and requires every answer to be byte-identical. It passed 16/16 across all
// five roles, including the prompts the rejected LADE experiment corrupted.
//
// Best effort by design. Anything that fails is simply not cached, and Run then does its usual
// per-call work for that prompt, with its usual HTP retry and error handling.
func (g *GenieRunner) Prefetch(ctx context.Context, b ModelBundle, prompts []string, prefill string, onToken func(int, string)) {
	if !batchEnabled() || len(prompts) < 2 || g.mock {
		return
	}
	// skip anything already answered; batching one prompt saves nothing
	var todo []string
	var at []int
	for i, p := range prompts {
		if _, hit := g.cacheGet(sha256.Sum256([]byte(b.Dir + "|" + b.Config + "|" + p))); !hit {
			todo = append(todo, p)
			at = append(at, i)
		}
	}
	if len(todo) < 2 {
		return
	}

	g.queue.Add(1)
	g.mu.Lock()
	g.queue.Add(-1)
	g.busy.Store(true)
	defer func() { g.lastEnd = time.Now(); g.busy.Store(false); g.mu.Unlock() }()
	if htpdEnabled() {
		g.prefetchViaHtpd(ctx, b, todo, at, onToken)
		return
	}
	// Same spacing Run uses, and for the same reason - see the measurement table in genie.go.
	// Re-measured 2026-10-14: the half-speed cliff this guarded against no longer reproduces on the
	// fine-tuned bundle with async init, so this came down from 600 ms to 250 ms.
	gap := 250 * time.Millisecond
	if g.lastDir != "" && g.lastDir != b.Dir {
		gap = 2500 * time.Millisecond
	}
	if wait := gap - time.Since(g.lastEnd); !g.lastEnd.IsZero() && wait > 0 {
		time.Sleep(wait)
	}
	g.lastDir = b.Dir

	t0 := time.Now()
	var sink func(int, string)
	if onToken != nil {
		sink = func(k int, chunk string) { onToken(at[k], chunk) }
	}
	texts, counts, err := g.runBatch(ctx, b, todo, sink)
	if err != nil {
		trace("Prefetch: batch failed, every prompt falls back to the per-call path: %v", err)
		return
	}
	per := float64(time.Since(t0).Microseconds()) / 1000.0 / float64(len(todo))
	n := 0
	for k, text := range texts {
		text = strings.TrimSpace(text)
		if text == "" {
			continue // not answered: leave it to Run
		}
		res := GenieResult{Text: text, Model: b.Name, FineTuned: b.FineTuned, Backend: "qidk_htp",
			LatencyMs: per, GenTokens: counts[k], Prefetched: true}
		g.cachePut(sha256.Sum256([]byte(b.Dir+"|"+b.Config+"|"+todo[k])), res)
		g.calls.Add(1)
		n++
	}
	g.lastMs.Store(int64(per))
	trace("Prefetch: %d/%d prompts answered in one process, %.0f ms each", n, len(todo), per)
}
