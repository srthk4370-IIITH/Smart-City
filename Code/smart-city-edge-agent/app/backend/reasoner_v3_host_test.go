package main

// Host harness for the v3 reasoner (proofs/2026-10-26_reasoner_deploy/run_host_harness.sh). Skipped unless
// SCE_REASONER_HOST_URL points at a llama-server serving the reasoner GGUF (CPU is enough). It drives the real
// backend path (RenderV3User input from the dev set, reasonerPromptV3, runV3Loop with the cap, checkReportV3)
// and writes one JSON line per item: gate result, completions, tool calls, tokens, latency.
//
//	SCE_REASONER_HOST_URL=http://127.0.0.1:8092 SCE_REASONER_HOST_DATA=<dev .ok.jsonl> \
//	SCE_REASONER_HOST_OUT=<out.jsonl> SCE_REASONER_HOST_N=20 go test -run TestReasonerV3Host -timeout 0 .

import (
	"bufio"
	"context"
	"encoding/json"
	"os"
	"strconv"
	"strings"
	"testing"
)

// replayTools answers with the example's own tool results in order (the gold trace), then "not available".
type replayTools struct{ queue *[]string }

func (t replayTools) Exec(_ context.Context, _ string, _ map[string]any) string {
	if q := *t.queue; len(q) > 0 {
		*t.queue = q[1:]
		return q[0]
	}
	return `{"error": "not available in the host harness"}`
}

func TestReasonerV3Host(t *testing.T) {
	url := os.Getenv("SCE_REASONER_HOST_URL")
	if url == "" {
		t.Skip("SCE_REASONER_HOST_URL not set")
	}
	data, out := os.Getenv("SCE_REASONER_HOST_DATA"), os.Getenv("SCE_REASONER_HOST_OUT")
	n, _ := strconv.Atoi(os.Getenv("SCE_REASONER_HOST_N"))
	if n <= 0 {
		n = 20
	}
	f, err := os.Open(data)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	w, err := os.Create(out)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close()
	llm := &llamaServerLLM{URL: url, Model: "qwen3.5-4b"}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<26)
	done, valid := 0, 0
	for sc.Scan() && done < n {
		var ex struct {
			ID       string `json:"id"`
			Family   string `json:"family"`
			Tools    string `json:"tools"`
			Messages []struct {
				Role    string `json:"role"`
				Content string `json:"content"`
			} `json:"messages"`
		}
		if json.Unmarshal(sc.Bytes(), &ex) != nil || ex.Tools != "incident" || len(ex.Messages) < 3 {
			continue
		}
		user := ex.Messages[1].Content
		var q []string
		for _, m := range ex.Messages {
			if m.Role == "tool" {
				q = append(q, m.Content)
			}
		}
		rt := replayTools{queue: &q}
		mode := "early"
		if strings.Contains(user, "(mode refine") {
			mode = "refine"
		}
		run, err := runV3Loop(context.Background(), llm, rt, user, reasonerMaxCalls(mode), 700, nil)
		rec := map[string]any{"id": ex.ID, "family": ex.Family, "llm_calls": run.LLMCalls, "tool_calls": len(run.Calls),
			"wanted": run.Wanted, "forced": run.Forced, "gen_tokens": run.Metrics.GenTokens, "ttft_ms": run.Metrics.TTFTMs,
			"latency_ms": run.LatencyMs, "raw": run.Text, "gold": ex.Messages[len(ex.Messages)-1].Content}
		if err != nil {
			rec["error"] = err.Error()
		} else {
			_, errs, _ := checkReportV3(run.Text, run.Prompt+"\n"+strings.Join(run.Results, "\n"))
			rec["gate_errors"] = errs
			if len(errs) == 0 {
				valid++
			}
		}
		b, _ := json.Marshal(rec)
		w.Write(append(b, '\n'))
		done++
	}
	t.Logf("host harness: %d items, %d passed the gate", done, valid)
}

// TestReasonerV3GateOnGold: the gate must accept the training gold answers (false-rejection rate). Skipped unless
// SCE_REASONER_GOLD names a dev/train .ok.jsonl file.
func TestReasonerV3GateOnGold(t *testing.T) {
	path := os.Getenv("SCE_REASONER_GOLD")
	if path == "" {
		t.Skip("SCE_REASONER_GOLD not set")
	}
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<26)
	n, bad := 0, map[string]int{}
	for sc.Scan() {
		var ex struct {
			Tools    string                           `json:"tools"`
			Messages []struct{ Role, Content string } `json:"messages"`
		}
		if json.Unmarshal(sc.Bytes(), &ex) != nil || ex.Tools != "incident" {
			continue
		}
		var known strings.Builder
		for _, m := range ex.Messages[:len(ex.Messages)-1] {
			known.WriteString(m.Content + "\n")
		}
		_, errs, _ := checkReportV3(ex.Messages[len(ex.Messages)-1].Content, known.String())
		n++
		for _, e := range errs {
			k := e
			if i := strings.IndexAny(e, "0123456789\""); i > 0 {
				k = e[:i]
			}
			bad[k]++
		}
		if len(errs) > 0 {
			bad["_rejected"]++
		}
	}
	b, _ := json.Marshal(bad)
	t.Logf("gold answers: %d, gate errors by kind: %s", n, b)
}
