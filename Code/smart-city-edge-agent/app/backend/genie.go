package main

// GenieRunner executes Llama 3.2 3B on the QIDK HTP (NPU) via Qualcomm's genie-t2t-run, locally on the
// device (no adb hop). One NPU job at a time (single-flight mutex); callers queue.

import (
	"context"
	"crypto/sha256"
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
	// Measured on the QIDK: a Genie session started < 0.5 s after the previous one exits overlaps the
	// previous session's HTP teardown and decodes at ~9 tok/s instead of ~19 tok/s. Keep a 0.6 s gap,
	// and a longer one when the model bundle changes: loading a different set of context binaries
	// straight after a teardown intermittently fails with "Could not create context from binary".
	gap := 600 * time.Millisecond
	if g.lastDir != "" && g.lastDir != b.Dir {
		gap = 2500 * time.Millisecond
	}
	if wait := gap - time.Since(g.lastEnd); !g.lastEnd.IsZero() && wait > 0 && !g.mock {
		time.Sleep(wait)
	}
	g.lastDir = b.Dir
	t0 := time.Now()
	res := GenieResult{Model: b.Name, FineTuned: b.FineTuned, Backend: "qidk_htp"}
	g.calls.Add(1)
	var text string
	var err error
	if g.mock {
		res.Backend = "mock"
		text, err = mockGenerate(prompt)
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

func (g *GenieRunner) exec(ctx context.Context, b ModelBundle, prompt, prefill string, timeout time.Duration, onToken func(string)) (string, streamStats, error) {
	var st streamStats
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
	// the JSON object starts inside the prefill (assistant turn already contains `{"pattern": "`)
	var js jsonScanner
	js.feed(prefill)
	var raw, gen strings.Builder
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
				if at := js.feed(chunk); at >= 0 && prefill != "" {
					gen.WriteString(chunk[:at])
					st.tokens++
					if onToken != nil {
						onToken(chunk[:at])
					}
					st.early = true
					// answer complete: stop generating (SIGINT first so Genie can release the HTP cleanly)
					cmd.Process.Signal(os.Interrupt)
					go func(p *os.Process) { time.Sleep(1500 * time.Millisecond); p.Kill() }(cmd.Process)
					io.Copy(io.Discard, stdout)
					break
				}
				gen.WriteString(chunk)
				st.tokens++
				if onToken != nil {
					onToken(chunk)
				}
			}
		}
		if rerr != nil {
			break
		}
	}
	werr := cmd.Wait()
	if !firstTok.IsZero() {
		st.genSec = time.Since(firstTok).Seconds()
	}
	if ctx.Err() == context.DeadlineExceeded {
		return gen.String(), st, fmt.Errorf("genie timeout after %s", timeout)
	}
	if !begun {
		tail := raw.String() + stderr.String()
		if len(tail) > 400 {
			tail = tail[len(tail)-400:]
		}
		return "", st, fmt.Errorf("genie failed: %v: %s", werr, tail)
	}
	out := strings.TrimSpace(gen.String())
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

// mockGenerate is only for laptop development without a device; never used on the QIDK.
func mockGenerate(prompt string) (string, error) {
	time.Sleep(400 * time.Millisecond)
	if strings.Contains(prompt, "cross-domain") {
		return `{"root_cause": "mock synthesis", "label": "unknown", "affected_domains": [], "evidence": ["S1.E1"], "confidence": 0.5, "action": "monitor", "explanation": "mock"}`, nil
	}
	return `{"pattern": "stable", "status": "normal", "observations": ["mock [E1]"], "likely_cause": "sensor_fault", "confidence": 0.5, "action": "monitor"}`, nil
}
