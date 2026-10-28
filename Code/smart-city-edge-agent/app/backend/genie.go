package main

// GenieRunner executes Llama 3.2 3B on the QIDK HTP (NPU) via Qualcomm's genie-t2t-run, locally on the
// device (no adb hop). One NPU job at a time (single-flight mutex); callers queue.

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

type ModelBundle struct {
	Name      string `json:"name"`
	Dir       string `json:"dir"`
	Config    string `json:"config"`
	FineTuned bool   `json:"fine_tuned"`
	Available bool   `json:"available"`
	Note      string `json:"note"`
}

type GenieResult struct {
	Text         string  `json:"text"`
	LatencyMs    float64 `json:"latency_ms"`
	TTFTMs       float64 `json:"ttft_ms"`
	GenTokens    int     `json:"gen_tokens"`
	TokensPerS   float64 `json:"tokens_per_s"`
	EarlyStopped bool    `json:"early_stopped"`
	Cached       bool    `json:"cached"`
	Retried      bool    `json:"retried"`
	Retries      int     `json:"retries,omitempty"`
	Model        string  `json:"model"`
	FineTuned    bool    `json:"fine_tuned"`
	Backend      string  `json:"backend"`
	Error        string  `json:"error,omitempty"`
	// Prefetched marks a result that was produced by a batched NPU run earlier in this same
	// incident (see genieapp.go). It lives in the prompt cache like any other entry, but it is a
	// real NPU call for this window, not a reused answer, so Run must not report it as Cached.
	Prefetched bool `json:"-"`
	// Streamed: the batch already sent this answer to the dashboard token by token (Prefetch with
	// an onToken sink), so Run must not send it a second time when it picks the answer up.
	Streamed bool `json:"-"`
}

type GenieRunner struct {
	mu        sync.Mutex
	runtime   string // dir holding genie-t2t-run-2.50 and QAIRT libs
	binary    string
	promptDir string
	mock      bool
	busy      atomic.Bool
	queue     atomic.Int32
	calls     atomic.Int64
	errorsN   atomic.Int64
	lastMs    atomic.Int64
	lastErr   atomic.Value
	Base      ModelBundle
	Tuned     ModelBundle
	lastEnd   time.Time // when the previous Genie process exited (guarded by mu)
	lastDir   string    // bundle used by the previous call (guarded by mu)
	cacheMu   sync.Mutex
	cache     map[[32]byte]GenieResult
	cacheKeys [][32]byte
}

// Exact-prompt result cache. Decoding is greedy (temp 0, top-k 1), so an identical prompt on the same
// bundle always yields the identical answer: reusing it has zero accuracy cost (e.g. Compare reruns,
// re-analysing an unchanged window).
const cacheSize = 128

func (g *GenieRunner) cacheGet(k [32]byte) (GenieResult, bool) {
	g.cacheMu.Lock()
	defer g.cacheMu.Unlock()
	r, ok := g.cache[k]
	return r, ok
}

func (g *GenieRunner) cachePut(k [32]byte, r GenieResult) {
	g.cacheMu.Lock()
	defer g.cacheMu.Unlock()
	if g.cache == nil {
		g.cache = map[[32]byte]GenieResult{}
	}
	if _, ok := g.cache[k]; !ok {
		g.cacheKeys = append(g.cacheKeys, k)
		if len(g.cacheKeys) > cacheSize {
			delete(g.cache, g.cacheKeys[0])
			g.cacheKeys = g.cacheKeys[1:]
		}
	}
	g.cache[k] = r
}

// Forget drops a prompt's cached answer, so the next Run of it goes to the NPU again (a solo re-run
// of an invalid batched answer must not get the same answer back from the cache).
func (g *GenieRunner) Forget(b ModelBundle, prompt string) {
	ck := sha256.Sum256([]byte(b.Dir + "|" + b.Config + "|" + prompt))
	g.cacheMu.Lock()
	defer g.cacheMu.Unlock()
	if _, ok := g.cache[ck]; !ok {
		return
	}
	delete(g.cache, ck)
	for i, k := range g.cacheKeys {
		if k == ck {
			g.cacheKeys = append(g.cacheKeys[:i], g.cacheKeys[i+1:]...)
			break
		}
	}
}

