package main

// htpd: the batched NPU engine (llama.cpp Hexagon backend), an alternative to genied (HANDBOOK 2.37).
//
// Why: Genie runs one sequence at a time, so a 13-agent incident is 13 back-to-back NPU calls. htpd
// keeps the SAME fine-tuned weights resident on the NPU (packed exactly from the w4a16 checkpoint) and
// decodes all of an incident's agents in one batch with per-sequence KV streams: 13 agents in ~26 s
// instead of ~44 s, synthesizer included the incident drops from ~54 s to ~38 s (measured on device).
//
// Opt-in: the file <workDir>/npu_engine containing "htpd" (or SCE_NPU_ENGINE=htpd) selects it.
// Anything else keeps genied exactly as before. The two engines are never resident together: two
// models on the NPU is the configuration that rebooted the board (HANDBOOK 2.27), so in htpd mode
// genied is stopped and the per-call Genie CLI fallback is disabled.
//
// Protocol (app/genied/../tools/htpd): one JSON object per line each way.
//   -> {"kind":"agents","prompts":[...]}   (agent prompts, ending with the agent prefill)
//   -> {"kind":"synth","prompt":"..."}     (synthesizer / Mode 2 report prompts)
//   <- {"outputs":[{"text","tokens","ttft_ms","ms","stop"}],"prefill_ms","total_ms"}
// htpd applies the same stop rule as answerScanner (object closed, or the agent "action" key).
//
// Streaming (optional, proofs/2026-10-21_v2_research/streaming/htpd_stream_protocol.md): when a
// request carries "stream":true an htpd that supports it writes progress lines BEFORE the result
// line: {"kind":"tok","i":k,"t":"piece"} or one line per decode step {"kind":"toks","t":["",..]}
// (index = stream). The final line is the unchanged result object and stays authoritative. An htpd
// that ignores "stream" just sends the result line, and the client then emits each whole answer
// at the end of the batch exactly as before.

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

var htpdWorkDir string

func npuEngine() string {
	if e := strings.TrimSpace(os.Getenv("SCE_NPU_ENGINE")); e != "" {
		return e
	}
	if b, err := os.ReadFile(filepath.Join(htpdWorkDir, "npu_engine")); err == nil {
		return strings.TrimSpace(string(b))
	}
	return "genie"
}

func htpdEnabled() bool { return npuEngine() == "htpd" }

func htpdAddr() string { return envOr("SCE_HTPD", "127.0.0.1:8091") }

// htpdMaxBatch must match htpd --agents (13 for the v1 agent, 10 for v2: agentversion.go).
func htpdMaxBatch() int { return htpdAgentStreams() }

func htpdUp() bool {
	c, err := net.DialTimeout("tcp", htpdAddr(), 200*time.Millisecond)
	if err != nil {
		return false
	}
	c.Close()
	return true
}

type htpdOut struct {
	Text   string  `json:"text"`
	Tokens int     `json:"tokens"`
	TTFTMs float64 `json:"ttft_ms"`
	Ms     float64 `json:"ms"`
	Stop   string  `json:"stop"`
}

type htpdResp struct {
	Outputs   []htpdOut `json:"outputs"`
	PrefillMs float64   `json:"prefill_ms"`
	TotalMs   float64   `json:"total_ms"`
	Error     string    `json:"error"`
	// htpd v8, kind "reason" only: swap/cache timings ({"load_ms","unload_ms","reload_ms","cache",...})
	Reason json.RawMessage `json:"reason,omitempty"`
}

// htpdLine is any line htpd writes: a streaming progress line (Kind set) or the final result.
type htpdLine struct {
	htpdResp
	Kind string          `json:"kind"`
	I    int             `json:"i"`
	T    json.RawMessage `json:"t"`
}

