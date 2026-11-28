package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func fakeSupa(t *testing.T, fail *bool) (*httptest.Server, *[]string, *sync.Mutex) {
	var mu sync.Mutex
	var got []string
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("apikey") != "k" || r.Header.Get("Authorization") != "Bearer k" {
			w.WriteHeader(401)
			return
		}
		b, _ := io.ReadAll(r.Body)
		mu.Lock()
		defer mu.Unlock()
		if *fail {
			w.WriteHeader(503)
			return
		}
		got = append(got, strings.TrimPrefix(r.URL.Path, "/rest/v1/")+" "+r.URL.RawQuery+" "+string(b))
		w.WriteHeader(201)
	}))
	return ts, &got, &mu
}

func testSupa(url, dir string) *supaSync {
	return &supaSync{url: url, key: "k", board: "b1", dir: dir, client: http.DefaultClient,
		seen: map[string]sbSeen{}, wake: make(chan struct{}, 1)}
}

func testInc() Incident {
	return Incident{ID: "INC-1", Severity: "critical", Title: "Leak", CreatedWall: "2026-11-20T10:00:00Z",
		Roles: []string{"water"}, Sensors: []SensorRef{{Node: "n1", Location: "Block A"}},
		Final: &ReportCall{Raw: "RAWPROMPTSECRET", Prompt: "WINDOWSECRET", Parsed: &Report{Label: "leak", RootCause: "pipe",
			Evidence: []string{"EVIDENCESECRET 912 ppm"}, Observations: []V3Observation{{}}}},
		WorkflowState: WorkflowState{Events: []IncEvent{{Seq: 1, At: 1790000000, Actor: "op", Event: "ack"}}}}
}

func TestSupabaseSendsReportsOnlyAndDedups(t *testing.T) {
	fail := false
	ts, got, mu := fakeSupa(t, &fail)
	defer ts.Close()
	x := testSupa(ts.URL, t.TempDir())
	inc := testInc()
	line, _ := json.Marshal(inc)
	x.OnIncident(line)
	x.OnIncident(line) // unchanged: nothing new
	x.enqueueLocked(x.healthRow())
	if err := x.flush(); err != nil {
		t.Fatal(err)
	}
	mu.Lock()
	all := strings.Join(*got, "\n")
	n := len(*got)
	mu.Unlock()
	if n != 4 { // boards, incident_reports, decisions, board_health
		t.Fatalf("rows %d: %s", n, all)
	}
	for _, bad := range []string{"SECRET", "evidence", "observations", "windows", "readings", "prompt", "raw"} {
		if strings.Contains(strings.ToLower(all), strings.ToLower(bad)) {
			t.Fatalf("forbidden %q sent: %s", bad, all)
		}
	}
	if strings.Contains(all, "on_conflict") { // plain inserts: ON CONFLICT would need a SELECT policy under RLS
		t.Fatal("on_conflict must not be sent")
	}
	inc.Title = "Leak v2"
	line, _ = json.Marshal(inc)
	x.OnIncident(line)
	x.flush()
	mu.Lock()
	last := (*got)[len(*got)-1]
	mu.Unlock()
	if !strings.Contains(last, `"revision":1`) || x.Stats()["queued"].(int) != 0 {
		t.Fatalf("revision: %s", last)
	}
}

func TestSupabaseOfflineQueueSurvivesRestartAndCaps(t *testing.T) {
	fail := true
	ts, got, mu := fakeSupa(t, &fail)
	defer ts.Close()
	dir := t.TempDir()
	x := testSupa(ts.URL, dir)
	line, _ := json.Marshal(testInc())
	x.OnIncident(line)
	if x.flush() == nil || x.Stats()["last_error"] == "" {
		t.Fatal("expected failure")
	}
	y := testSupa(ts.URL, dir)
	y.load()
	mu.Lock()
	fail = false
	mu.Unlock()
	if err := y.flush(); err != nil || len(*got) == 0 {
		t.Fatalf("resend: %v %d", err, len(*got))
	}
	// cap: health rows are dropped first
	z := testSupa(ts.URL, t.TempDir())
	z.rows = []sbRow{{T: "incident_reports", D: map[string]any{"a": 1}}}
	for i := 0; i < sbMaxRows+10; i++ {
		z.enqueueLocked(sbRow{T: "board_health", D: map[string]any{"i": i}})
	}
	if len(z.rows) != sbMaxRows || z.rows[0].T != "incident_reports" {
		t.Fatalf("cap %d %s", len(z.rows), z.rows[0].T)
	}
}

