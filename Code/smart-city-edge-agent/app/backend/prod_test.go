package main

import (
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"testing"
	"time"
)

// No keys: nothing starts, no hook, /api/prod/* answers 404 as before.
func TestProdOffByDefault(t *testing.T) {
	s := testServer(t)
	persistHook.Store(nil)
	prod = &prodState{}
	startProd(s)
	if persistHook.Load() != nil || prodAny() {
		t.Fatal("a production feature started without its key")
	}
	h := s.routes()
	for _, p := range []string{"/api/prod/status", "/api/prod/time", "/api/prod/selftest"} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, p, nil))
		if w.Code != http.StatusNotFound {
			t.Errorf("%s: %d", p, w.Code)
		}
	}
}

// Alert delivery through the real store hook: Reasoner.persist -> alerter -> webhook; plus status and self-test.
func TestProdAlertThroughPersist(t *testing.T) {
	s := testServer(t)
	sk := newSink(t)
	t.Setenv("SCE_ALERT_WEBHOOK", sk.srv.URL)
	persistHook.Store(nil)
	prod = &prodState{}
	t.Cleanup(func() { persistHook.Store(nil); prod = &prodState{} })
	startProd(s)
	if prod.alert == nil {
		t.Fatal("alerter not started")
	}
	inc := &Incident{ID: "INC-0100", State: "done", Severity: "critical", Title: "Tank level falling"}
	s.rsn.incidents = append(s.rsn.incidents, inc)
	s.rsn.persist(inc)
	prod.alert.Tick()
	if sk.n() != 1 {
		t.Fatalf("alerts sent: %d", sk.n())
	}
	if _, err := filepath.Glob(filepath.Join(s.dir, "state", "alert_queue.json")); err != nil {
		t.Fatal(err)
	}
	h := s.routes()
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/prod/status", nil))
	if w.Code != 200 {
		t.Fatalf("status %d", w.Code)
	}
	for i := 0; i < 2; i++ {
		s.eng.Tick()
	}
	time.Sleep(10 * time.Millisecond)
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/api/prod/selftest", nil))
	if w.Code != 200 {
		t.Fatalf("selftest %d %s", w.Code, w.Body.String())
	}
}
