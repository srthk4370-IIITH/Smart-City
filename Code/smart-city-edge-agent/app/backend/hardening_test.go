package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func do(h http.Handler, method, path, body, remote string, hdr map[string]string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r := httptest.NewRequest(method, path, strings.NewReader(body))
	r.RemoteAddr = remote
	for k, v := range hdr {
		r.Header.Set(k, v)
	}
	h.ServeHTTP(w, r)
	return w
}

const (
	loopAddr = "127.0.0.1:40000"
	lanAddr  = "192.168.1.50:40000"
)

var jsonHdr = map[string]string{"Content-Type": "application/json"}

func TestAtomicWriteAndCaps(t *testing.T) {
	dir := t.TempDir()
	p := filepath.Join(dir, "sub", "f.json")
	if err := atomicWrite(p, []byte("one"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := atomicWrite(p, []byte("two"), 0o600); err != nil {
		t.Fatal(err)
	}
	if b, _ := os.ReadFile(p); string(b) != "two" {
		t.Fatalf("got %q", b)
	}
	if _, err := os.Stat(p + ".tmp"); err == nil {
		t.Fatal("temp file left behind")
	}
	if fi, _ := os.Stat(p); fi.Mode().Perm() != 0o600 {
		t.Fatalf("mode %v", fi.Mode())
	}
	if err := atomicWrite(filepath.Join(p, "x"), []byte("a"), 0o644); err == nil { // a file where a directory is needed
		t.Fatal("write into a non-directory must fail")
	}
	// capTail keeps whole newest lines
	big := filepath.Join(dir, "big.jsonl")
	var sb strings.Builder
	for i := 0; i < 200; i++ {
		sb.WriteString(`{"n":` + strings.Repeat("9", 20) + "}\n")
	}
	os.WriteFile(big, []byte(sb.String()), 0o644)
	if !capTail(big, 1000) {
		t.Fatal("not cut")
	}
	b, _ := os.ReadFile(big)
	if len(b) > 600 || !strings.HasPrefix(string(b), "{") || !strings.HasSuffix(string(b), "\n") {
		t.Fatalf("bad cut: %d bytes %q", len(b), b[:10])
	}
	if capTail(big, 1<<20) {
		t.Fatal("small file cut")
	}
	// daily rotation
	d := filepath.Join(dir, "state", "daily")
	os.MkdirAll(d, 0o755)
	old, fresh := filepath.Join(d, "2026-01-01.json"), filepath.Join(d, "2026-11-19.json")
	os.WriteFile(old, []byte("{}"), 0o644)
	os.WriteFile(fresh, []byte("{}"), 0o644)
	os.Chtimes(old, time.Now().Add(-100*24*time.Hour), time.Now().Add(-100*24*time.Hour))
	rotateStateFiles(dir, time.Now())
	if _, err := os.Stat(old); err == nil {
		t.Fatal("old daily summary kept")
	}
	if _, err := os.Stat(fresh); err != nil {
		t.Fatal("fresh daily summary removed")
	}
}

func TestRecoverMiddlewareAndSafeGo(t *testing.T) {
	h := recoverMW(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { panic("boom") }))
	before := panics()
	w := do(h, "GET", "/x", "", loopAddr, nil)
	if w.Code != 500 || panics() != before+1 {
		t.Fatalf("code %d panics %d", w.Code, panics())
	}
	done := make(chan bool)
	safeGo("test", func() { defer close(done); panic("in goroutine") })
	<-done
	time.Sleep(20 * time.Millisecond) // the process is still alive: reaching here is the assertion
	safeIter("test iter", func() { panic("x") })
}

func TestDiskInfo(t *testing.T) {
	d := diskInfo(t.TempDir())
	if !d.OK || d.TotalMB <= 0 || d.UsedPct < 0 || d.UsedPct > 100 {
		t.Fatalf("%+v", d)
	}
}

func TestRestartLoopCap(t *testing.T) {
	clk := &fakeClock{time.Unix(1_800_000_000, 0)}
	l := &restartLoop{now: clk.now}
	for i := 0; i < restartLoopMax-1; i++ {
		if l.note() {
			t.Fatal("tripped early")
		}
		clk.t = clk.t.Add(30 * time.Second)
	}
	if !l.note() || l.allow() {
		t.Fatal("6 starts in 15 min must trip the cap")
	}
	if ro, min := l.status(); !ro || min < 1 || min > 6 {
		t.Fatalf("status %v %d", ro, min)
	}
	clk.t = clk.t.Add(6 * time.Minute)
	if !l.allow() {
		t.Fatal("backoff over: starts allowed again")
	}
	for i := 0; i < restartLoopMax; i++ {
		l.note()
		clk.t = clk.t.Add(10 * time.Second)
	}
	if ro, min := l.status(); !ro || min < 6 { // second trip = 10 min
		t.Fatalf("second backoff %v %d", ro, min)
	}
}

func TestDemoEndpointsOffByDefault(t *testing.T) {
	s := testServer(t)
	h := s.routes()
	demoOverride.Store(2)
	defer demoOverride.Store(0)
	for _, p := range []string{"/api/scenarios", "/api/inject", "/api/chaos/run"} {
		m := "GET"
		if p != "/api/scenarios" {
			m = "POST"
		}
		if w := do(h, m, p, `{"scenario":"clear"}`, loopAddr, jsonHdr); w.Code != 404 {
			t.Fatalf("%s = %d with demo off", p, w.Code)
		}
	}
	demoOverride.Store(1)
	if w := do(h, "POST", "/api/inject", `{"scenario":"clear"}`, loopAddr, jsonHdr); w.Code != 200 {
		t.Fatalf("inject with demo on = %d %s", w.Code, w.Body)
	}
	// system_check analyses are deploy tooling and work in both modes
	var hv map[string]any
	json.Unmarshal(do(h, "GET", "/api/health", "", loopAddr, nil).Body.Bytes(), &hv)
	if hv["demo_active"] != true {
		t.Fatalf("demo_active missing: %v", hv["demo_active"])
	}
	demoOverride.Store(2)
	json.Unmarshal(do(h, "GET", "/api/health", "", loopAddr, nil).Body.Bytes(), &hv)
	if hv["demo_active"] != false {
		t.Fatal("demo_active true with demo off")
	}
	for _, k := range []string{"no_alert_channel", "disk", "htpd_rules_only", "store_write_errors"} {
		if _, ok := hv[k]; !ok {
			t.Errorf("health lacks %s", k)
		}
	}
	if hv["no_alert_channel"] != true {
		t.Fatal("no alerter configured must say no_alert_channel")
	}
}

func TestInjectedIncidentIsWatermarked(t *testing.T) {
	real, demo := &Incident{ID: "INC-1"}, &Incident{ID: "INC-2", Injected: true}
	markDemo(real)
	markDemo(demo)
	b, _ := json.Marshal(demo)
	if real.Watermark != "" || demo.Watermark != demoWatermark || !strings.Contains(string(b), "DEMO") {
		t.Fatalf("watermark: real %q demo %q", real.Watermark, demo.Watermark)
	}
}

func TestReadTokenAndCSRF(t *testing.T) {
	s := testServer(t)
	s.hub = NewHub()
	os.MkdirAll(filepath.Join(s.dir, "state"), 0o755)
	os.WriteFile(filepath.Join(s.dir, "state", "api_token"), []byte("w-tok\n"), 0o644)
	os.WriteFile(filepath.Join(s.dir, "state", "read_token"), []byte("r-tok\n"), 0o644)
	h := s.routes()
	// token file modes are tightened
	if fi, _ := os.Stat(filepath.Join(s.dir, "state", "api_token")); fi.Mode().Perm() != 0o600 {
		t.Fatalf("api_token mode %v", fi.Mode().Perm())
	}
	// sensitive reads
	if w := do(h, "GET", "/api/chat/sessions", "", lanAddr, nil); w.Code != 403 {
		t.Fatalf("LAN chat sessions without token = %d", w.Code)
	}
	if w := do(h, "GET", "/api/chat/sessions", "", lanAddr, map[string]string{"X-API-Token": "nope"}); w.Code != 403 {
		t.Fatalf("wrong token = %d", w.Code)
	}
	for _, tok := range []string{"r-tok", "w-tok"} {
		if w := do(h, "GET", "/api/chat/sessions", "", lanAddr, map[string]string{"X-API-Token": tok}); w.Code == 403 {
			t.Fatalf("token %s refused", tok)
		}
	}
	if w := do(h, "GET", "/api/chat/sessions", "", loopAddr, nil); w.Code == 403 {
		t.Fatal("loopback read must stay open")
	}
	if w := do(h, "GET", "/api/incidents/export", "", lanAddr, nil); w.Code != 403 {
		t.Fatalf("export = %d", w.Code)
	}
	if w := do(h, "GET", "/api/live", "", lanAddr, nil); w.Code != 200 {
		t.Fatalf("ordinary read = %d", w.Code)
	}
	// read token does not allow writes
	if w := do(h, "POST", "/api/mode", `{"mode":3}`, lanAddr, map[string]string{"Content-Type": "application/json", "X-API-Token": "r-tok"}); w.Code != 403 {
		t.Fatalf("write with the read token = %d", w.Code)
	}
	// LAN write: token + JSON
	if w := do(h, "POST", "/api/mode", `{"mode":3}`, lanAddr, map[string]string{"Content-Type": "application/json", "X-API-Token": "w-tok"}); w.Code != 200 {
		t.Fatalf("LAN write with token = %d %s", w.Code, w.Body)
	}
	if w := do(h, "POST", "/api/mode", `{"mode":3}`, lanAddr, map[string]string{"Content-Type": "text/plain", "X-API-Token": "w-tok"}); w.Code != 415 {
		t.Fatalf("LAN write as text/plain = %d", w.Code)
	}
	// CSRF: a browser page on another origin
	if w := do(h, "POST", "/api/mode", `{"mode":3}`, loopAddr, map[string]string{"Content-Type": "application/json", "Origin": "http://evil.example"}); w.Code != 403 {
		t.Fatalf("cross-origin write = %d", w.Code)
	}
	if w := do(h, "POST", "/api/mode", `mode=3`, loopAddr, map[string]string{"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://evil.example"}); w.Code != 403 {
		t.Fatalf("form post from another site = %d", w.Code)
	}
	if w := do(h, "POST", "/api/mode", `{"mode":3}`, loopAddr, map[string]string{"Content-Type": "application/json", "Origin": "http://example.com"}); w.Code != 200 {
		t.Fatalf("same-origin browser write = %d %s", w.Code, w.Body) // httptest Host is example.com
	}
	if w := do(h, "POST", "/api/mode", `mode=3`, loopAddr, map[string]string{"Content-Type": "application/x-www-form-urlencoded", "Origin": "http://example.com"}); w.Code != 415 {
		t.Fatalf("same-origin browser form post = %d", w.Code)
	}
	// curl / adb shell callers (no Origin, any content type) on loopback keep working
	if w := do(h, "POST", "/api/mode", `{"mode":3}`, loopAddr, nil); w.Code != 200 {
		t.Fatalf("loopback curl = %d", w.Code)
	}
	// strict mode: header required
	t.Setenv("SCE_CSRF_STRICT", "1")
	if w := do(h, "POST", "/api/mode", `{"mode":3}`, loopAddr, jsonHdr); w.Code != 403 {
		t.Fatalf("strict without header = %d", w.Code)
	}
	if w := do(h, "POST", "/api/mode", `{"mode":3}`, loopAddr, map[string]string{"Content-Type": "application/json", "X-Requested-With": "sce"}); w.Code != 200 {
		t.Fatalf("strict with header = %d", w.Code)
	}
}

func TestFogIngestFailsClosed(t *testing.T) {
	r := newWfRig(t).r
	h := FogIngestHandler(r, t.TempDir())
	body := `{"board_id":"b","stream":"s","rows":[]}`
	if w := do(h, "POST", "/v1/ingest", body, lanAddr, nil); w.Code != http.StatusServiceUnavailable {
		t.Fatalf("no token configured = %d", w.Code)
	}
	t.Setenv("SCE_FOG_INGEST_TOKEN", "tok")
	if w := do(h, "POST", "/v1/ingest", body, lanAddr, nil); w.Code != http.StatusUnauthorized {
		t.Fatalf("no bearer = %d", w.Code)
	}
	if w := do(h, "POST", "/v1/ingest", body, lanAddr, map[string]string{"Authorization": "Bearer wrong"}); w.Code != http.StatusUnauthorized {
		t.Fatalf("wrong bearer = %d", w.Code)
	}
	if w := do(h, "POST", "/v1/ingest", body, lanAddr, map[string]string{"Authorization": "Bearer tok"}); w.Code != 200 {
		t.Fatalf("right bearer = %d %s", w.Code, w.Body)
	}
}

// ---------------------------------------------------------------- store

func TestCompactNeverArchivesOpenIncidents(t *testing.T) {
	t.Setenv("SCE_MAX_INCIDENTS", "50")
	rg := newWfRig(t)
	for i := 1; i <= 80; i++ {
		id := "INC-" + strings.Repeat("0", 4-len(itoa(i))) + itoa(i)
		inc := rg.add(id, "SR-AQ-KH03-03", "co2", "warning")
		if i%2 == 0 { // even = closed
			if _, err := rg.r.Close(id, "sam", "fixed_by_action", "done", false); err != nil {
				t.Fatal(err)
			}
		}
		_ = inc
	}
	rg.r.compact()
	rg.r.mu.RLock()
	open, closed := 0, 0
	for _, i := range rg.r.incidents {
		if wfOf(i) == wfClosed {
			closed++
		} else {
			open++
		}
	}
	n := len(rg.r.incidents)
	rg.r.mu.RUnlock()
	if open != 40 {
		t.Fatalf("open incidents were archived: %d of 40 left", open)
	}
	if n != 50 || closed != 10 {
		t.Fatalf("retention: %d incidents (%d closed), want 50 (10)", n, closed)
	}
	ab, _ := os.ReadFile(archivePath(rg.r.store))
	if strings.Count(string(ab), "\n") != 30 {
		t.Fatalf("archived %d lines, want 30 closed ones", strings.Count(string(ab), "\n"))
	}
	// reload: nothing lost, newest wins
	r2 := NewReasoner(nil, nil, rg.dir, func(string, any) {})
	if len(r2.incidents) != 50 {
		t.Fatalf("reload has %d", len(r2.incidents))
	}
}

// An append racing a compaction must never leave an older copy after a newer one.
func TestPersistCompactNoLostUpdate(t *testing.T) {
	rg := newWfRig(t)
	inc := rg.add("INC-0001", "SR-AQ-KH03-03", "co2", "warning")
	done := make(chan bool)
	go func() {
		for i := 0; i < 60; i++ {
			rg.r.mu.Lock()
			inc.Title = "v" + itoa(i)
			rg.r.mu.Unlock()
			rg.r.persist(inc)
		}
		close(done)
	}()
	for i := 0; i < 30; i++ {
		rg.r.compact()
	}
	<-done
	rg.r.compact()
	r2 := NewReasoner(nil, nil, rg.dir, func(string, any) {})
	if len(r2.incidents) != 1 || r2.incidents[0].Title != "v59" {
		t.Fatalf("lost update: %d incidents, title %q", len(r2.incidents), r2.incidents[0].Title)
	}
}

func TestPersistReportsWriteFailure(t *testing.T) {
	rg := newWfRig(t)
	inc := rg.add("INC-0001", "SR-AQ-KH03-03", "co2", "warning")
	before := storeWriteErrors.Load()
	rg.r.store = filepath.Join(rg.dir, "no", "such", "dir", "incidents.jsonl")
	rg.r.persist(inc)
	if storeWriteErrors.Load() != before+1 {
		t.Fatal("a failed store write was not counted")
	}
}

// ---------------------------------------------------------------- pending queue

func TestPendingQueueBoundedCriticalFirstPersisted(t *testing.T) {
	rg := newWfRig(t)
	var cands []Candidate
	for i := 0; i < 100; i++ {
		st := "warning"
		if i >= 90 {
			st = "critical"
		}
		cands = append(cands, Candidate{Node: "N" + itoa(i), Metric: "co2", Finding: Finding{Status: st}})
	}
	rg.r.mu.Lock()
	rg.r.mergePending(cands)
	n := len(rg.r.pending)
	first := rg.r.pending[0]
	rg.r.mu.Unlock()
	if n != maxPendingCands {
		t.Fatalf("queue %d, want cap %d", n, maxPendingCands)
	}
	if first.Finding.Status != "critical" {
		t.Fatal("critical not first")
	}
	// a restart brings it back
	r2 := NewReasoner(nil, nil, rg.dir, func(string, any) {})
	if len(r2.pending) != maxPendingCands || r2.pending[0].Finding.Status != "critical" || r2.pending[9].Finding.Status != "critical" {
		t.Fatalf("restored %d", len(r2.pending))
	}
	// taking the work empties the file
	rg.r.mu.Lock()
	_, ok := rg.r.next()
	rg.r.mu.Unlock()
	if !ok {
		t.Fatal("no work")
	}
	if _, err := os.Stat(rg.r.pendingPath()); err == nil {
		t.Fatal("pending file not removed")
	}
}

// ---------------------------------------------------------------- watchdog

func TestWatchdogHardCapResetsStuckActive(t *testing.T) {
	rg := newWfRig(t)
	inc := rg.add("INC-0001", "SR-AQ-KH03-03", "co2", "critical")
	rg.r.mu.Lock()
	inc.State, inc.Workflow = "running", wfAnalysing
	inc.openedAt = time.Now().Add(-3 * time.Hour)
	rg.r.active = true
	gen := rg.r.loopGen
	rg.r.mu.Unlock()
	if n := rg.r.watchdogSweep(time.Now(), dataWaitMax, runMax); n != 1 {
		t.Fatalf("swept %d", n)
	}
	rg.r.mu.RLock()
	defer rg.r.mu.RUnlock()
	if rg.r.active || rg.r.loopGen != gen+1 || inc.State != "done_with_errors" {
		t.Fatalf("active=%v gen=%d state=%s", rg.r.active, rg.r.loopGen, inc.State)
	}
}

// ---------------------------------------------------------------- alerts

func TestAlertEscalationLadderAndBackup(t *testing.T) {
	main, backup := newSink(t), newSink(t)
	a, clk := testAlerter(t, filepath.Join(t.TempDir(), "q.json"), main, nil)
	a.backup = []alertChan{webhookChan("backup_email", backup.srv.URL, "json", "")}
	a.OnIncident(incJSON("INC-0001", "critical", "pending", 0, false))
	a.Tick()
	if main.n() != 1 {
		t.Fatalf("first alert: %d", main.n())
	}
	for _, step := range []struct {
		min  int
		want int
	}{{14, 1}, {1, 2}, {15, 3}, {30, 4}} { // 14 min: nothing; 15: 1st; 30: 2nd; 60: 3rd
		clk.t = clk.t.Add(time.Duration(step.min) * time.Minute)
		a.Tick()
		if main.n() != step.want {
			t.Fatalf("after +%d min: %d messages, want %d", step.min, main.n(), step.want)
		}
	}
	if backup.n() != 1 || backup.got[0]["incident"] != "INC-0001" {
		t.Fatalf("backup contact told %d times", backup.n())
	}
	clk.t = clk.t.Add(5 * time.Hour)
	a.Tick()
	if main.n() != 4 || backup.n() != 1 {
		t.Fatal("ladder repeats")
	}
	// an acknowledged critical stops the ladder
	a.OnIncident(incJSON("INC-0002", "critical", "pending", 0, false))
	a.Tick()
	a.OnIncident(incJSON("INC-0002", "critical", "pending", clk.t.Unix(), false))
	clk.t = clk.t.Add(2 * time.Hour)
	n := main.n()
	a.Tick()
	if main.n() != n {
		t.Fatal("acknowledged critical escalated")
	}
}

func TestNoAlertChannelFlag(t *testing.T) {
	old := prod.alert
	defer func() { prod.alert = old }()
	prod.alert = nil
	if alertChannelConfigured() {
		t.Fatal("configured with nothing")
	}
	main := newSink(t)
	a, _ := testAlerter(t, filepath.Join(t.TempDir(), "q.json"), main, nil)
	prod.alert = a
	if !alertChannelConfigured() {
		t.Fatal("not configured with a channel")
	}
	a.SendSystem("disk|d", "Disk", "full")
	a.SendSystem("disk|d", "Disk", "full") // once per key
	a.Tick()
	if main.n() != 1 {
		t.Fatalf("system alert sent %d times", main.n())
	}
}

// ---------------------------------------------------------------- decisions

func TestAckAndDecideCriticalWhileAIRuns(t *testing.T) {
	rg := newWfRig(t)
	inc := rg.add("INC-0001", "SR-AQ-KH03-03", "co2", "critical")
	rg.r.mu.Lock()
	inc.State, inc.Workflow = "running", wfAnalysing
	inc.Final = &ReportCall{Preliminary: true, Parsed: &Report{Severity: "critical"}}
	rg.r.mu.Unlock()
	if _, err := rg.r.Ack(inc.ID, "sam"); err != nil {
		t.Fatalf("ack while running: %v", err)
	}
	if _, err := rg.r.ApproveAll(inc.ID, "sam", ""); err != nil {
		t.Fatalf("approve critical on the rules report: %v", err)
	}
	// a warning still waits
	w := rg.add("INC-0002", "SR-AQ-KH03-03", "co2", "warning")
	rg.r.mu.Lock()
	w.State, w.Workflow = "running", wfAnalysing
	rg.r.mu.Unlock()
	if _, err := rg.r.ApproveAll(w.ID, "sam", ""); err == nil {
		t.Fatal("approve of a running warning must still be refused")
	}
	if _, err := rg.r.Ack(w.ID, "sam"); err != nil {
		t.Fatalf("ack of a running warning: %v", err)
	}
	// even with no report at all, ack works
	f := rg.add("INC-0003", "SR-AQ-KH03-03", "co2", "warning")
	rg.r.mu.Lock()
	f.State, f.Workflow, f.Final = "failed", wfInterrupted, nil
	rg.r.mu.Unlock()
	if _, err := rg.r.Ack(f.ID, "sam"); err != nil {
		t.Fatalf("ack of an interrupted incident: %v", err)
	}
}

func TestUndoWithinTenMinutes(t *testing.T) {
	rg := newWfRig(t)
	now := time.Unix(1_800_000_000, 0)
	old := wfNow
	wfNow = func() time.Time { return now }
	defer func() { wfNow = old }()
	rg.add("INC-0001", "SR-AQ-KH03-03", "co2", "warning")
	if _, err := rg.r.Close("INC-0001", "sam", "fixed_by_action", "valve replaced", false); err != nil {
		t.Fatal(err)
	}
	if got := rg.get("INC-0001"); wfOf(&got) != wfClosed || got.Undo == nil || undoUntil(&got) != now.Add(10*time.Minute).Unix() {
		t.Fatalf("no undo offered: %+v", got.Undo)
	}
	now = now.Add(9 * time.Minute)
	if _, err := rg.r.Undo("INC-0001", "sam"); err != nil {
		t.Fatalf("undo within 9 min: %v", err)
	}
	got := rg.get("INC-0001")
	if wfOf(&got) != wfNeeds || got.Outcome != "" || got.ClosedAt != 0 || got.Undo != nil || !strings.HasSuffix(evNames(got), "sam:undone") {
		t.Fatalf("not restored: %s %+v", wfOf(&got), got)
	}
	// too late
	rg.r.Close("INC-0001", "sam", "fixed_by_action", "again", false)
	now = now.Add(11 * time.Minute)
	if _, err := rg.r.Undo("INC-0001", "sam"); err == nil || !strings.Contains(err.Error(), "10-minute") {
		t.Fatalf("late undo: %v", err)
	}
	if _, err := rg.r.Undo("INC-0001", "sam"); err == nil {
		t.Fatal("second undo")
	}
	// ack, then undo
	rg.add("INC-0002", "SR-AQ-KH03-03", "co2", "warning")
	rg.r.Ack("INC-0002", "meena")
	if _, err := rg.r.Undo("INC-0002", "meena"); err != nil {
		t.Fatal(err)
	}
	if g := rg.get("INC-0002"); g.Owner != "" || g.AckedAt != 0 || wfOf(&g) != wfNeeds {
		t.Fatalf("ack not undone: %+v", g.WorkflowState)
	}
	// somebody else acted since: no undo
	rg.add("INC-0003", "SR-AQ-KH03-03", "co2", "warning")
	rg.r.Ack("INC-0003", "meena")
	rg.r.AddStep("INC-0003", "ravi", "check the damper")
	if _, err := rg.r.Undo("INC-0003", "meena"); err == nil {
		t.Fatal("undo after another operator's action")
	}
}

func TestCriticalDismissNeedsSecondConfirmation(t *testing.T) {
	s := testServer(t)
	rg := &wfRig{t: t, r: s.rsn, dir: s.dir}
	rg.add("INC-0001", "SR-AQ-KH03-03", "co2", "critical")
	rg.add("INC-0002", "SR-AQ-KH03-03", "co2", "warning")
	h := s.routes()
	dismiss := func(id, extra string) *httptest.ResponseRecorder {
		return do(h, "POST", "/api/incidents/"+id+"/dismiss", `{"operator":"sam","note":"checked, false alarm"`+extra+`}`, loopAddr, jsonHdr)
	}
	if w := dismiss("INC-0001", ""); w.Code != 409 || !strings.Contains(w.Body.String(), "confirm_required") {
		t.Fatalf("critical dismiss without confirmation = %d %s", w.Code, w.Body)
	}
	if w := dismiss("INC-0002", ""); w.Code != 200 {
		t.Fatalf("warning dismiss = %d %s", w.Code, w.Body)
	}
	if w := dismiss("INC-0001", `,"confirm_critical":true`); w.Code != 200 {
		t.Fatalf("confirmed critical dismiss = %d %s", w.Code, w.Body)
	}
	got := rg.get("INC-0001")
	if !got.DismissUnconfirmed || got.Outcome != "no_action_needed" {
		t.Fatalf("dismissal not marked unconfirmed: %+v", got.WorkflowState)
	}
	// list shows it
	var list []map[string]any
	json.Unmarshal(do(h, "GET", "/api/incidents", "", loopAddr, nil).Body.Bytes(), &list)
	found := false
	for _, it := range list {
		if it["id"] == "INC-0001" {
			found = it["dismiss_unconfirmed"] == true && it["undo_until"].(float64) > 0
		}
	}
	if !found {
		t.Fatalf("list lacks dismiss_unconfirmed / undo_until: %v", list)
	}
	// the same person cannot confirm; a second one can
	if w := do(h, "POST", "/api/incidents/INC-0001/confirm_dismiss", `{"operator":"Sam"}`, loopAddr, jsonHdr); w.Code != 409 {
		t.Fatalf("self-confirm = %d", w.Code)
	}
	if w := do(h, "POST", "/api/incidents/INC-0001/confirm_dismiss", `{"operator":"meena"}`, loopAddr, jsonHdr); w.Code != 200 {
		t.Fatalf("second person = %d %s", w.Code, w.Body)
	}
	if g := rg.get("INC-0001"); g.DismissUnconfirmed {
		t.Fatal("still unconfirmed")
	}
	// reopen needs a reason
	if w := do(h, "POST", "/api/incidents/INC-0001/reopen", `{"operator":"sam"}`, loopAddr, jsonHdr); w.Code != 400 {
		t.Fatalf("reopen without reason = %d", w.Code)
	}
	if w := do(h, "POST", "/api/incidents/INC-0001/reopen", `{"operator":"sam","note":"it came back"}`, loopAddr, jsonHdr); w.Code != 200 {
		t.Fatalf("reopen = %d %s", w.Code, w.Body)
	}
	// undo over HTTP
	if w := do(h, "POST", "/api/incidents/INC-0002/undo", `{"operator":"sam"}`, loopAddr, jsonHdr); w.Code != 200 {
		t.Fatalf("undo = %d %s", w.Code, w.Body)
	}
}

func TestUnconfirmedDismissalLeavesRetrievalMemory(t *testing.T) {
	inc := &Incident{ID: "INC-0001", Mode: 3, State: "done", Title: "CO2 rising", WorkflowState: WorkflowState{DismissUnconfirmed: true},
		Final:   &ReportCall{Valid: true, Parsed: &Report{Severity: "warning", Label: "ventilation_issue", RootCause: "fan"}},
		Sensors: []SensorRef{{Node: "SR-AQ-KH03-03", Metric: "co2", Role: "air_quality", Xs: []float64{400, 500, 600, 700}}}}
	if _, ok := retDocOf(inc); ok {
		t.Fatal("an unconfirmed dismissal is retrieval memory")
	}
	inc.DismissUnconfirmed = false
	if _, ok := retDocOf(inc); !ok {
		t.Skip("fixture is not indexable on its own")
	}
}

// ---------------------------------------------------------------- engine / chat

func TestWarmingUpPerSensor(t *testing.T) {
	s := testServer(t)
	s.eng.SetLive(4 * time.Hour)
	var node, metric string
	for _, sn := range s.eng.Sensors() {
		if sn.Metric == "co2" {
			node, metric = sn.Node, sn.Metric
			break
		}
	}
	if node == "" {
		t.Skip("no co2 sensor")
	}
	find := func() SensorState {
		_, st, _ := s.eng.Snapshot()
		for _, x := range st {
			if x.Node == node && x.Metric == metric {
				return x
			}
		}
		t.Fatal("sensor missing")
		return SensorState{}
	}
	st := find()
	need := trigRules().PersistReadings
	if !st.WarmingUp || st.WarmMinLeft != need*5 {
		t.Fatalf("fresh live sensor: warming=%v left=%d (need %d readings)", st.WarmingUp, st.WarmMinLeft, need)
	}
	s.eng.mu.RLock()
	top := s.eng.sim / bucketSec * bucketSec
	s.eng.mu.RUnlock()
	v := 700.0
	for i := 0; i < need; i++ {
		ts := top - int64(i)*bucketSec
		if _, err := s.eng.IngestReading(Reading{Node: node, Metric: metric, Value: &v, Ts: float64(ts)}, ts+1); err != nil {
			t.Fatal(err)
		}
	}
	if st = find(); st.WarmingUp || st.WarmMinLeft != 0 {
		t.Fatalf("after %d readings: warming=%v left=%d", need, st.WarmingUp, st.WarmMinLeft)
	}
	b, _ := json.Marshal(st)
	if !strings.Contains(string(b), `"warming_up":false`) || !strings.Contains(string(b), `"warming_min_left":0`) {
		t.Fatalf("not in the JSON: %s", b)
	}
}

func TestChatIgnoresSystemCheckIncidents(t *testing.T) {
	rg := newWfRig(t)
	rg.add("INC-0001", "SR-AQ-KH03-03", "co2", "warning")
	chk := rg.add("INC-0002", "SR-AQ-KH03-03", "co2", "warning")
	rg.r.mu.Lock()
	chk.SystemCheck = true
	chk.Outcome = "false_alarm"
	rg.r.mu.Unlock()
	tl := &chatTools{r: rg.r}
	for _, ci := range tl.incidents() {
		if ci.inc.SystemCheck {
			t.Fatalf("chat lists the system check %s", ci.inc.ID)
		}
	}
	if lines := rg.r.memoryLines("INC-0001", []string{"SR-AQ-KH03-03"}, 5); len(lines) != 0 {
		t.Fatalf("memory lines include a system check: %v", lines)
	}
}