// transientHTP reports errors where the HTP refused to set up a session (DSP-side allocation or device
// creation), as opposed to the model producing bad output. Only these are retried.
func transientHTP(err error) bool {
	m := err.Error()
	for _, k := range []string{"create context", "err 1002", "Failed to create device", "Failed to free device", "dspservice", "remote_handle"} {
		if strings.Contains(m, k) {
			return true
		}
	}
	return false
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func NewGenieRunner(runtimeDir, workDir string, mock bool) *GenieRunner {
	bin := filepath.Join(runtimeDir, "genie-t2t-run-2.50")
	if v := os.Getenv("SCE_GENIE_BIN"); v != "" { // Android app: binary packaged as a native lib
		bin = v
	}
	g := &GenieRunner{runtime: runtimeDir, binary: bin,
		promptDir: filepath.Join(workDir, "state", "prompts"), mock: mock}
	os.MkdirAll(g.promptDir, 0o755)
	g.lastErr.Store("")
	g.Base = ModelBundle{Name: "Llama 3.2 3B Instruct (base, w4a16)", Dir: runtimeDir, Config: "smartcity_agent.json"}
	g.Tuned = ModelBundle{Name: "Llama 3.2 3B smart-city agent (fine-tuned, w4a16)", Dir: filepath.Join(filepath.Dir(runtimeDir), "genie_bundle_ft"),
		Config: "smartcity_agent.json", FineTuned: true}
	g.Refresh()
	return g
}

// Refresh checks which bundles are present on disk. The tuned bundle is used only if all its context
// binaries and its config exist and it passed the smoke test marker written by deploy (OK file).
func (g *GenieRunner) Refresh() {
	if g.mock {
		g.Base.Available, g.Base.Note = true, "mock backend (no device)"
		g.Tuned.Available, g.Tuned.Note = false, "mock"
		return
	}
	g.Base.Available = fileExists(g.binary) && fileExists(filepath.Join(g.Base.Dir, g.Base.Config))
	if !g.Base.Available {
		g.Base.Note = "missing genie binary or smartcity_agent.json in " + g.Base.Dir
	} else {
		g.Base.Note = "on-device NPU (HTP V75)"
	}
	ok := fileExists(filepath.Join(g.Tuned.Dir, g.Tuned.Config)) && fileExists(filepath.Join(g.Tuned.Dir, "VALIDATED"))
	for i := 1; i <= 3 && ok; i++ {
		ok = fileExists(filepath.Join(g.Tuned.Dir, fmt.Sprintf("llama_v3_2_3b_instruct_part_%d_of_3.bin", i)))
	}
	g.Tuned.Available = ok
	if ok {
		g.Tuned.Note = "fine-tuned bundle validated on device"
	} else {
		g.Tuned.Note = "not deployed yet: falling back to base model for agents"
	}
}

func fileExists(p string) bool { _, err := os.Stat(p); return err == nil }

// AgentModel returns the bundle used for domain agents (tuned if available, else base).
func (g *GenieRunner) AgentModel() ModelBundle {
	if g.Tuned.Available {
		return g.Tuned
	}
	return g.Base
}

// Run executes one prompt. prefill = text already placed at the start of the assistant turn (part of
// prompt); onToken receives generated text chunks as Genie streams them. Generation is stopped as soon as
// the JSON object opened by the prefill is complete (EarlyStop), which removes post-JSON rambling.
func (g *GenieRunner) Run(ctx context.Context, b ModelBundle, prompt, prefill string, timeout time.Duration, onToken func(string)) GenieResult {
	ck := sha256.Sum256([]byte(b.Dir + "|" + b.Config + "|" + prompt))
	if hit, ok := g.cacheGet(ck); ok {
		if hit.Prefetched {
			// answered by this incident's batch: keep its real timings, and drop the mark so a
			// genuine repeat of the same prompt later still counts as a cache hit
			streamed := hit.Streamed
			hit.Prefetched, hit.Streamed = false, false
			g.cachePut(ck, hit)
			if onToken != nil && !streamed {
				onToken(hit.Text)
			}
			return hit
		}
		hit.Cached, hit.LatencyMs = true, 0
		if onToken != nil {
			onToken(hit.Text)
		}
		return hit
	}
	g.queue.Add(1)
	g.mu.Lock()
	g.queue.Add(-1)
	g.busy.Store(true)
	defer func() { g.lastEnd = time.Now(); g.busy.Store(false); g.mu.Unlock() }()
	// The gap exists because of a measurement from 2026-10-07: a Genie session started < 0.5 s after
	// the previous one exited overlapped the previous session's HTP teardown and decoded at ~9 tok/s
	// instead of ~19. That was the BASE model, 200-token generations, and before
	// "allow-async-init": true was added to the config.
	//
	// Re-measured 2026-10-14 on the fine-tuned bundle, two passes with the gaps in ascending and then
	// descending order (so temperature drift could not favour one end), 10 samples:
	//
	//   gap   0.0s   0.2s   0.3s   0.4s   0.6s   1.0s
	//   up    22.53  22.20  21.94  22.31  22.31  22.29   tok/s on the SECOND call
	//   down  22.43    -    22.42    -    22.44  22.10
	//
	// The cliff is gone - even back-to-back with no gap at all. Init is slightly LOWER back-to-back
	// (586-631 ms vs the usual ~690). So 600 ms was costing us that much per extra NPU call for
	// nothing. Dropped to 250 ms rather than 0: the regression if this is ever wrong is decode
	// halving, which is far worse than 250 ms, and nothing was measured between 0 and 250.
	//
	// The bundle-change gap is NOT reduced: that one guards a different failure (loading a different
	// set of context binaries straight after a teardown intermittently fails with "Could not create
	// context from binary"), which was never re-tested.
	gap := 250 * time.Millisecond
	if g.lastDir != "" && g.lastDir != b.Dir {
		gap = 2500 * time.Millisecond
	} else if htpdEnabled() || daemonUp() {
		// The gap guards against one PROCESS's HTP teardown overlapping the next process's start.
		// genied is one persistent process holding one dialog: there is no teardown between calls,
		// so there is nothing to wait out. The same holds for htpd (one resident process; the CLI is
		// never spawned in htpd mode), where the 250 ms used to land between the agent batch and the
		// synthesizer of every multi-domain incident (proofs/2026-10-21_latency_ladder).
		gap = 0
	}
	if wait := gap - time.Since(g.lastEnd); !g.lastEnd.IsZero() && wait > 0 && !g.mock {
		time.Sleep(wait)
	}
	// Thermal pacing inside an incident. The thermal guard only holds work BETWEEN incidents; a
	// 13-agent chaos incident is one unit of work and drove the NPU junction to 94 C (stress pass 8).
	// At the guard threshold (88 C) we let it cool to 82 C before the next call, at most 15 s per call. This costs latency
	// only at the extreme and never changes what the model sees.
	if !g.mock {
		if _, npu, _ := ThermalHot(); npu >= 88 {
			t := time.Now()
			for npu >= 82 && time.Since(t) < 15*time.Second {
				time.Sleep(time.Second)
				_, npu, _ = ThermalHot()
			}
			log.Printf("[GenieRunner] thermal pacing: waited %v for the NPU to cool (now %.0f C)", time.Since(t).Round(100*time.Millisecond), npu)
		}
	}
	g.lastDir = b.Dir
	t0 := time.Now()
	res := GenieResult{Model: b.Name, FineTuned: b.FineTuned, Backend: "qidk_htp"}
	g.calls.Add(1)
	var text string
	var err error
	if g.mock {
		res.Backend = "mock"
		text, err = mockGen(prompt)
		text = strings.TrimPrefix(text, prefill)
		if onToken != nil {
			for _, w := range strings.SplitAfter(text, " ") {
				onToken(w)
				time.Sleep(15 * time.Millisecond)
			}
		}
	} else {
		var st streamStats
		text, st, err = g.exec(ctx, b, prompt, prefill, timeout, onToken)
		// The HTP occasionally refuses a fresh context ("Could not create context from binary", err 1002 =
		// memory allocation on the DSP side). Seen on the QIDK after a reboot / idle period: it clears by
		// itself within ~10 s, so a single 4 s retry was not enough (both attempts failed, error shown as a
		// policy rejection). Retry with backoff; the prompt and model are unchanged, so outputs are identical.
		for attempt, wait := range []time.Duration{3 * time.Second, 7 * time.Second, 15 * time.Second} {
			if err == nil || !transientHTP(err) || ctx.Err() != nil {
				break
			}
			log.Printf("[GenieRunner] NPU context creation failed (attempt %d), retrying in %s", attempt+1, wait)
			select {
			case <-ctx.Done():
			case <-time.After(wait):
			}
			text, st, err = g.exec(ctx, b, prompt, prefill, timeout, onToken)
			res.Retried = true
			res.Retries = attempt + 1
		}
		if err != nil && transientHTP(err) {
			err = fmt.Errorf("NPU unavailable (HTP context allocation failed after %d retries, hardware not model): %w", res.Retries, err)
		}
		res.TTFTMs, res.GenTokens, res.EarlyStopped = st.ttftMs, st.tokens, st.early
		if st.genSec > 0 {
			res.TokensPerS = float64(st.tokens) / st.genSec
		}
	}
	res.LatencyMs = float64(time.Since(t0).Microseconds()) / 1000.0
	g.lastMs.Store(int64(res.LatencyMs))
	res.Text = text
	if err != nil {
		g.errorsN.Add(1)
		res.Error = err.Error()
		g.lastErr.Store(err.Error())
	}
	if res.Error == "" && strings.TrimSpace(res.Text) != "" {
		g.cachePut(ck, res)
	}
	return res
}

type streamStats struct {
	ttftMs, genSec float64
	tokens         int
	early          bool
	trimmed        bool
}

// jsonScanner tracks brace depth outside strings so we know when the answer object is complete.
type jsonScanner struct {
	depth      int
	inStr, esc bool
	started    bool
}

func (j *jsonScanner) feed(s string) (doneAt int) {
	for i := 0; i < len(s); i++ {
		c := s[i]
		if j.inStr {
			if j.esc {
				j.esc = false
			} else if c == '\\' {
				j.esc = true
			} else if c == '"' {
				j.inStr = false
			}
			continue
		}
		switch c {
		case '"':
			j.inStr = true
		case '{':
			j.depth++
			j.started = true
		case '}':
			j.depth--
			if j.started && j.depth == 0 {
				return i + 1
			}
		}
	}
	return -1
}

// trace prints per-stage timings when SCE_GENIE_TRACE=1, for latency debugging only.
func trace(f string, a ...any) {
	if os.Getenv("SCE_GENIE_TRACE") == "1" {
		log.Printf("[trace] "+f, a...)
	}
}

func (g *GenieRunner) exec(ctx context.Context, b ModelBundle, prompt, prefill string, timeout time.Duration, onToken func(string)) (string, streamStats, error) {
	var st streamStats

	// htpd mode: every NPU call goes to the batched llama.cpp engine; never spawn Genie next to it.
	if htpdEnabled() && !g.mock {
		return g.execViaHtpd(ctx, prompt, prefill, timeout, onToken)
	}

	// Fast path: a persistent dialog that has already paid the ~700 ms model init (genieclient.go).
	// Only for the bundle the daemon was started against; anything else, or any failure, falls
	// through to spawning the CLI below, which is exactly the behaviour we had before genied.
	if daemonEnabled() && b.Dir == envOr("SCE_GENIE_DAEMON_BUNDLE", g.Tuned.Dir) {
		var streamed strings.Builder // what the dashboard has already been shown
		tok := onToken
		if onToken != nil {
			tok = func(s string) { streamed.WriteString(s); onToken(s) }
		}
		text, dst, err := g.execViaDaemon(ctx, prompt, prefill, timeout, tok)
		switch {
		case err == nil:
			daemonFailures.Store(0)
			return text, dst, nil
		case errors.Is(err, errDaemonDied) && len(geniedPids()) == 0:
			// genied died mid-answer (crash, OOM kill) and nothing holds the model any more, so the
			// CLI can run this call without a second resident model. Decoding is greedy, so the CLI
			// repeats the same tokens: hold back the part the dashboard already shows.
			trace("daemon died after %d tokens, re-running on the CLI", dst.tokens)
			onToken = skipStreamed(onToken, streamed.Len())
		case dst.tokens > 0:
			// it already streamed part of an answer to the dashboard; re-running on the CLI would
			// emit those tokens a second time, so fail rather than duplicate
			return text, dst, fmt.Errorf("daemon failed mid-answer: %w", err)
		case len(geniedPids()) > 0:
			// genied is resident (alive but failing, or briefly unreachable). Spawning the CLI now
			// would put a SECOND model on the NPU - the configuration that crashed the board - so
			// fail this call instead; the incident falls back to its rule-based report. Two such
			// failures in a row mean it is wedged: kill it and let the supervisor start a clean one.
			if daemonFailures.Add(1) >= 2 {
				killDaemon("2 consecutive calls failed: " + err.Error())
			}
			return "", dst, fmt.Errorf("daemon resident but failed, CLI not started: %w", err)
		default:
			trace("daemon not running, falling back to the CLI: %v", err)
		}
	}

	f := filepath.Join(g.promptDir, fmt.Sprintf("p_%d.txt", time.Now().UnixNano()))
	// Genie's tokenizer adds BOS itself (verified: a prompt starting with <|begin_of_text|> becomes 1 token
	// longer than on the host). Our prompts carry BOS to stay byte-identical to training, so strip it here,
	// otherwise every NPU call sees a double BOS the model never saw in training.
	if err := os.WriteFile(f, []byte(strings.TrimPrefix(prompt, "<|begin_of_text|>")), 0o644); err != nil {
		return "", st, err
	}
	defer os.Remove(f)
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	rt := g.runtime
	cmd := exec.CommandContext(ctx, g.binary, "-c", b.Config, "--prompt_file", f)
	cmd.Dir = b.Dir
	// Same context-window rule as genied: a prompt that would not leave room for a full answer runs
	// on the large-context bundle (same weights, byte-identical outputs) rather than being cut short.
	if b.Dir == g.Tuned.Dir && needsLargeWindow(prompt) {
		if lb := largeBundle(); lb != "" {
			cmd.Dir = lb
			trace("cli: prompt ~%d tokens -> large context window %s", estTokens(prompt), lb)
		}
	}
	cmd.Env = append(os.Environ(),
		"LD_LIBRARY_PATH="+envOr("SCE_GENIE_LD", rt+"/qairt_2_50_libs:"+rt+"/aarch64-android:"+rt),
		"ADSP_LIBRARY_PATH="+envOr("SCE_GENIE_ADSP", rt+"/dsp_2_50;"+rt+"/dsp;"+rt+"/dsp/unsigned;/vendor/dsp/cdsp;/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp;/dsp"))
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return "", st, err
	}
	var stderr strings.Builder
	cmd.Stderr = &stderr
	t0 := time.Now()
	if err := cmd.Start(); err != nil {
		return "", st, err
	}
	var raw strings.Builder
	// every stop decision lives in answerScanner, shared with the daemon path (answerscan.go)
	scan := newAnswerScanner(prefill, onToken)
	// stopGenie ends generation early. SIGINT first so Genie releases the HTP cleanly.
	stopGenie := func() {
		tStop := time.Now()
		cmd.Process.Signal(os.Interrupt)
		go func(p *os.Process) { time.Sleep(1500 * time.Millisecond); p.Kill() }(cmd.Process)
		io.Copy(io.Discard, stdout)
		trace("earlystop: signal->drain %v", time.Since(tStop))
	}
	begun := false
	var firstTok time.Time
	buf := make([]byte, 512)
	for {
		n, rerr := stdout.Read(buf)
		if n > 0 {
			chunk := string(buf[:n])
			raw.WriteString(chunk)
			if !begun {
				all := raw.String()
				if i := strings.Index(all, "[BEGIN]:"); i >= 0 {
					begun = true
					chunk = strings.TrimLeft(all[i+len("[BEGIN]:"):], " ")
				} else {
					chunk = ""
				}
			}
			if begun && chunk != "" {
				if strings.Contains(chunk, "[END]") {
					chunk = chunk[:strings.Index(chunk, "[END]")]
				}
				if firstTok.IsZero() && strings.TrimSpace(chunk) != "" {
					firstTok = time.Now()
					st.ttftMs = float64(firstTok.Sub(t0).Microseconds()) / 1000
				}
				st.tokens++
				if scan.feed(chunk) {
					st.early = true
					st.trimmed = scan.Trimmed
					stopGenie()
					break
				}
			}
		}
		if rerr != nil {
			break
		}
	}
	tWait := time.Now()
	werr := cmd.Wait()
	trace("cmd.Wait %v | total exec %v | ttft %.0fms tokens %d", time.Since(tWait), time.Since(t0), st.ttftMs, st.tokens)
	if !firstTok.IsZero() {
		st.genSec = time.Since(firstTok).Seconds()
	}
	final := scan.Done() // releases whatever the holdback was still sitting on
	if ctx.Err() == context.DeadlineExceeded {
		return final, st, fmt.Errorf("genie timeout after %s", timeout)
	}
	if !begun {
		tail := raw.String() + stderr.String()
		if len(tail) > 400 {
			tail = tail[len(tail)-400:]
		}
		return "", st, fmt.Errorf("genie failed: %v: %s", werr, tail)
	}
	out := strings.TrimSpace(final)
	if i := strings.Index(out, "[END"); i >= 0 {
		out = strings.TrimSpace(out[:i])
	}
	return out, st, nil
}

