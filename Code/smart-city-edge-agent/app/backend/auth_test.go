package main

import (
	"net/http"
	"net/http/httptest"
	"os"
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
		r := httptest.NewRequest(c.method, "/api/mode", nil)
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
