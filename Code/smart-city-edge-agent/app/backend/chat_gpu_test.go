package main

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// the chat engine factory as built (other tests replace chatLLM and do not restore it)
var chatLLMDefault = chatLLM

// fakeLlamaServer: /completion answers content (status 200) or HTTP 500; bodies receives each request body.
func fakeLlamaServer(t *testing.T, fail bool, content string, bodies chan<- map[string]any, hits *atomic.Int32) string {
	s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		b, _ := io.ReadAll(r.Body)
		var m map[string]any
		json.Unmarshal(b, &m)
		if r.URL.Path != "/completion" || r.Method != "POST" {
			t.Errorf("request %s %s", r.Method, r.URL.Path)
		}
		if bodies != nil {
			bodies <- m
		}
		if fail {
			http.Error(w, "loading model", 503)
			return
		}
		json.NewEncoder(w).Encode(map[string]any{"content": content, "tokens_predicted": 7, "stop": true,
			"timings": map[string]any{"prompt_ms": 12.5, "predicted_per_second": 20.0}})
	}))
	t.Cleanup(s.Close)
	return s.URL
}

func TestChatGPURequestShape(t *testing.T) {
	chatGPUDownUntil.Store(0)
	bodies := make(chan map[string]any, 4)
	var hits atomic.Int32
	t.Setenv("SCE_CHAT_URL", fakeLlamaServer(t, false, "<think>\n\n</think>\n\nAll fine.", bodies, &hits))
	t.Setenv("SCE_HTPD", "127.0.0.1:1") // htpd must not be used
	prefix := chatStaticPrefixMode(time.Date(2026, 11, 4, 10, 0, 0, 0, IST), true)
	prompt := chatPromptMode(prefix, nil, "Is KH03 ok?", nil, true)
	llm := chatLLMDefault(prefix)
	g, ok := llm.(*chatGPULLM)
	if !ok {
		t.Fatalf("chat_url set: engine %T", llm)
	}
	text, m, err := llm.Complete(context.Background(), prompt, chatMaxNew, nil)
	if err != nil || text != "<think>\n\n</think>\n\nAll fine." || m.GenTokens != 7 {
		t.Fatalf("text %q m %+v err %v", text, m, err)
	}
	want := map[string]any{"prompt": prompt, "n_predict": float64(chatMaxNew), "temperature": float64(0), "top_k": float64(1),
		"cache_prompt": true, "stream": false}
	if got := <-bodies; !reflect.DeepEqual(got, want) {
		t.Fatalf("body %v", got)
	}
	if llm.Name() != "qwen3.5-2b rsn_v3 (gpu)" || g.used != "qwen3.5-2b rsn_v3 (gpu)" {
		t.Fatalf("labels %q %q", llm.Name(), g.used)
	}
}

// a GPU failure falls back to htpd with the same prompt (after the NPU wait) and skips the GPU for the backoff
func TestChatGPUFallbackToHtpd(t *testing.T) {
	chatGPUDownUntil.Store(0)
	t.Cleanup(func() { chatGPUDownUntil.Store(0) })
	var hits atomic.Int32
	t.Setenv("SCE_CHAT_URL", fakeLlamaServer(t, true, "", nil, &hits))
	got := make(chan map[string]any, 2)
	t.Setenv("SCE_HTPD", fakeReasonHtpd(t, false, got))
	t.Setenv("SCE_REASONER_MODEL", "/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf")
	waited := 0
	g := chatLLMDefault("PFX").(*chatGPULLM)
	g.beforeNPU = func(context.Context) error { waited++; return nil }
	for i := 0; i < 2; i++ {
		text, _, err := g.Complete(context.Background(), "PFX question", 100, nil)
		if err != nil || text != `{"title": "A"}` {
			t.Fatalf("fallback: %q %v", text, err)
		}
		req := <-got
		if req["kind"] != "reason" || req["prompt"] != "PFX question" || req["prefix"] != "PFX" || req["max_new"] != float64(100) {
			t.Fatalf("htpd request %v", req)
		}
	}
	if hits.Load() != 1 || waited != 2 || chatGPUUp() {
		t.Fatalf("gpu hits %d (want 1: backoff), npu waits %d, up %v", hits.Load(), waited, chatGPUUp())
	}
	if g.used != "qwen3.5-4b chat (htpd)" {
		t.Fatalf("fallback label %q", g.used)
	}
}

// chat_url unset: the htpd chat engine and request exactly as before
func TestChatURLUnsetUnchanged(t *testing.T) {
	t.Setenv("SCE_CHAT_URL", "")
	got := make(chan map[string]any, 1)
	t.Setenv("SCE_HTPD", fakeReasonHtpd(t, false, got))
	llm := chatLLMDefault("PFX")
	if _, ok := llm.(htpdChatLLM); !ok {
		t.Fatalf("engine %T", llm)
	}
	if _, _, err := llm.Complete(context.Background(), "PFX q", 50, nil); err != nil {
		t.Fatal(err)
	}
	want := map[string]any{"kind": "reason", "prompt": "PFX q", "keep": true, "prefix": "PFX", "max_new": float64(50), "stream": true}
	if req := <-got; !reflect.DeepEqual(req, want) {
		t.Fatalf("htpd request %v", req)
	}
}

