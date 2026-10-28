package main

// Token streaming end to end without a device: a fake htpd speaking the real line protocol
// (htpd.cpp header) with and without the proposed "stream":true progress lines
// (proofs/2026-10-21_v2_research/streaming/htpd_stream_protocol.md), the htpd client, Prefetch/Run,
// the reasoner's sinks and the SSE hub.

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"math"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"testing"
	"time"
	"unicode/utf8"
)

type fakeHtpd struct {
	addr      string
	stream    bool          // honour "stream":true
	stepForm  bool          // per-step {"kind":"toks"} lines instead of {"kind":"tok"} lines
	prefill   time.Duration // before the first token
	step      time.Duration // per decode step
	mu        sync.Mutex
	requests  []map[string]any
	answerFor func(kind, prompt string) string // raw continuation after the prefill
}

// fakeAnswer: what the model would generate after the prefill, including the action key that
// htpd's stop rule cuts away for agents.
func fakeAnswer(kind, prompt string) string {
	if kind == "agents" {
		n := len(prompt) % 7
		return fmt.Sprintf(`stable", "status": "normal", "observations": ["reading %d stays flat [E1]", "no step °C [E2]"], "likely_cause": "normal_conditions", "confidence": 0.9, "action": "none"}`, n)
	}
	return `mock synthesis", "label": "unknown", "affected_domains": [], "evidence": ["S1.E1"], "confidence": 0.5, "action": "monitor", "explanation": "mock report streamed"}`
}

// htpdFinal applies htpd's stop rule to a raw continuation: agents stop when the "action" key
// closes (text cut at the comma before it, then '}'), reports when the object closes.
func htpdFinal(kind, raw string) (final string, streamed string) {
	if kind == "agents" {
		i := strings.Index(raw, `"action"`)
		j := strings.LastIndex(raw[:i], ",")
		return raw[:j] + "}", raw[:i+len(`"action"`)]
	}
	return raw, raw
}

func pieces(s string, n int) []string {
	var out []string
	r := []rune(s)
	for i := 0; i < len(r); i += n {
		e := i + n
		if e > len(r) {
			e = len(r)
		}
		out = append(out, string(r[i:e]))
	}
	return out
}

func startFakeHtpd(t *testing.T, f *fakeHtpd) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	f.addr = ln.Addr().String()
	if f.answerFor == nil {
		f.answerFor = fakeAnswer
	}
	t.Cleanup(func() { ln.Close() })
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			go f.serve(c)
		}
	}()
}

func (f *fakeHtpd) serve(c net.Conn) {
	defer c.Close()
	rd := bufio.NewReaderSize(c, 1<<20)
	for {
		line, err := rd.ReadBytes('\n')
		if err != nil {
			return
		}
		var req map[string]any
		json.Unmarshal(line, &req)
		f.mu.Lock()
		f.requests = append(f.requests, req)
		f.mu.Unlock()
		kind, _ := req["kind"].(string)
		var prompts []string
		if kind == "agents" {
			for _, p := range req["prompts"].([]any) {
				prompts = append(prompts, p.(string))
			}
		} else {
			prompts = []string{req["prompt"].(string)}
		}
		stream := f.stream && req["stream"] == true
		t0 := time.Now()
		time.Sleep(f.prefill)
		type st struct {
			ps    []string
			final string
			ttft  float64
			ms    float64
		}
		ss := make([]st, len(prompts))
		steps := 0
		for i, p := range prompts {
			final, streamed := htpdFinal(kind, f.answerFor(kind, p))
			ss[i] = st{ps: pieces(streamed, 3+i%3), final: final}
			if len(ss[i].ps) > steps {
				steps = len(ss[i].ps)
			}
		}
		w := bufio.NewWriter(c)
		for k := 0; k < steps; k++ {
			step := make([]string, len(ss))
			for i := range ss {
				if k < len(ss[i].ps) {
					step[i] = ss[i].ps[k]
					if k == 0 {
						ss[i].ttft = float64(time.Since(t0).Microseconds()) / 1000
					}
					if k == len(ss[i].ps)-1 {
						ss[i].ms = float64(time.Since(t0).Microseconds()) / 1000
					}
				}
			}
			if stream {
				if f.stepForm {
					b, _ := json.Marshal(map[string]any{"kind": "toks", "t": step})
					w.Write(append(b, '\n'))
				} else {
					for i, p := range step {
						if p != "" {
							b, _ := json.Marshal(map[string]any{"kind": "tok", "i": i, "t": p})
							w.Write(append(b, '\n'))
						}
					}
				}
				w.Flush()
			}
			time.Sleep(f.step)
		}
		var outs []htpdOut
		for _, s := range ss {
			stop := "json"
			if kind == "agents" {
				stop = "action"
			}
			outs = append(outs, htpdOut{Text: s.final, Tokens: len(s.ps), TTFTMs: s.ttft, Ms: s.ms, Stop: stop})
		}
		b, _ := json.Marshal(htpdResp{Outputs: outs, PrefillMs: float64(f.prefill.Milliseconds()), TotalMs: float64(time.Since(t0).Milliseconds())})
		w.Write(append(b, '\n'))
		w.Flush()
	}
}

