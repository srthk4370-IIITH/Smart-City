package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func histFixture(now time.Time) *Server {
	wall := func(d time.Duration) string { return now.Add(-d).In(IST).Format("2006-01-02 15:04:05") }
	u := func(d time.Duration) int64 { return now.Add(-d).Unix() }
	sens := func(node, metric string) []SensorRef {
		return []SensorRef{{Node: node, Metric: metric}, {Node: "CTX", Metric: "x", Context: true}}
	}
	r := &Reasoner{}
	r.incidents = []*Incident{
		// closed after acknowledgement; the same sensor alarms again 1 day later -> recurred
		{ID: "INC-0001", State: "done", CreatedWall: wall(72 * time.Hour), Severity: "critical", Roles: []string{"water"},
			Sensors: sens("WM-1", "level"), TotalMs: 4000, WorkflowState: WorkflowState{Workflow: wfClosed,
				AckedAt: u(72*time.Hour - 10*time.Minute), ClosedAt: u(48 * time.Hour), Outcome: "fixed_by_action"}},
		{ID: "INC-0002", State: "done", CreatedWall: wall(24 * time.Hour), Severity: "warning", Roles: []string{"water"},
			Sensors: sens("WM-1", "level"), TotalMs: 6000, WorkflowState: WorkflowState{Workflow: wfNeeds, AckedAt: u(24*time.Hour - 30*time.Minute)}},
		// sensor fault, still analysing (no AI latency yet)
		{ID: "INC-0003", State: "running", CreatedWall: wall(time.Hour), Severity: "sensor_fault", Roles: []string{"air_quality", "hvac"},
			Sensors: sens("AQ-1", "co2"), TotalMs: 900},
		// outside a 7-day window
		{ID: "INC-0004", State: "done", CreatedWall: wall(10 * 24 * time.Hour), Severity: "warning", Roles: []string{"power"},
			Sensors: sens("PW-1", "kw")},
		// deploy check: never shown
		{ID: "INC-0005", State: "done", CreatedWall: wall(2 * time.Hour), Severity: "critical", SystemCheck: true},
		// wall clock unknown: falls back to sensor time
		{ID: "INC-0006", State: "done", CreatedSim: u(5 * time.Hour), Severity: "", Roles: []string{"power"}, Sensors: sens("PW-1", "kw"),
			Watermark: "DEMO", WorkflowState: WorkflowState{Workflow: wfClosed, ClosedAt: u(4 * time.Hour), Outcome: "false_alarm"}},
	}
	return &Server{rsn: r}
}

func TestHistoryDaysParam(t *testing.T) {
	for _, c := range []struct {
		q    string
		want int
	}{{"", 7}, {"0", 7}, {"-3", 7}, {"abc", 7}, {"1", 1}, {"30", 30}, {"90", 90}, {"500", 90}} {
		if got := histDays(c.q); got != c.want {
			t.Errorf("histDays(%q) = %d, want %d", c.q, got, c.want)
		}
	}
}

