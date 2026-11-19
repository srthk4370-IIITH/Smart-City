package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
)

// fogBox: a fog server (FogHandler + FogIngestHandler over its own store) that can be down, or apply a batch and then
// lose the answer (the board must retry; the fog must not apply twice).
type fogBox struct {
	r          *Reasoner
	dir        string
	srv        *httptest.Server
	down       atomic.Bool
	loseAnswer atomic.Bool
}

func newFogBox(t *testing.T) *fogBox {
	fb := &fogBox{dir: t.TempDir()}
	fb.r = NewReasoner(NewGenieRunner(fb.dir, fb.dir, true), nil, fb.dir, func(string, any) {})
	ing := FogIngestHandler(fb.r, fb.dir)
	tools := FogHandler(fb.r, fogKBCache)
	fb.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if fb.down.Load() {
			http.Error(w, "down", http.StatusBadGateway)
			return
		}
		if req.URL.Path == "/v1/ingest" {
			if fb.loseAnswer.CompareAndSwap(true, false) {
				ing.ServeHTTP(httptest.NewRecorder(), req)
				http.Error(w, "connection reset", http.StatusBadGateway)
				return
			}
			ing.ServeHTTP(w, req)
			return
		}
		tools.ServeHTTP(w, req)
	}))
	t.Cleanup(fb.srv.Close)
	return fb
}

func hookOnly(t *testing.T, r *Reasoner, f func([]byte)) {
	t.Helper()
	persistHook.Store(nil)
	addPersistHook(r, f)
	t.Cleanup(func() { persistHook.Store(nil) })
}

func TestFogUploadOutageResumeIdempotent(t *testing.T) {
	fb := newFogBox(t)
	s := testServer(t)
	f := newFogUploader(s.dir, s.eng)
	f.url = func() string { return fb.srv.URL }
	hookOnly(t, s.rsn, f.OnIncident)
	ctx := context.Background()

	inc := &Incident{ID: "INC-0001", State: "done", Severity: "critical", Title: "CO2 rising", Approval: "pending",
		Sensors: []SensorRef{{Ref: "S1", Node: dqNode, Metric: dqMetric, Xs: []float64{450, 600, 900}}},
		Agents:  []AgentCall{{Ref: "S1", Prompt: "WINDOW 450 600 900", Raw: `{"pattern":"spike"}`}},
		Final:   &ReportCall{Prompt: "WINDOW again", Raw: "report"}}
	s.rsn.incidents = append(s.rsn.incidents, inc)
	fb.down.Store(true)
	s.rsn.persist(inc) // version 1, fog down
	inc.Approval = "approved"
	s.rsn.persist(inc) // version 2, still down
	f.Enqueue("health", "", map[string]any{"uptime_s": 10})
	if err := f.Sync(ctx); err == nil {
		t.Fatal("sync succeeded against a dead fog")
	}
	if n := len(f.readRows(f.pos(), 100)); n != 3 {
		t.Fatalf("outbox %d rows, want 3", n)
	}
	// the fog comes back but the first answer is lost after it applied the batch: the board retries, nothing doubles
	fb.down.Store(false)
	fb.loseAnswer.Store(true)
	if err := f.Sync(ctx); err == nil {
		t.Fatal("lost answer counted as sent")
	}
	if err := f.Sync(ctx); err != nil {
		t.Fatal(err)
	}
	got := fb.r.Get("INC-0001")
	if got == nil || got.Approval != "approved" {
		t.Fatalf("fog copy %+v", got)
	}
	if len(got.Sensors[0].Xs) != 0 || got.Agents[0].Prompt != "" || got.Final.Prompt != "" || got.Agents[0].Raw == "" {
		t.Fatalf("raw readings left the board: %+v %+v", got.Sensors[0], got.Agents[0])
	}
	b, _ := os.ReadFile(filepath.Join(fb.dir, "state", "fog_rows.jsonl"))
	if strings.Count(string(b), `"kind":"health"`) != 1 {
		t.Fatalf("fog rows:\n%s", b)
	}
	// the fog's chat tools now see the uploaded incident
	resp, err := http.Get(fb.srv.URL + "/v1/status")
	if err != nil {
		t.Fatal(err)
	}
	var st map[string]any
	json.NewDecoder(resp.Body).Decode(&st)
	resp.Body.Close()
	if st["incidents"].(float64) != 1 {
		t.Fatalf("fog status %v", st)
	}
	// a restart keeps the stream and seq: new rows continue above what the fog applied
	g := newFogUploader(s.dir, s.eng)
	g.url = f.url
	if g.stream != f.stream || g.seq != f.seq {
		t.Fatalf("restart lost stream/seq: %s/%d vs %s/%d", g.stream, g.seq, f.stream, f.seq)
	}
	inc.Title = "CO2 rising (refined)"
	hookOnly(t, s.rsn, g.OnIncident)
	s.rsn.persist(inc)
	if err := g.Sync(ctx); err != nil {
		t.Fatal(err)
	}
	if fb.r.Get("INC-0001").Title != "CO2 rising (refined)" {
		t.Fatal("update after restart not applied")
	}
}

func TestFogOutboxCapKeepsNewestIncident(t *testing.T) {
	s := testServer(t)
	f := newFogUploader(s.dir, s.eng)
	f.capBytes = 8 << 10
	for i := 0; i < 200; i++ {
		f.Enqueue("health", "", map[string]any{"pad": strings.Repeat("x", 100), "i": i})
		if i%20 == 0 {
			f.Enqueue("incident", "INC-0001", map[string]any{"id": "INC-0001", "v": i})
		}
	}
	st, _ := os.Stat(f.path("fog_outbox.jsonl"))
	if st.Size() > f.capBytes {
		t.Fatalf("outbox %d bytes over cap %d", st.Size(), f.capBytes)
	}
	var newest float64 = -1
	n := 0
	for _, r := range f.readRows(f.pos(), 1000) {
		if r.Kind == "incident" {
			var m map[string]any
			json.Unmarshal(r.Data, &m)
			newest = m["v"].(float64)
			n++
		}
	}
	if n != 1 || newest != 180 || f.dropped == 0 {
		t.Fatalf("incident rows %d newest %v dropped %d", n, newest, f.dropped)
	}
}

func TestFogHourlySummariesNoOccupancy(t *testing.T) {
	s := testServer(t)
	f := newFogUploader(s.dir, s.eng)
	f.summarise() // first call only notes the hour
	for i := 0; i < 13; i++ {
		s.eng.Tick()
	}
	f.summarise()
	rows := f.readRows(0, 10000)
	if len(rows) == 0 {
		t.Fatal("no summaries")
	}
	for _, r := range rows {
		var m map[string]any
		json.Unmarshal(r.Data, &m)
		if r.Kind != "summary" || m["role"] == "occupancy" {
			t.Fatalf("row %s %v", r.Kind, m)
		}
	}
	f.occupancy = true
	for i := 0; i < 12; i++ {
		s.eng.Tick()
	}
	f.summarise()
	occ := 0
	for _, r := range f.readRows(0, 10000) {
		if strings.Contains(string(r.Data), `"role":"occupancy"`) {
			occ++
		}
	}
	if occ == 0 {
		t.Fatal("fog_upload_occupancy=1 did not include occupancy")
	}
}