type chunkRec struct {
	at   time.Duration
	k    int
	text string
}

func htpdTestRunner(t *testing.T, f *fakeHtpd) *GenieRunner {
	t.Helper()
	startFakeHtpd(t, f)
	t.Setenv("SCE_NPU_ENGINE", "htpd")
	t.Setenv("SCE_HTPD", f.addr)
	t.Setenv("SCE_GENIE_BATCH", "")
	cool := filepath.Join(t.TempDir(), "thermal")
	os.WriteFile(cool, []byte("cool"), 0o644)
	t.Setenv("SCE_THERMAL_FAKE", cool)
	dir := t.TempDir()
	return NewGenieRunner(dir, dir, false)
}

// runPrefetch batches n agent prompts, then picks every answer up through Run like runAgent does.
func runPrefetch(t *testing.T, f *fakeHtpd, n int) (recs []chunkRec, batch time.Duration, finals []string, runEmits int) {
	g := htpdTestRunner(t, f)
	b := g.AgentModel()
	prompts := make([]string, n)
	for i := range prompts {
		prompts[i] = fmt.Sprintf("agent prompt %d %s", i, strings.Repeat("x", i)) + AgentPrefill
	}
	var mu sync.Mutex
	t0 := time.Now()
	g.Prefetch(context.Background(), b, prompts, AgentPrefill, func(k int, s string) {
		mu.Lock()
		recs = append(recs, chunkRec{time.Since(t0), k, s})
		mu.Unlock()
	})
	batch = time.Since(t0)
	for _, p := range prompts {
		res := g.Run(context.Background(), b, p, AgentPrefill, 5*time.Second, func(string) { runEmits++ })
		if res.Error != "" {
			t.Fatal(res.Error)
		}
		finals = append(finals, res.Text)
	}
	return
}

func joinStream(recs []chunkRec, k int) string {
	var sb strings.Builder
	for _, r := range recs {
		if r.k == k {
			sb.WriteString(r.text)
		}
	}
	return sb.String()
}

func firstAt(recs []chunkRec, k int) time.Duration {
	for _, r := range recs {
		if r.k == k {
			return r.at
		}
	}
	return -1
}

func TestHtpdStreamingBatch(t *testing.T) {
	for _, stepForm := range []bool{false, true} {
		t.Run(fmt.Sprintf("stepForm=%v", stepForm), func(t *testing.T) {
			f := &fakeHtpd{stream: true, stepForm: stepForm, prefill: 150 * time.Millisecond, step: 8 * time.Millisecond}
			recs, batch, finals, runEmits := runPrefetch(t, f, 6)
			if f.requests[0]["stream"] != true {
				t.Fatalf("client did not ask htpd to stream: %v", f.requests[0])
			}
			for k := range finals {
				got := joinStream(recs, k)
				if got != finals[k] {
					t.Fatalf("stream %d: streamed text != final answer\n got %q\nwant %q", k, got, finals[k])
				}
				if strings.Contains(got, "action") {
					t.Fatalf("stream %d showed the trimmed action key: %q", k, got)
				}
				if ft := firstAt(recs, k); ft > batch/2 {
					t.Fatalf("stream %d first token at %v of a %v batch: not streaming", k, ft, batch)
				}
			}
			if runEmits != 0 {
				t.Fatalf("Run replayed %d already streamed answers (duplicated text on the dashboard)", runEmits)
			}
			if len(recs) < 6*10 {
				t.Fatalf("only %d chunks for 6 streams", len(recs))
			}
		})
	}
}

func TestHtpdNonStreamingStillWorks(t *testing.T) {
	f := &fakeHtpd{stream: false, prefill: 100 * time.Millisecond, step: 5 * time.Millisecond}
	recs, _, finals, runEmits := runPrefetch(t, f, 4)
	if len(recs) != 4 {
		t.Fatalf("old htpd: want one whole-answer chunk per agent, got %d", len(recs))
	}
	for k := range finals {
		if joinStream(recs, k) != finals[k] {
			t.Fatalf("stream %d text mismatch", k)
		}
	}
	if runEmits != 0 {
		t.Fatalf("Run replayed %d answers already sent by the batch", runEmits)
	}
}