type NPUStatus struct {
	Busy          bool   `json:"busy"`
	Queue         int32  `json:"queue"`
	Calls         int64  `json:"calls"`
	Errors        int64  `json:"errors"`
	LastLatencyMs int64  `json:"last_latency_ms"`
	LastError     string `json:"last_error"`
}

func (g *GenieRunner) Status() NPUStatus {
	return NPUStatus{Busy: g.busy.Load(), Queue: g.queue.Load(), Calls: g.calls.Load(), Errors: g.errorsN.Load(),
		LastLatencyMs: g.lastMs.Load(), LastError: g.lastErr.Load().(string)}
}

// mockGen answers in mock mode; tests swap it for scripted agents (refine_test.go).
var mockGen = mockGenerate

// mockGenerate is only for laptop development without a device; never used on the QIDK.
func mockGenerate(prompt string) (string, error) {
	time.Sleep(400 * time.Millisecond)
	if strings.Contains(prompt, "cross-domain") {
		return `{"root_cause": "mock synthesis", "label": "unknown", "affected_domains": [], "evidence": ["S1.E1"], "confidence": 0.5, "action": "monitor", "explanation": "mock"}`, nil
	}
	return `{"pattern": "stable", "status": "normal", "observations": ["mock [E1]"], "likely_cause": "sensor_fault", "confidence": 0.5, "action": "monitor"}`, nil
}