// htpdStream turns htpd's raw per-stream pieces into what the dashboard may see: each stream goes
// through the same answerScanner as the Genie paths (holdback, so text that the action trim will
// retract is never shown), and finish() reconciles with the authoritative final text, emitting only
// what was not streamed yet. With a non-streaming htpd nothing is fed and finish() emits the whole
// answer at once - the old behaviour.
type htpdStream struct {
	scans []*answerScanner
	done  []bool
	emit  func(k int, s string)
}

func newHtpdStream(n int, prefill string, emit func(k int, s string)) *htpdStream {
	h := &htpdStream{scans: make([]*answerScanner, n), done: make([]bool, n), emit: emit}
	for k := range h.scans {
		k := k
		a := newAnswerScanner(prefill, func(s string) { emit(k, s) })
		if a.ts == nil && prefill == AgentPrefill {
			// htpd always trims agent answers at "action"; hold back the same way even when the
			// app-side trim is switched off, so the stream never shows text the result drops
			a.ts = newTrailScanner()
			a.ts.feed(prefill, trimStopKey)
		}
		h.scans[k] = a
	}
	return h
}

func (h *htpdStream) feed(k int, piece string) {
	if k < 0 || k >= len(h.scans) || h.done[k] || piece == "" {
		return
	}
	if h.scans[k].feed(piece) {
		h.done[k] = true
	}
}

// finish emits the part of the final text the stream has not shown. If htpd's text diverged from the
// streamed prefix (should not happen: same stop rule), nothing more is emitted; the agent result
// that follows replaces the live text on the dashboard anyway.
func (h *htpdStream) finish(k int, final string) {
	a := h.scans[k]
	shown := string(a.gen[:a.emitted])
	if strings.HasPrefix(final, shown) {
		if rest := final[len(shown):]; rest != "" {
			h.emit(k, rest)
		}
		return
	}
	trace("htpd stream %d: streamed text diverged from the final answer (%d bytes shown)", k, len(shown))
}

func htpdCall(ctx context.Context, kind string, prompts []string, timeout time.Duration) (*htpdResp, error) {
	return htpdCallStream(ctx, kind, prompts, timeout, nil)
}

// htpdCallStream is htpdCall with streaming: onPiece (when set) receives every raw generated piece
// per stream as htpd reports it. Works unchanged against an htpd that does not stream.
func htpdCallStream(ctx context.Context, kind string, prompts []string, timeout time.Duration, onPiece func(k int, piece string)) (*htpdResp, error) {
	return htpdCallOpts(ctx, kind, prompts, timeout, nil, onPiece)
}

// htpdCallOpts is htpdCallStream with extra request keys (htpd v8 "reason": keep, prefix, schema, max_new).
func htpdCallOpts(ctx context.Context, kind string, prompts []string, timeout time.Duration, extra map[string]any, onPiece func(k int, piece string)) (*htpdResp, error) {
	c, err := net.DialTimeout("tcp", htpdAddr(), time.Second)
	if err != nil {
		return nil, err
	}
	defer c.Close()
	dl := time.Now().Add(timeout)
	if d, ok := ctx.Deadline(); ok && d.Before(dl) {
		dl = d
	}
	c.SetDeadline(dl)
	req := map[string]any{"kind": kind}
	for k, v := range extra {
		req[k] = v
	}
	if kind == "agents" {
		req["prompts"] = prompts
	} else {
		req["prompt"] = prompts[0]
	}
	if onPiece != nil {
		req["stream"] = true // ignored by an htpd without streaming (it only looks up known keys)
	}
	b, _ := json.Marshal(req)
	if _, err := c.Write(append(b, '\n')); err != nil {
		return nil, err
	}
	rd := bufio.NewReaderSize(c, 1<<20)
	var r htpdResp
	for {
		line, err := rd.ReadBytes('\n')
		if err != nil {
			return nil, err
		}
		var l htpdLine
		if err := json.Unmarshal(line, &l); err != nil {
			return nil, err
		}
		switch l.Kind {
		case "":
			r = l.htpdResp
		case "tok":
			var s string
			if onPiece != nil && json.Unmarshal(l.T, &s) == nil {
				onPiece(l.I, s)
			}
			continue
		case "toks":
			var ss []string
			if onPiece != nil && json.Unmarshal(l.T, &ss) == nil {
				for k, s := range ss {
					if s != "" {
						onPiece(k, s)
					}
				}
			}
			continue
		default:
			continue // future progress lines
		}
		break
	}
	if r.Error != "" {
		return nil, fmt.Errorf("htpd: %s", r.Error)
	}
	if len(r.Outputs) != len(prompts) {
		return nil, fmt.Errorf("htpd: %d outputs for %d prompts", len(r.Outputs), len(prompts))
	}
	return &r, nil
}

