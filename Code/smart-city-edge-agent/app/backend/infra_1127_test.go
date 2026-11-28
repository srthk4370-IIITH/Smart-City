package main

// night sweep 2026-11-27, workstream D (infra) tests.

import (
	"bufio"
	"context"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// #50: an SSE client that stops reading (half-open phone) is dropped after the write deadline, not ~15 min later.
func TestSSEWriteDeadlineDropsStalledClient(t *testing.T) {
	old := sseWriteTimeout
	sseWriteTimeout = 200 * time.Millisecond
	defer func() { sseWriteTimeout = old }()
	h := NewHub()
	srv := httptest.NewServer(h)
	defer srv.Close()
	c, err := net.Dial("tcp", strings.TrimPrefix(srv.URL, "http://"))
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	c.Write([]byte("GET / HTTP/1.1\r\nHost: x\r\n\r\n"))
	bufio.NewReader(c).ReadString('\n') // the status line; then never read again
	subs := func() int { h.mu.Lock(); defer h.mu.Unlock(); return len(h.subs) }
	deadline := time.Now().Add(10 * time.Second)
	for subs() == 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	big := strings.Repeat("x", 256<<10)
	for subs() > 0 && time.Now().Before(deadline) {
		h.Publish("note", map[string]any{"pad": big})
		time.Sleep(20 * time.Millisecond)
	}
	if subs() != 0 {
		t.Fatal("stalled SSE client still subscribed after 10 s")
	}
}

var _ = http.MethodGet

// #47: a live O_APPEND log is truncated in place (the writer keeps working) with its newest part in .1;
// prefetch_shadow.jsonl is capped by the hourly rotation.
func TestRotateLiveLogsAndShadow(t *testing.T) {
	dir := t.TempDir()
	st := filepath.Join(dir, "state")
	os.MkdirAll(st, 0o755)
	p := filepath.Join(st, "htpd.log")
	w, err := os.OpenFile(p, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close()
	line := strings.Repeat("x", 99) + "\n"
	for i := 0; i < (liveLogCapBytes/100)+500; i++ {
		w.WriteString(line)
	}
	shadow := filepath.Join(st, "prefetch_shadow.jsonl")
	os.WriteFile(shadow, []byte(strings.Repeat(`{"a":1}`+"\n", (3<<20)/8)), 0o644)
	rotateStateFiles(dir, time.Now())
	if fi, _ := os.Stat(p); fi.Size() != 0 {
		t.Fatal("log not truncated", fi.Size())
	}
	if fi, err := os.Stat(p + ".1"); err != nil || fi.Size() < liveLogCapBytes/8 {
		t.Fatal("tail not kept", err)
	}
	w.WriteString("after\n") // the child's fd still works and lands at the start of the new file
	if b, _ := os.ReadFile(p); string(b) != "after\n" {
		t.Fatalf("append after truncate: %q", b)
	}
	if fi, _ := os.Stat(shadow); fi.Size() > 2<<20 {
		t.Fatal("shadow log not capped", fi.Size())
	}
}

// #51: an incident moved to the archive also leaves the retrieval index.
func TestCompactPrunesRetrievalIndex(t *testing.T) {
	t.Setenv("SCE_MAX_INCIDENTS", "50")
	rg := newWfRig(t)
	for i := 1; i <= 60; i++ {
		id := "INC-" + strings.Repeat("0", 4-len(itoa(i))) + itoa(i)
		rg.add(id, "SR-AQ-KH03-03", "co2", "warning")
		if _, err := rg.r.Close(id, "sam", "fixed_by_action", "done", false); err != nil {
			t.Fatal(err)
		}
	}
	rg.r.ret.mu.Lock()
	if rg.r.ret.df == nil {
		rg.r.ret.df = map[string]int{}
	}
	rg.r.ret.addLocked(retDoc{ID: "INC-0001", tf: map[string]float64{"co2": 1}})
	rg.r.ret.addLocked(retDoc{ID: "INC-0060", tf: map[string]float64{"co2": 1}})
	rg.r.ret.mu.Unlock()
	rg.r.compact()
	if rg.r.ret.doc("INC-0001") != nil {
		t.Fatal("archived incident still in the retrieval index")
	}
	if rg.r.ret.doc("INC-0060") == nil {
		t.Fatal("live incident dropped from the index")
	}
}

// #3/#4: bad input through the real routes (loopback, as the WebView): clear 4xx answers, never a 5xx or panic.
func TestAPIBadInputAndMethods(t *testing.T) {
	s := testServer(t)
	s.hub = NewHub()
	h := s.routes()
	call := func(method, path, ct, body string) *httptest.ResponseRecorder {
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.RemoteAddr = "127.0.0.1:5000"
		if ct != "" {
			r.Header.Set("Content-Type", ct)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		return w
	}
	for _, c := range []struct {
		method, path, ct, body string
		want                   int
	}{
		{"GET", "/api/series", "", "", 400},
		{"GET", "/api/series?node=NOPE-00&metric=co2", "", "", 404},
		{"GET", "/api/series?node=" + dqNode + "&metric=" + dqMetric + "&hours=-3", "", "", 200},
		{"GET", "/api/incidents/INC-9999", "", "", 404},
		{"GET", "/api/incidents/..%2F..%2Fetc%2Fpasswd", "", "", 404},
		{"GET", "/api/history?days=-5", "", "", 200},
		{"GET", "/api/history?days=abc", "", "", 200},
		{"GET", "/api/history?days=100000", "", "", 200},
		{"GET", "/api/mode", "", "", 405},
		{"GET", "/api/maintenance", "", "", 405},
		{"GET", "/api/site/validate", "", "", 405},
		{"GET", "/api/chat/voice", "", "", 405},
		{"POST", "/api/mode", "application/json", "{not json", 400},
		{"POST", "/api/mode", "application/json", `{"mode":9}`, 400},
		{"POST", "/api/maintenance", "application/json", `{"node":""}`, 400},
		{"POST", "/api/chat/voice", "audio/wav", "not a wav", 400},
	} {
		w := call(c.method, c.path, c.ct, c.body)
		if w.Code != c.want {
			t.Errorf("%s %s: %d, want %d (%s)", c.method, c.path, w.Code, c.want, strings.TrimSpace(w.Body.String()))
		}
		if w.Code == 405 && w.Header().Get("Allow") != "POST" {
			t.Errorf("%s %s: 405 without Allow: POST", c.method, c.path)
		}
	}
}

// #88: non-urgent work waits while the NPU is over the budget and goes on once it is under the resume mark;
// below the budget it never waits.
func TestThermalYieldBudget(t *testing.T) {
	old, oldPoll := thermalNPU, thermalPoll
	defer func() { thermalNPU, thermalPoll = old, oldPoll }()
	thermalPoll = 10 * time.Millisecond
	thermalNPU = func() float64 { return 70 }
	if d := thermalYield(context.Background(), "t", time.Second); d != 0 || thermalOverBudget() {
		t.Fatal("waited below the budget", d)
	}
	var calls int
	thermalNPU = func() float64 { calls++; return map[bool]float64{true: 92, false: 74}[calls < 5] }
	if d := thermalYield(context.Background(), "t", 5*time.Second); d <= 0 || d > 2*time.Second {
		t.Fatal("cool-down wait", d)
	}
	thermalNPU = func() float64 { return 95 } // never cools: bounded
	if d := thermalYield(context.Background(), "t", 100*time.Millisecond); d < 100*time.Millisecond || d > time.Second {
		t.Fatal("bound", d)
	}
}

// #87: samples are kept, filtered by hours, with peaks; the route answers.
func TestResourceHistory(t *testing.T) {
	resHist.Lock()
	resHist.s = nil
	resHist.Unlock()
	now := time.Now().Unix()
	addResSample(resSample{T: now - 7200, RSSMB: 30, MemAvMB: 4000, NPUC: 50})
	addResSample(resSample{T: now - 60, RSSMB: 32, MemAvMB: 3760, NPUC: 94})
	out := resSince(1, now)
	if n := len(out["samples"].([]resSample)); n != 1 {
		t.Fatal("1 h window", n)
	}
	if p := out["peak"].(map[string]float64); p["npu_c"] != 94 || p["mem_available_mb_min"] != 3760 {
		t.Fatal("peak", p)
	}
	if n := len(resSince(6, now)["samples"].([]resSample)); n != 2 {
		t.Fatal("6 h window", n)
	}
	s := testServer(t)
	s.hub = NewHub()
	r := httptest.NewRequest("GET", "/api/resources?hours=2", nil)
	r.RemoteAddr = "127.0.0.1:1"
	w := httptest.NewRecorder()
	s.routes().ServeHTTP(w, r)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"samples"`) {
		t.Fatal(w.Code, w.Body.String())
	}
	if sampleResources().T == 0 {
		t.Fatal("sample")
	}
}

// #104: a sensor handed over while an analysis runs waits for the NPU instead of being dropped; it gives up
// when its batch closed on it (alerted) or the wait runs out.
func TestPrefetchWaitsForIdleNPU(t *testing.T) {
	oldPoll := pfPoll
	pfPoll = 10 * time.Millisecond
	defer func() { pfPoll = oldPoll }()
	s := testServer(t)
	c := Candidate{Node: dqNode, Metric: dqMetric}
	s.rsn.mu.Lock()
	s.rsn.active = true
	s.rsn.mu.Unlock()
	go func() {
		time.Sleep(100 * time.Millisecond)
		s.rsn.mu.Lock()
		s.rsn.active = false
		s.rsn.mu.Unlock()
	}()
	if !s.rsn.pfWaitIdle(c, 5*time.Second) {
		t.Fatal("did not wait for the analysis to finish")
	}
	s.rsn.mu.Lock()
	s.rsn.active = true
	s.rsn.mu.Unlock()
	if s.rsn.pfWaitIdle(c, 50*time.Millisecond) {
		t.Fatal("bounded wait ignored")
	}
	s.eng.mu.Lock()
	if st := s.eng.states[key(dqNode, dqMetric)]; st != nil {
		st.alerted = true
	}
	s.eng.mu.Unlock()
	s.rsn.mu.Lock()
	s.rsn.active = false
	s.rsn.mu.Unlock()
	if s.rsn.pfWaitIdle(c, time.Second) {
		t.Fatal("prefetch after the sensor already alerted")
	}
}