func TestHtpdSynthStreams(t *testing.T) {
	for _, on := range []bool{true, false} {
		f := &fakeHtpd{stream: on, prefill: 80 * time.Millisecond, step: 5 * time.Millisecond}
		g := htpdTestRunner(t, f)
		var chunks []string
		var first, last time.Duration = -1, 0
		t0 := time.Now()
		res := g.Run(context.Background(), g.AgentModel(), "synth prompt"+ReportPrefill, ReportPrefill, 5*time.Second, func(s string) {
			if first < 0 {
				first = time.Since(t0)
			}
			last = time.Since(t0)
			chunks = append(chunks, s)
		})
		if res.Error != "" {
			t.Fatal(res.Error)
		}
		if strings.TrimSpace(strings.Join(chunks, "")) != res.Text {
			t.Fatalf("stream=%v: streamed %q != result %q", on, strings.Join(chunks, ""), res.Text)
		}
		// ~49 pieces x 5 ms: a streamed report spreads over >= 150 ms, a buffered one arrives at once
		if on && (len(chunks) < 10 || last-first < 150*time.Millisecond) {
			t.Fatalf("synth did not stream: %d chunks between %v and %v", len(chunks), first, last)
		}
		if !on && len(chunks) != 1 {
			t.Fatalf("old htpd: want 1 chunk, got %d", len(chunks))
		}
	}
}

// ------------------------------------------------------------------ SSE

type sseEvent struct {
	at   time.Duration
	kind string
	data map[string]any
}

func readSSE(t *testing.T, url string, until func([]sseEvent) bool) (evs []sseEvent) {
	t.Helper()
	resp, err := http.Get(url)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	rd := bufio.NewReader(resp.Body)
	t0 := time.Now()
	kind := ""
	for !until(evs) {
		line, err := rd.ReadString('\n')
		if err != nil {
			t.Fatal(err)
		}
		line = strings.TrimRight(line, "\n")
		switch {
		case strings.HasPrefix(line, "event: "):
			kind = line[7:]
		case strings.HasPrefix(line, "data: "):
			var m map[string]any
			json.Unmarshal([]byte(line[6:]), &m)
			evs = append(evs, sseEvent{time.Since(t0), kind, m})
		}
	}
	return
}