// execViaHtpd is exec's path in htpd mode. It never falls back to the Genie CLI (see the file header).
func (g *GenieRunner) execViaHtpd(ctx context.Context, prompt, prefill string, timeout time.Duration,
	onToken func(string)) (string, streamStats, error) {
	var st streamStats
	kind := "synth"
	if prefill == AgentPrefill {
		kind = "agents" // the agent context applies the action trim
	}
	var hs *htpdStream
	var onPiece func(int, string)
	if onToken != nil {
		hs = newHtpdStream(1, prefill, func(_ int, s string) { onToken(s) })
		onPiece = hs.feed
	}
	r, err := htpdCallStream(ctx, kind, []string{prompt}, timeout, onPiece)
	if err != nil {
		htpdKill("call failed: " + err.Error())
		return "", st, fmt.Errorf("htpd: %w", err)
	}
	o := r.Outputs[0]
	st.tokens, st.ttftMs = o.Tokens, o.TTFTMs
	st.genSec = (o.Ms - o.TTFTMs) / 1000
	st.early = o.Stop == "json" || o.Stop == "action"
	st.trimmed = o.Stop == "action"
	if hs != nil {
		hs.finish(0, o.Text)
	}
	out := strings.TrimSpace(o.Text)
	if out == "" {
		return "", st, fmt.Errorf("htpd returned no answer (stop=%s)", o.Stop)
	}
	return out, st, nil
}

// prefetchViaHtpd answers every prompt of an incident in batches of up to htpdMaxBatch() parallel sequences and
// parks the answers in the prompt cache (same contract as the genie-app Prefetch path).
func (g *GenieRunner) prefetchViaHtpd(ctx context.Context, b ModelBundle, todo []string, at []int, onToken func(int, string)) {
	for start := 0; start < len(todo); start += htpdMaxBatch() {
		end := start + htpdMaxBatch()
		if end > len(todo) {
			end = len(todo)
		}
		t0 := time.Now()
		// 13 agents take ~26-36 s; a batch that runs past 150 s is a stalled engine (seen once at 91 C)
		var hs *htpdStream
		var onPiece func(int, string)
		if onToken != nil {
			base := start
			hs = newHtpdStream(end-start, AgentPrefill, func(k int, s string) { onToken(at[base+k], s) })
			onPiece = hs.feed
		}
		r, err := htpdCallStream(ctx, "agents", todo[start:end], 150*time.Second, onPiece)
		if err != nil {
			htpdKill("batch failed: " + err.Error())
			trace("Prefetch(htpd): batch failed, prompts fall back to per-call htpd: %v", err)
			return
		}
		wall := float64(time.Since(t0).Microseconds()) / 1000
		for k, o := range r.Outputs {
			text := strings.TrimSpace(o.Text)
			if text == "" {
				continue
			}
			if hs != nil {
				hs.finish(k, o.Text) // the rest of this agent's answer, or all of it from an htpd that does not stream
			}
			// Streamed: Run must not replay the text when the agent picks the answer up from the cache
			res := GenieResult{Text: text, Model: b.Name, FineTuned: b.FineTuned, Backend: "qidk_htp_llamacpp_batched",
				LatencyMs: o.Ms, TTFTMs: o.TTFTMs, GenTokens: o.Tokens, EarlyStopped: o.Stop == "json" || o.Stop == "action",
				Prefetched: true, Streamed: hs != nil}
			if o.Ms > o.TTFTMs && o.Tokens > 0 {
				res.TokensPerS = float64(o.Tokens) / ((o.Ms - o.TTFTMs) / 1000)
			}
			g.cachePut(sha256Key(b, todo[start+k]), res)
			g.calls.Add(1)
		}
		g.lastMs.Store(int64(wall))
		trace("Prefetch(htpd): %d agents in one batch, %.0f ms (prefill %.0f ms)", end-start, wall, r.PrefillMs)
	}
}

