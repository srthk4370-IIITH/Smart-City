package main

import (
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

// Wi-Fi internet first, then the laptop relay, else the row stays queued (owner 2026-11-20).
func TestSupabaseDirectThenRelay(t *testing.T) {
	var relayHits int32
	relay := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt32(&relayHits, 1)
		w.WriteHeader(201)
	}))
	defer relay.Close()
	x := &supaSync{url: "http://127.0.0.1:1", relay: relay.URL, key: "k", client: &http.Client{Timeout: 2 * time.Second}}
	if err := x.post(sbRow{T: "board_health", D: map[string]any{"board_id": "b"}}); err != nil {
		t.Fatalf("relay path: %v", err)
	}
	if relayHits != 1 || !x.directDown.After(time.Now()) {
		t.Fatalf("relay hits %d, direct skipped until %v", relayHits, x.directDown)
	}
	if b := x.bases(time.Now()); len(b) != 1 || b[0] != relay.URL {
		t.Fatalf("direct should be skipped for 5 min: %v", b)
	}
	relay.Close()
	if err := x.post(sbRow{T: "board_health", D: map[string]any{"board_id": "b"}}); err == nil {
		t.Fatal("both paths down must return an error so the row stays queued")
	}
}