// night sweep 2026-11-27 #46/#11: a row refused with HTTP 500 is parked after sbParkAfter tries and the rows behind it
// still go; rows are removed by id; Stats carries sent/parked/last_ok_unix/offline_since_unix.
func TestSupabaseParksPoisonRowAndKeepsOrder(t *testing.T) {
	var mu sync.Mutex
	var got []string
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, _ := io.ReadAll(r.Body)
		mu.Lock()
		defer mu.Unlock()
		if strings.Contains(string(b), "POISON") {
			w.WriteHeader(500)
			return
		}
		got = append(got, string(b))
		w.WriteHeader(201)
	}))
	defer ts.Close()
	dir := t.TempDir()
	x := testSupa(ts.URL, dir)
	x.boardSent = true
	x.enqueueLocked(sbRow{T: "decisions", D: map[string]any{"n": "POISON"}}, sbRow{T: "decisions", D: map[string]any{"n": "after"}})
	if x.rows[0].ID == 0 || x.rows[0].ID == x.rows[1].ID {
		t.Fatal("row ids", x.rows)
	}
	for i := 1; i < sbParkAfter; i++ {
		if x.flush() == nil {
			t.Fatal("expected a failure", i)
		}
		if st := x.Stats(); st["offline_since_unix"].(int64) == 0 || st["queued"].(int) != 2 {
			t.Fatal("stats while failing", st)
		}
	}
	if err := x.flush(); err != nil {
		t.Fatal(err)
	}
	st := x.Stats()
	if st["queued"].(int) != 0 || st["parked"].(int) != 1 || st["sent"].(int) != 1 || st["offline_since_unix"].(int64) != 0 ||
		st["last_ok_unix"].(int64) == 0 {
		t.Fatal("stats", st)
	}
	if len(got) != 1 || !strings.Contains(got[0], "after") {
		t.Fatal("sent", got)
	}
	if b, _ := os.ReadFile(filepath.Join(dir, "supabase_parked.jsonl")); !strings.Contains(string(b), "POISON") {
		t.Fatal("parked file", string(b))
	}
	// a key problem (401) is never parked: it would fail every row
	y := testSupa(ts.URL, t.TempDir())
	y.key = "wrong"
	y.boardSent = true
	y.enqueueLocked(sbRow{T: "decisions", D: map[string]any{"n": 1}})
	srv401 := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(401) }))
	defer srv401.Close()
	y.url = srv401.URL
	for i := 0; i < sbParkAfter+2; i++ {
		y.flush()
	}
	if y.Stats()["queued"].(int) != 1 || y.Stats()["parked"].(int) != 0 {
		t.Fatal("401 parked", y.Stats())
	}
}

// night sweep 2026-11-27 #45: a flush that sends many rows writes the queue file once, not once per row.
func TestSupabaseFlushWritesQueueOnce(t *testing.T) {
	fail := false
	ts, _, _ := fakeSupa(t, &fail)
	defer ts.Close()
	dir := t.TempDir()
	x := testSupa(ts.URL, dir)
	x.boardSent = true
	for i := 0; i < 50; i++ {
		x.enqueueLocked(sbRow{T: "board_health", D: map[string]any{"i": i}})
	}
	os.Remove(x.qpath())
	writes := 0
	stop := make(chan struct{})
	done := make(chan struct{})
	go func() { // count queue-file rewrites while flushing (each rewrite renames a fresh file in)
		defer close(done)
		var last time.Time
		for {
			select {
			case <-stop:
				return
			default:
			}
			if st, err := os.Stat(x.qpath()); err == nil && st.ModTime() != last {
				last = st.ModTime()
				writes++
			}
		}
	}()
	if err := x.flush(); err != nil {
		t.Fatal(err)
	}
	close(stop)
	<-done
	if b, _ := os.ReadFile(x.qpath()); len(strings.TrimSpace(string(b))) != 0 || writes > 2 {
		t.Fatalf("queue after flush %q, writes %d", b, writes)
	}
}

// night sweep 2026-11-27 #53: dedup entries of incidents closed > 30 days ago are pruned; open ones stay.
func TestSupabaseSeenPrune(t *testing.T) {
	x := testSupa("http://127.0.0.1:1", t.TempDir())
	now := time.Now()
	x.seen = map[string]sbSeen{"INC-1": {Rev: 1, Closed: now.Add(-31 * 24 * time.Hour).Unix()},
		"INC-2": {Rev: 1, Closed: now.Add(-2 * 24 * time.Hour).Unix()}, "INC-3": {Rev: 1}}
	if n := x.pruneSeenLocked(now); n != 1 || len(x.seen) != 2 {
		t.Fatal(n, x.seen)
	}
	inc := testInc()
	inc.Workflow = wfClosed
	line, _ := json.Marshal(inc)
	x.OnIncident(line)
	if x.seen["INC-1"].Closed == 0 {
		t.Fatal("closed time not recorded", x.seen["INC-1"])
	}
}