// superviseHtpd starts htpd (and keeps genied stopped) when htpd mode is selected.
func superviseHtpd(g *GenieRunner, workDir string) {
	prof := htpdProfile()
	bin := envOr("SCE_HTPD_BIN", "/data/local/tmp/llama.cpp/bin/htpd")
	if v := prof["bin"]; v != "" {
		bin = v
	}
	profEnv := strings.Fields(prof["env"])
	model := htpdModelPath()
	if _, err := os.Stat(bin); err != nil {
		log.Printf("htpd: not installed at %s - staying on genied", bin)
		return
	}
	lib := filepath.Join(filepath.Dir(filepath.Dir(bin)), "lib")
	// an htpd left running from a backend with other args (agent v1 <-> v2: model, streams, agent ctx)
	// is restarted, so the agent switch always gets its own model and context sizes
	want := fmt.Sprintf("%s --agents %d --agent-ctx %d", model, htpdMaxBatch(), htpdAgentCtx())
	if n := reasonerStreams(); n > 1 {
		want += fmt.Sprintf(" --reason-streams %d", n) // split decoding changes the reasoner context: restart htpd
	}
	if prof["layouts"] != "" || prof["bin"] != "" || len(profEnv) > 0 {
		want += fmt.Sprintf(" bin=%s layouts=%s env=%s", bin, prof["layouts"], strings.Join(profEnv, " "))
	}
	if rm := reasonerHtpdModel(); rm != "" { // htpd v8 reasoner slot (reasoner=v3, reasoner_engine=htpd only)
		want += " reasoner=" + rm
	}
	argsFile := filepath.Join(workDir, "state", "htpd_args")
	if prev, err := os.ReadFile(argsFile); htpdUp() && (err != nil || strings.TrimSpace(string(prev)) != want) {
		htpdKill("args changed: " + want) // returns once the old process has exited
	}
	os.WriteFile(argsFile, []byte(want+"\n"), 0o644)
	if agentV2() {
		if _, err := os.Stat(model); err != nil {
			log.Printf("htpd: agent v2 selected but model %s is missing", model)
		}
	}
	var startedAt time.Time
	start := func() {
		if htpdUp() {
			return
		}
		if pids := htpdPids(); len(pids) > 0 {
			// an htpd exists but is not listening yet: it opens its port only after loading the 2.8 GB model,
			// which can take minutes on a cold board. Starting another here put two models on the NPU.
			if startedAt.IsZero() {
				startedAt = time.Now() // left by an earlier backend: give it the same 5 min from now
			}
			if time.Since(startedAt) < 5*time.Minute {
				return
			}
			htpdKill(fmt.Sprintf("pids %v not listening %s after start", pids, time.Since(startedAt).Round(time.Second)))
		}
		// never two models on the NPU: genied must be gone before htpd loads
		killDaemon("htpd mode selected")
		time.Sleep(time.Second)
		ubSynth := "512"
		if v := prof["ubatch_synth"]; v != "" { // A/B knob (proofs/2026-10-21_latency_ladder): single-sequence prefill chunk
			ubSynth = v
		}
		args := []string{"-m", model, "--agents", fmt.Sprint(htpdMaxBatch()), "--agent-ctx", fmt.Sprint(htpdAgentCtx()),
			"--synth-ctx", "4096", "--ubatch", "512", "--ubatch-synth", ubSynth, "--port", strings.Split(htpdAddr(), ":")[1]}
		if l := prof["layouts"]; l != "" {
			args = append(args, "--agent-layouts", l) // htpd v7: one batch on the first layout that fits
		}
		if rm := reasonerHtpdModel(); rm != "" {
			args = append(args, "--reasoner-model", rm) // htpd v8: in-process swap for kind "reason"
			if n := reasonerStreams(); n > 1 {
				args = append(args, "--reason-streams", fmt.Sprint(n)) // htpd v8x split decoding
			}
		}
		cmd := exec.Command(bin, args...)
		cmd.Env = append(os.Environ(), "LD_LIBRARY_PATH="+lib, "ADSP_LIBRARY_PATH="+lib,
			"GGML_HEXAGON_FA_STREAMS=1", "HTPD_SPEC=0",
			// measured 2026-10-16: pipelined HMX for decode-sized matmuls + parked finished streams
			// (htpd default) cut a 13-agent batch from ~28-31 s to ~24 s with identical outputs; the
			// equal-ubatch prefill (HTPD_LEGACY_PREFILL unset) changed ~30% of outputs for no gain
			"GGML_HEXAGON_HMX_PIPE_ALL=1", "HTPD_LEGACY_PREFILL=1",
			// batched verified drafting, adaptive k (<= 4 per stream, rows <= 32): 13 agents 22 -> 16.4 s,
			// 4 agents 14.9 -> 5.8 s, outputs identical to plain greedy (25/25, 2026-10-16)
			"HTPD_DRAFT=1", "HTPD_DRAFT_K="+envOr("SCE_HTPD_DRAFT_K", "8"),
			// cross-incident KV cache of each role's system-prompt prefix: prefill 8.7 -> 6.8 s (13 agents),
			// 3.1 -> 2.0 s (4 agents); 54-window accuracy unchanged or better (2026-10-16)
			"HTPD_PREFIX_CACHE=1")
		cmd.Env = append(cmd.Env, profEnv...) // htpd_profile flags last, so they override
		logPath := filepath.Join(workDir, "state", "htpd.log")
		if fi, err := os.Stat(logPath); err == nil && fi.Size() > 4<<20 {
			os.Rename(logPath, logPath+".1")
		}
		if lf, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil {
			defer lf.Close()
			cmd.Stdout, cmd.Stderr = lf, lf
		}
		cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
		if err := cmd.Start(); err != nil {
			log.Printf("htpd: start failed: %v", err)
			return
		}
		go cmd.Wait()
		startedAt = time.Now()
		// the kernel kills htpd before any system process if memory runs out (the eval script did this; the
		// app path did not)
		os.WriteFile(fmt.Sprintf("/proc/%d/oom_score_adj", cmd.Process.Pid), []byte("1000"), 0o644)
		for i := 0; i < 60 && !htpdUp(); i++ {
			time.Sleep(250 * time.Millisecond)
		}
		up := htpdUp()
		log.Printf("htpd: started (pid %d), up=%v", cmd.Process.Pid, up)
		if up {
			go htpdWarmup(g, workDir)
		}
	}
	start()
	go func() {
		for range time.Tick(15 * time.Second) {
			if htpdEnabled() && !g.busy.Load() {
				start()
			}
		}
	}()
}

