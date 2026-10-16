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

// htpdMaxBatch must match htpd --agents.
const htpdMaxBatch = 13

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
}

func htpdCall(ctx context.Context, kind string, prompts []string, timeout time.Duration) (*htpdResp, error) {
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
	if kind == "agents" {
		req["prompts"] = prompts
	} else {
		req["prompt"] = prompts[0]
	}
	b, _ := json.Marshal(req)
	if _, err := c.Write(append(b, '\n')); err != nil {
		return nil, err
	}
	line, err := bufio.NewReaderSize(c, 1<<20).ReadBytes('\n')
	if err != nil {
		return nil, err
	}
	var r htpdResp
	if err := json.Unmarshal(line, &r); err != nil {
		return nil, err
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
	r, err := htpdCall(ctx, kind, []string{prompt}, timeout)
	if err != nil {
		htpdKill("call failed: " + err.Error())
		return "", st, fmt.Errorf("htpd: %w", err)
	}
	o := r.Outputs[0]
	st.tokens, st.ttftMs = o.Tokens, o.TTFTMs
	st.genSec = (o.Ms - o.TTFTMs) / 1000
	st.early = o.Stop == "json" || o.Stop == "action"
	st.trimmed = o.Stop == "action"
	if onToken != nil {
		onToken(o.Text)
	}
	out := strings.TrimSpace(o.Text)
	if out == "" {
		return "", st, fmt.Errorf("htpd returned no answer (stop=%s)", o.Stop)
	}
	return out, st, nil
}

// prefetchViaHtpd answers every prompt of an incident in batches of up to 13 parallel sequences and
// parks the answers in the prompt cache (same contract as the genie-app Prefetch path).
func (g *GenieRunner) prefetchViaHtpd(ctx context.Context, b ModelBundle, todo []string, at []int, onToken func(int, string)) {
	for start := 0; start < len(todo); start += htpdMaxBatch {
		end := start + htpdMaxBatch
		if end > len(todo) {
			end = len(todo)
		}
		t0 := time.Now()
		// 13 agents take ~26-36 s; a batch that runs past 150 s is a stalled engine (seen once at 91 C)
		r, err := htpdCall(ctx, "agents", todo[start:end], 150*time.Second)
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
			res := GenieResult{Text: text, Model: b.Name, FineTuned: b.FineTuned, Backend: "qidk_htp_llamacpp_batched",
				LatencyMs: o.Ms, TTFTMs: o.TTFTMs, GenTokens: o.Tokens, EarlyStopped: o.Stop == "json" || o.Stop == "action",
				Prefetched: true}
			if o.Ms > o.TTFTMs && o.Tokens > 0 {
				res.TokensPerS = float64(o.Tokens) / ((o.Ms - o.TTFTMs) / 1000)
			}
			g.cachePut(sha256Key(b, todo[start+k]), res)
			g.calls.Add(1)
			if onToken != nil {
				onToken(at[start+k], text)
			}
		}
		g.lastMs.Store(int64(wall))
		trace("Prefetch(htpd): %d agents in one batch, %.0f ms (prefill %.0f ms)", end-start, wall, r.PrefillMs)
	}
}

// superviseHtpd starts htpd (and keeps genied stopped) when htpd mode is selected.
func superviseHtpd(g *GenieRunner, workDir string) {
	bin := envOr("SCE_HTPD_BIN", "/data/local/tmp/llama.cpp/bin/htpd")
	model := envOr("SCE_HTPD_MODEL", "/data/local/tmp/gpu/ft_device_q4exact.gguf")
	if _, err := os.Stat(bin); err != nil {
		log.Printf("htpd: not installed at %s - staying on genied", bin)
		return
	}
	lib := filepath.Join(filepath.Dir(filepath.Dir(bin)), "lib")
	start := func() {
		if htpdUp() {
			return
		}
		// never two models on the NPU: genied must be gone before htpd loads
		killDaemon("htpd mode selected")
		time.Sleep(time.Second)
		args := []string{"-m", model, "--agents", fmt.Sprint(htpdMaxBatch), "--agent-ctx", "768",
			"--synth-ctx", "4096", "--ubatch", "512", "--ubatch-synth", "512", "--port", strings.Split(htpdAddr(), ":")[1]}
		cmd := exec.Command(bin, args...)
		cmd.Env = append(os.Environ(), "LD_LIBRARY_PATH="+lib, "ADSP_LIBRARY_PATH="+lib,
			"GGML_HEXAGON_FA_STREAMS=1", "HTPD_SPEC=0",
			// measured 2026-10-16: pipelined HMX for decode-sized matmuls + parked finished streams
			// (htpd default) cut a 13-agent batch from ~28-31 s to ~24 s with identical outputs; the
			// equal-ubatch prefill (HTPD_LEGACY_PREFILL unset) changed ~30% of outputs for no gain
			"GGML_HEXAGON_HMX_PIPE_ALL=1", "HTPD_LEGACY_PREFILL=1",
			// batched verified drafting, adaptive k (<= 4 per stream, rows <= 32): 13 agents 22 -> 16.4 s,
			// 4 agents 14.9 -> 5.8 s, outputs identical to plain greedy (25/25, 2026-10-16)
			"HTPD_DRAFT=1",
			// cross-incident KV cache of each role's system-prompt prefix: prefill 8.7 -> 6.8 s (13 agents),
			// 3.1 -> 2.0 s (4 agents); 54-window accuracy unchanged or better (2026-10-16)
			"HTPD_PREFIX_CACHE=1")
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
		for i := 0; i < 60 && !htpdUp(); i++ {
			time.Sleep(250 * time.Millisecond)
		}
		log.Printf("htpd: started (pid %d), up=%v", cmd.Process.Pid, htpdUp())
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

func sha256Key(b ModelBundle, prompt string) [32]byte {
	return sha256.Sum256([]byte(b.Dir + "|" + b.Config + "|" + prompt))
}

// htpdKill stops a stalled or failing htpd so the supervisor starts a clean one (within 15 s).
func htpdKill(why string) {
	ents, _ := os.ReadDir("/proc")
	for _, e := range ents {
		b, err := os.ReadFile("/proc/" + e.Name() + "/comm")
		if err != nil || strings.TrimSpace(string(b)) != "htpd" {
			continue
		}
		var pid int
		if _, err := fmt.Sscan(e.Name(), &pid); err == nil {
			log.Printf("htpd: killing pid %d (%s)", pid, why)
			syscall.Kill(pid, syscall.SIGKILL)
		}
	}
}