// chat_think=adaptive (chat format) and chat_url (2B on the GPU) leave the reports on the 4B: label, prompt, engine
func TestReportsStay4B(t *testing.T) {
	t.Setenv("SCE_REASONER_MODEL", "/data/local/tmp/gpu/qwen35_reasoner_q4_0.gguf")
	t.Setenv("SCE_CHAT_THINK", "off")
	p0, a0 := v3StaticPrefix(), reasonerPromptV3("U", nil)
	t.Setenv("SCE_CHAT_THINK", "adaptive")
	t.Setenv("SCE_CHAT_URL", "http://127.0.0.1:1")
	t.Setenv("SCE_REASONER_ENGINE", "htpd")
	if v3StaticPrefix() != p0 || reasonerPromptV3("U", nil) != a0 {
		t.Fatalf("report prompt changed with chat_think/chat_url")
	}
	if l := (htpdReasonLLM{}).Name(); l != "qwen3.5-4b (htpd)" {
		t.Fatalf("report label %q", l)
	}
	if _, ok := reasonerLLM().(htpdReasonLLM); !ok {
		t.Fatalf("report engine %T", reasonerLLM())
	}
	if l := (htpdChatLLM{}).Name(); l != "qwen3.5-4b chat (htpd)" {
		t.Fatalf("htpd chat label %q", l)
	}
}

// with the GPU up a question is answered while an incident is analysed (no NPU wait) and names its engine
func TestChatGPUSkipsNPUQueue(t *testing.T) {
	chatGPUDownUntil.Store(0)
	var hits atomic.Int32
	t.Setenv("SCE_CHAT_URL", fakeLlamaServer(t, false, "Incidents are scored by severity.", nil, &hits))
	saved := chatLLM
	chatLLM = chatLLMDefault
	t.Cleanup(func() { chatLLM = saved })
	r := &Reasoner{}
	r.incidents = []*Incident{{ID: "INC-0902", State: "running"}} // stays running: Warm never pings
	cs := &chatStore{path: t.TempDir() + "/chats.json", S: map[string]*ChatSession{}}
	s, err := cs.Ask(context.Background(), r, "", "Explain how incidents are scored.")
	if err != nil {
		t.Fatal(err)
	}
	m := s.Msgs[len(s.Msgs)-1]
	if m.Busy || m.Error || m.Queued > 1500 || m.Model != "qwen3.5-2b rsn_v3 (gpu)" || hits.Load() == 0 {
		t.Fatalf("answer %+v hits %d", m, hits.Load())
	}
}

// GPU keep-warm: the static tool header alone (a llama-server checkpoint before the hourly time line), 1 token,
// during an incident too (never the NPU), then no second ping within chatGPUWarmGap.
func TestChatGPUWarmHeaderOnly(t *testing.T) {
	chatGPUDownUntil.Store(0)
	var hits atomic.Int32
	bodies := make(chan map[string]any, 8)
	t.Setenv("SCE_CHAT_URL", fakeLlamaServer(t, false, "x", bodies, &hits))
	t.Setenv("SCE_CHAT_THINK", "adaptive")
	t.Setenv("SCE_HTPD", "127.0.0.1:1") // htpd must not be used
	r := &Reasoner{}
	r.incidents = []*Incident{{ID: "INC-0903", State: "running"}}
	cs := &chatStore{path: t.TempDir() + "/chats.json", S: map[string]*ChatSession{}}
	cs.Warm(r)
	t.Cleanup(func() { cs.mu.Lock(); cs.active = time.Time{}; cs.mu.Unlock() })
	select {
	case b := <-bodies:
		if b["prompt"] != chatHeader15 || b["n_predict"] != 1.0 {
			t.Fatalf("ping: n_predict %v, prompt header-only %v", b["n_predict"], b["prompt"] == chatHeader15)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("no GPU ping during an incident")
	}
	time.Sleep(5 * time.Second)
	select {
	case b := <-bodies:
		if p, _ := b["prompt"].(string); !strings.HasPrefix(p, chatHeader15) || !strings.HasSuffix(p, "<|im_start|>user\n") || b["n_predict"] != 1.0 {
			t.Fatalf("second ping is not the hour's prefix: %q", p[max(0, len(p)-60):])
		}
	default:
		t.Fatal("no prefix ping")
	}
	if n := hits.Load(); n != 2 {
		t.Errorf("%d requests within 5 s, want 2 (header + prefix)", n)
	}
}

// the badge follows chat_device
func TestChatGPULabelDevice(t *testing.T) {
	t.Setenv("SCE_CHAT_DEVICE", "")
	if l := chatGPULabel(); l != "qwen3.5-2b rsn_v3 (gpu)" {
		t.Errorf("default: %q", l)
	}
	t.Setenv("SCE_CHAT_DEVICE", "cpu")
	if l := (&chatGPULLM{}).Name(); l != "qwen3.5-2b rsn_v3 (cpu)" {
		t.Errorf("cpu: %q", l)
	}
}

// a round that only repeats earlier calls ends the question (no 5-call loop)
func TestChatNewCallsDropsRepeats(t *testing.T) {
	seen := map[string]bool{}
	a := V3Call{Name: "faulty_sensors", Params: []V3Param{{K: "basis", V: "confirmed"}, {K: "time", V: `{"preset": "last_30d"}`}}}
	b := V3Call{Name: "faulty_sensors", Params: []V3Param{{K: "time", V: `{"preset":"last_30d"}`}, {K: "basis", V: "confirmed"}}}
	c := V3Call{Name: "faulty_sensors", Params: []V3Param{{K: "basis", V: "confirmed"}, {K: "node", V: "KH03"}}}
	if got := chatNewCalls([]V3Call{a}, seen); len(got) != 1 {
		t.Fatalf("first call dropped")
	}
	if got := chatNewCalls([]V3Call{b}, seen); len(got) != 0 {
		t.Errorf("same call (other order and spacing) kept")
	}
	if got := chatNewCalls([]V3Call{b, c}, seen); len(got) != 1 || got[0].Params[1].V != "KH03" {
		t.Errorf("new arguments dropped: %+v", got)
	}
}