func TestHubTokenOrderAndResync(t *testing.T) {
	h := NewHub()
	srv := httptest.NewServer(h)
	defer srv.Close()
	ready := make(chan struct{})
	var evs []sseEvent
	done := make(chan struct{})
	go func() {
		defer close(done)
		evs = readSSE(t, srv.URL, func(e []sseEvent) bool {
			select {
			case <-ready:
			default:
				close(ready)
			}
			return len(e) >= 301
		})
	}()
	// the subscriber is registered once ": connected" was written; wait until it is in subs
	for i := 0; i < 200; i++ {
		h.mu.Lock()
		n := len(h.subs)
		h.mu.Unlock()
		if n > 0 {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	want := map[string]string{}
	refs := []string{"S1", "S2", "S3"}
	sinks := map[string]bool{}
	for i := 0; i < 300; i++ {
		ref := refs[i%3]
		m := map[string]any{"incident": "INC-1", "ref": ref, "text": fmt.Sprintf("<%d>", i)}
		if !sinks[ref] {
			m["reset"], sinks[ref] = true, true
		}
		if i == 150 { // S1 re-run: a new sink resets its text
			m["reset"], want["S1"] = true, ""
		}
		want[ref] += m["text"].(string)
		h.Publish("token", m)
	}
	h.Publish("incident", map[string]any{"id": "INC-1", "state": "done"})
	<-done
	seq := map[string]float64{}
	got := map[string]string{}
	for i, e := range evs[:300] {
		if e.kind != "token" || e.data["text"] != fmt.Sprintf("<%d>", i) {
			t.Fatalf("event %d out of order: %s %v", i, e.kind, e.data)
		}
		ref := e.data["ref"].(string)
		if e.data["reset"] == true {
			seq[ref], got[ref] = 0, ""
		}
		if e.data["seq"].(float64) != seq[ref]+1 {
			t.Fatalf("event %d: seq %v after %v", i, e.data["seq"], seq[ref])
		}
		seq[ref]++
		got[ref] += e.data["text"].(string)
	}
	if evs[300].kind != "incident" {
		t.Fatalf("incident event not last: %s", evs[300].kind)
	}
	st := h.Streams("INC-1")
	for _, s := range st["streams"].([]liveStream) {
		if s.Text != want[s.Ref] || s.Text != got[s.Ref] || float64(s.Seq) != seq[s.Ref] {
			t.Fatalf("/api/streams %s: %q seq %d, events gave %q seq %v", s.Ref, s.Text, s.Seq, got[s.Ref], seq[s.Ref])
		}
	}
}

// ------------------------------------------------------------------ the whole pipeline

type e2eStats struct {
	Mode              string             `json:"mode"`
	Agents            int                `json:"agents"`
	PrefillMs         float64            `json:"fake_prefill_ms"`
	StepMs            float64            `json:"fake_step_ms"`
	FirstTokenMs      float64            `json:"first_visible_token_ms"`
	AgentFirstMs      map[string]float64 `json:"agent_first_token_ms"`
	AgentLastMs       map[string]float64 `json:"agent_last_token_ms"`
	AgentEvents       map[string]int     `json:"agent_token_events"`
	FinalFirstMs      float64            `json:"report_first_token_ms"`
	FinalEvents       int                `json:"report_token_events"`
	MaxGapMs          float64            `json:"max_gap_between_events_while_generating_ms"`
	MedianGapMs       float64            `json:"median_gap_ms"`
	IncidentMs        float64            `json:"incident_total_ms"`
	LiveMismatches    int                `json:"live_text_mismatches"`
	EventsTotal       int                `json:"token_events_total"`
	BatchEventFirstMs float64            `json:"batch_event_ms"`
}

func pickCandidates(t *testing.T, eng *Engine, n int) []Candidate {
	t.Helper()
	eng.mu.RLock()
	defer eng.mu.RUnlock()
	var keys []string
	for k := range eng.states {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	var out []Candidate
	roles := map[string]int{}
	for _, k := range keys {
		st := eng.states[k]
		if st.Role == "hvac" || st.Role == "weather" || st.Role == "occupancy" || roles[st.Role] >= 2 {
			continue
		}
		xs, ok := eng.Window(st.Node, st.Metric, eng.sim)
		if !ok {
			continue
		}
		f := RuleFinding(st.Role, st.Metric, st.Node, xs, eng.sim)
		f.Status = "warning"
		out = append(out, Candidate{st.Node, st.Metric, st.Role, f, xs, eng.sim, false, false, false})
		roles[st.Role]++
		if len(out) == n {
			break
		}
	}
	return out
}

func runE2E(t *testing.T, stream bool) e2eStats {
	f := &fakeHtpd{stream: stream, stepForm: true, prefill: 300 * time.Millisecond, step: 15 * time.Millisecond}
	g := htpdTestRunner(t, f)
	eng, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	h := NewHub()
	dir := t.TempDir()
	r := NewReasoner(g, eng, dir, h.Publish)
	c := make(chan []byte, 8*hubSubBuf) // ~350 events per incident: never full, so Publish never drops one
	h.mu.Lock()
	h.subs[c] = true
	h.mu.Unlock()
	cands := pickCandidates(t, eng, 4)
	type ev struct {
		at   time.Duration
		kind string
		m    map[string]any
	}
	var evs []ev
	var wg sync.WaitGroup
	wg.Add(1)
	t0 := time.Now()
	go func() {
		defer wg.Done()
		// The hub queue is FIFO: read until the end marker published after Process returns, so every
		// token event is recorded however far this reader lags (a timed stop dropped late events
		// under load: a flaky "live text != answer").
		for b := range c {
			s := string(b)
			kind := strings.TrimPrefix(strings.SplitN(s, "\n", 2)[0], "event: ")
			if kind == "test-end" {
				return
			}
			var m map[string]any
			json.Unmarshal([]byte(strings.TrimSpace(strings.SplitN(strings.SplitN(s, "\n", 2)[1], "data: ", 2)[1])), &m)
			evs = append(evs, ev{time.Since(t0), kind, m})
		}
	}()
	inc := r.Process(cands, 3)
	total := time.Since(t0)
	h.Publish("test-end", map[string]any{})
	wg.Wait()
	ms := func(d time.Duration) float64 { return math.Round(float64(d.Microseconds())/100) / 10 }
	st := e2eStats{Mode: map[bool]string{true: "htpd streams per-step tokens (proposed)", false: "htpd today (result line only)"}[stream],
		PrefillMs: ms(f.prefill), StepMs: ms(f.step), FirstTokenMs: -1, FinalFirstMs: -1, BatchEventFirstMs: -1,
		AgentFirstMs: map[string]float64{}, AgentLastMs: map[string]float64{}, AgentEvents: map[string]int{}, IncidentMs: ms(total)}
	text := map[string]string{}
	var gaps []float64
	var last time.Duration = -1
	for _, e := range evs {
		if e.kind == "batch" && st.BatchEventFirstMs < 0 {
			st.BatchEventFirstMs = ms(e.at)
		}
		if e.kind != "token" {
			continue
		}
		st.EventsTotal++
		ref := e.m["ref"].(string)
		if e.m["reset"] == true {
			text[ref] = ""
		}
		text[ref] += e.m["text"].(string)
		if st.FirstTokenMs < 0 {
			st.FirstTokenMs = ms(e.at)
		}
		if last >= 0 {
			gaps = append(gaps, ms(e.at-last))
		}
		last = e.at
		if ref == "final" {
			st.FinalEvents++
			if st.FinalFirstMs < 0 {
				st.FinalFirstMs = ms(e.at)
			}
			continue
		}
		if _, ok := st.AgentFirstMs[ref]; !ok {
			st.AgentFirstMs[ref] = ms(e.at)
		}
		st.AgentLastMs[ref] = ms(e.at)
		st.AgentEvents[ref]++
	}
	st.Agents = len(st.AgentFirstMs)
	sort.Float64s(gaps)
	if len(gaps) > 0 {
		st.MaxGapMs, st.MedianGapMs = gaps[len(gaps)-1], gaps[len(gaps)/2]
	}
	for _, a := range inc.Agents {
		if strings.HasPrefix(a.Model, "context agent") || strings.HasPrefix(a.Model, "rules") {
			continue
		}
		want := strings.TrimPrefix(a.Raw, AgentPrefill)
		if got := text[a.Ref]; got != want {
			st.LiveMismatches++
			t.Errorf("%s: live text %q != answer %q", a.Ref, got, want)
		}
	}
	if inc.Final != nil && inc.Final.Raw != "" && text["final"] != strings.TrimPrefix(inc.Final.Raw, ReportPrefill) {
		t.Errorf("report live text %q != %q", text["final"], inc.Final.Raw)
	}
	return st
}

func TestStreamingEndToEnd(t *testing.T) {
	t.Setenv("SCE_AGENT_VERSION", "")
	before := runE2E(t, false)
	after := runE2E(t, true)
	for _, s := range []e2eStats{before, after} {
		b, _ := json.MarshalIndent(s, "", "  ")
		t.Logf("%s", b)
	}
	if after.Agents < 2 {
		t.Fatalf("need a batched incident, got %d agents", after.Agents)
	}
	if after.FirstTokenMs <= 0 || after.FirstTokenMs > before.FirstTokenMs*0.8 {
		t.Fatalf("streaming did not bring the first token forward: %v ms vs %v ms", after.FirstTokenMs, before.FirstTokenMs)
	}
	for ref, n := range after.AgentEvents {
		if n < 10 {
			t.Fatalf("%s: %d token events, not streaming", ref, n)
		}
	}
	if after.LiveMismatches+before.LiveMismatches > 0 {
		t.Fatalf("live text on the dashboard differs from the stored answers (duplicated or missing tokens)")
	}
	if dir := os.Getenv("SCE_STREAM_PROOF"); dir != "" {
		b, _ := json.MarshalIndent(map[string]any{"generated": time.Now().Format(time.RFC3339),
			"what":   "fake htpd (same line protocol, scaled-down timings) -> htpd client -> Prefetch/Run -> reasoner sinks -> SSE hub; times from Process start",
			"before": before, "after": after}, "", "  ")
		os.MkdirAll(dir, 0o755)
		os.WriteFile(filepath.Join(dir, "e2e_fake_htpd.json"), b, 0o644)
	}
}

// The answerScanner holdback cuts by bytes, so a chunk can end inside "°"; the sink must publish
// whole characters only (JSON would turn the half into U+FFFD on the dashboard).
func TestTokenSinkWholeUTF8(t *testing.T) {
	var got []string
	r := &Reasoner{notify: func(kind string, v any) { got = append(got, v.(map[string]any)["text"].(string)) }}
	sink := r.tokenSink(&Incident{ID: "INC-1"}, "S1")
	s := "no step °C, 5 µg/m³ ok"
	for i := 0; i < len(s); i++ {
		sink(s[i : i+1])
	}
	for _, c := range got {
		if !utf8.ValidString(c) {
			t.Fatalf("published half a character: %q", c)
		}
	}
	if strings.Join(got, "") != s {
		t.Fatalf("got %q", strings.Join(got, ""))
	}
}
