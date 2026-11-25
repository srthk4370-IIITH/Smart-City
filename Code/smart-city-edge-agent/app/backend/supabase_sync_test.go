package main

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
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
	z.rows = []sbRow{{"incident_reports", map[string]any{"a": 1}}}
	for i := 0; i < sbMaxRows+10; i++ {
		z.enqueueLocked(sbRow{"board_health", map[string]any{"i": i}})
	}
	if len(z.rows) != sbMaxRows || z.rows[0].T != "incident_reports" {
		t.Fatalf("cap %d %s", len(z.rows), z.rows[0].T)
	}
}
