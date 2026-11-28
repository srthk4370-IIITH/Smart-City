package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func TestGuardOffDeviceWrites(t *testing.T) {
	ok := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) })
	os.Setenv("SCE_API_TOKEN", "s3cret")
	defer os.Unsetenv("SCE_API_TOKEN")
	h := (&Server{dir: t.TempDir()}).guard(ok)
	for _, c := range []struct {
		method, addr, tok string
		want              int
	}{
		{"GET", "192.168.1.9:5000", "", 200},
		{"POST", "127.0.0.1:5000", "", 200},
		{"POST", "[::1]:5000", "", 200},
		{"POST", "192.168.1.9:5000", "", 403},
		{"POST", "192.168.1.9:5000", "wrong", 403},
		{"POST", "192.168.1.9:5000", "s3cret", 200},
	} {
		path := "/api/mode"
		if c.method == "GET" { // /api/mode is POST-only (405 since #4); any read route shows the read rule
			path = "/api/status"
		}
		r := httptest.NewRequest(c.method, path, nil)
		r.RemoteAddr = c.addr
		if c.tok != "" {
			r.Header.Set("X-API-Token", c.tok)
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != c.want {
			t.Errorf("%s from %s tok=%q: %d, want %d", c.method, c.addr, c.tok, w.Code, c.want)
		}
	}
}

// night sweep 2026-11-27 #113: the WebView sends an Origin header; push-to-talk posts audio/wav.
func TestGuardVoiceWAVFromWebView(t *testing.T) {
	ok := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(200) })
	h := (&Server{dir: t.TempDir()}).guard(ok)
	for _, c := range []struct {
		path, origin, ct string
		want             int
	}{
		{"/api/chat/voice", "http://127.0.0.1:8080", "audio/wav", 200},
		{"/api/chat/voice", "http://127.0.0.1:8080", "audio/x-wav", 200},
		{"/api/chat/voice", "http://127.0.0.1:8080", "audio/wav; codecs=1", 200},
		{"/api/chat/voice", "http://evil.example", "audio/wav", 403},    // same-origin check stays
		{"/api/chat/voice", "http://127.0.0.1:8080", "text/plain", 415}, // only WAV on the voice route
		{"/api/chat", "http://127.0.0.1:8080", "audio/wav", 415},        // WAV only on the voice route
		{"/api/chat", "http://127.0.0.1:8080", "application/json", 200},
	} {
		r := httptest.NewRequest("POST", c.path, strings.NewReader("RIFF....WAVE"))
		r.Host = "127.0.0.1:8080"
		r.RemoteAddr = "127.0.0.1:40000"
		r.Header.Set("Origin", c.origin)
		r.Header.Set("Content-Type", c.ct)
		w := httptest.NewRecorder()
		h.ServeHTTP(w, r)
		if w.Code != c.want {
			t.Errorf("%s origin=%s ct=%s: %d, want %d (%s)", c.path, c.origin, c.ct, w.Code, c.want, w.Body.String())
		}
	}
}