// htpdWarmup primes a freshly started htpd from <workDir>/htpd_warmup.jsonl (one request per line,
// {"kind":"agents","prompts":[...]} or {"kind":"synth","prompts":["..."]}; made by
// proofs/2026-10-21_latency_ladder/make_warmup.py). A cold htpd has no per-role system-prompt KV and no recent
// answers to draft from, so the first incident after a (re)start paid both (chaos round 1: 30.8-34.4 s vs
// 25.5-29.7 s later). Outputs are discarded and never enter the answer cache; the KV restored later is the
// same bytes a cold prefill computes, and drafts are verified. No file = no warm-up (today's behaviour).
// Holds the runner lock like a call, so a real request that arrives meanwhile waits for it (a few seconds).
func htpdWarmup(g *GenieRunner, workDir string) {
	b, err := os.ReadFile(filepath.Join(workDir, "htpd_warmup.jsonl"))
	if err != nil {
		return
	}
	g.mu.Lock()
	g.busy.Store(true)
	defer func() { g.lastEnd = time.Now(); g.busy.Store(false); g.mu.Unlock() }()
	t0, n := time.Now(), 0
	for _, line := range strings.Split(string(b), "\n") {
		var w struct {
			Kind    string   `json:"kind"`
			Prompts []string `json:"prompts"`
		}
		if json.Unmarshal([]byte(strings.TrimSpace(line)), &w) != nil || len(w.Prompts) == 0 {
			continue
		}
		if w.Kind != "agents" {
			w.Kind, w.Prompts = "synth", w.Prompts[:1]
		} else if len(w.Prompts) > htpdMaxBatch() {
			w.Prompts = w.Prompts[:htpdMaxBatch()]
		}
		if _, err := htpdCall(context.Background(), w.Kind, w.Prompts, 120*time.Second); err != nil {
			log.Printf("htpd: warm-up stopped after %d requests: %v", n, err)
			return
		}
		n++
	}
	log.Printf("htpd: warm-up %d requests in %v", n, time.Since(t0).Round(time.Millisecond))
}

