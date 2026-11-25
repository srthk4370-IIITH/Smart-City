package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// A single {"node","metric","value"} on a live engine takes the device path: an impossible value is rejected,
// not clamped into range and reported "stored" (2026-11-19 hands-on).
func TestIngestSingleLiveUsesDevicePath(t *testing.T) {
	s := testServer(t)
	s.eng.SetLive(4 * time.Hour)
	h := s.routes()
	post := func(body string) string {
		w := httptest.NewRecorder()
		r := httptest.NewRequest(http.MethodPost, "/api/ingest", strings.NewReader(body))
		r.Header.Set("Content-Type", "application/json")
		r.RemoteAddr = "127.0.0.1:40000"
		h.ServeHTTP(w, r)
		return w.Body.String()
	}
	var node, metric string
	for _, sn := range s.eng.Sensors() {
		if sn.Metric == "co2" {
			node, metric = sn.Node, sn.Metric
			break
		}
	}
	if node == "" {
		t.Skip("no co2 sensor in the test bank")
	}
	if got := post(`{"node":"` + node + `","metric":"` + metric + `","value":-5000}`); strings.Contains(got, `"stored"`) || !strings.Contains(got, "results") {
		t.Fatalf("impossible single value: %s", got)
	}
	if got := post(`{"node":"` + node + `","metric":"` + metric + `","value":650}`); !strings.Contains(got, "accepted") {
		t.Fatalf("plausible single value: %s", got)
	}
}