func TestHistoryEndpoint(t *testing.T) {
	now := time.Date(2026, 11, 27, 12, 0, 0, 0, IST)
	old := histNow
	histNow = func() time.Time { return now }
	defer func() { histNow = old }()
	mux := http.NewServeMux()
	histFixture(now).registerHistoryRoutes(mux)

	get := func(q string) HistResp {
		t.Helper()
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, httptest.NewRequest("GET", "/api/history"+q, nil))
		if rec.Code != 200 {
			t.Fatalf("%s: status %d", q, rec.Code)
		}
		var hr HistResp
		if err := json.Unmarshal(rec.Body.Bytes(), &hr); err != nil {
			t.Fatalf("%s: %v", q, err)
		}
		return hr
	}

	cases := []struct {
		name      string
		q         string
		days      int
		ids       []string // newest first
		perDay    int
		crit      int
		openN     int
		faultPct  float64
		medAck    int64
		medClose  int64
		medAI     float64
		recurred  int
		topSensor string
	}{
		{"default 7d", "", 7, []string{"INC-0003", "INC-0006", "INC-0002", "INC-0001"}, 8, 1, 2, 25, 20 * 60, 45000, 5000, 1, "WM-1/level"},
		{"1 day", "?days=1", 1, []string{"INC-0003", "INC-0006", "INC-0002"}, 2, 0, 2, 33.3, 30 * 60, 3600, 6000, 0, ""},
		{"30 days", "?days=30", 30, []string{"INC-0003", "INC-0006", "INC-0002", "INC-0001", "INC-0004"}, 31, 1, 3, 20, 20 * 60, 45000, 5000, 1, "WM-1/level"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			hr := get(c.q)
			if hr.Days != c.days || hr.Now != now.Unix() || hr.TZ != "Asia/Kolkata" {
				t.Fatalf("header %+v", hr)
			}
			if len(hr.Incidents) != len(c.ids) {
				t.Fatalf("got %d rows, want %v", len(hr.Incidents), c.ids)
			}
			for i, id := range c.ids {
				if hr.Incidents[i].ID != id {
					t.Fatalf("row %d = %s, want %s", i, hr.Incidents[i].ID, id)
				}
			}
			a := hr.Agg
			if a.Total != len(c.ids) || len(a.PerDay) != c.perDay || a.BySeverity["critical"] != c.crit || a.Open != c.openN {
				t.Fatalf("agg total=%d days=%d crit=%d open=%d", a.Total, len(a.PerDay), a.BySeverity["critical"], a.Open)
			}
			if a.SensorFaultPct != c.faultPct || a.MedianAckS != c.medAck || a.MedianCloseS != c.medClose || a.MedianAIMs != c.medAI {
				t.Fatalf("fault%%=%v ack=%d close=%d ai=%v", a.SensorFaultPct, a.MedianAckS, a.MedianCloseS, a.MedianAIMs)
			}
			if a.Recurred != c.recurred {
				t.Fatalf("recurred %d", a.Recurred)
			}
			if c.topSensor != "" && (len(a.TopSensors) == 0 || a.TopSensors[0].Sensor != c.topSensor) {
				t.Fatalf("top sensors %+v", a.TopSensors)
			}
			sum, heat := 0, 0
			for _, d := range a.PerDay {
				sum += d.Critical + d.Warning + d.SensorFault + d.Normal
			}
			for _, row := range a.Heat {
				for _, n := range row {
					heat += n
				}
			}
			if sum != a.Total || heat != a.Total {
				t.Fatalf("per-day sum %d, heat sum %d, total %d", sum, heat, a.Total)
			}
		})
	}

	// row details on the 7-day view
	hr := get("?days=7")
	by := map[string]HistRow{}
	for _, r := range hr.Incidents {
		by[r.ID] = r
	}
	if r := by["INC-0001"]; !r.Recurred || r.RecurredBy != "INC-0002" || r.Open || r.AckS != 600 || r.CloseS != 24*3600 || r.AIMs != 4000 {
		t.Errorf("INC-0001 %+v", r)
	}
	if r := by["INC-0003"]; !r.SensorFault || r.AIMs != 0 || len(r.Sensors) != 1 || r.Sensors[0] != "AQ-1/co2" || !r.Open {
		t.Errorf("INC-0003 %+v", r)
	}
	if r := by["INC-0006"]; !r.ClockGuess || !r.Demo || r.Sev != "warning" || r.Outcome != "false_alarm" {
		t.Errorf("INC-0006 %+v", r)
	}
	if hr.Agg.ByDomain["water"] != 2 || hr.Agg.ByDomain["hvac"] != 1 || hr.Agg.ByOutcome["open"] != 2 || hr.Agg.ByBuilding["unknown"] != 4 {
		t.Errorf("breakdowns %+v %+v %+v", hr.Agg.ByDomain, hr.Agg.ByOutcome, hr.Agg.ByBuilding)
	}
	// Friday 27 Nov 2026, 11:00 IST: weekday index 4, hour 11
	if hr.Agg.Heat[4][11] != 1 {
		t.Errorf("heat %v", hr.Agg.Heat[4])
	}

	rec := httptest.NewRecorder()
	mux.ServeHTTP(rec, httptest.NewRequest("POST", "/api/history", nil))
	if rec.Code != http.StatusMethodNotAllowed {
		t.Errorf("POST status %d", rec.Code)
	}
}