func sha256Key(b ModelBundle, prompt string) [32]byte {
	return sha256.Sum256([]byte(b.Dir + "|" + b.Config + "|" + prompt))
}

// htpdKill stops a stalled or failing htpd so the supervisor starts a clean one (within 15 s).
// htpdPids lists every running htpd build (comm "htpd" or "htpd_*": the profile can run htpd_v7 etc.).
func htpdPids() []int {
	var out []int
	ents, _ := os.ReadDir("/proc")
	for _, e := range ents {
		b, err := os.ReadFile("/proc/" + e.Name() + "/comm")
		if comm := strings.TrimSpace(string(b)); err != nil || (comm != "htpd" && !strings.HasPrefix(comm, "htpd_")) {
			continue
		}
		var pid int
		if _, err := fmt.Sscan(e.Name(), &pid); err == nil {
			out = append(out, pid)
		}
	}
	return out
}

// htpdKill stops every htpd and returns only when they are gone, so no second NPU client can start while
// the old one still holds its DSP session (two NPU clients rebooted the board, HANDBOOK 2.27/2.37/2.43).
// SIGTERM first and up to 20 s to exit, SIGKILL only after that; then 10 s for the DSP to release the
// session's memory before anything loads again.
func htpdKill(why string) {
	pids := htpdPids()
	if len(pids) == 0 {
		return
	}
	for _, pid := range pids {
		log.Printf("htpd: stopping pid %d (%s)", pid, why)
		syscall.Kill(pid, syscall.SIGTERM)
	}
	for i := 0; i < 80 && len(htpdPids()) > 0; i++ {
		time.Sleep(250 * time.Millisecond)
	}
	for _, pid := range htpdPids() {
		log.Printf("htpd: pid %d ignored SIGTERM for 20 s - SIGKILL", pid)
		syscall.Kill(pid, syscall.SIGKILL)
	}
	for i := 0; i < 160 && len(htpdPids()) > 0; i++ {
		time.Sleep(250 * time.Millisecond)
	}
	if left := htpdPids(); len(left) > 0 {
		log.Printf("htpd: pids %v still present after kill", left)
	}
	time.Sleep(10 * time.Second)
}
