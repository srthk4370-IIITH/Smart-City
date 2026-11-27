package main

// Who may read and change what.
//
// The backend listens on 0.0.0.0:8000 so a real sensor can POST readings over Wi-Fi (HANDBOOK 4). Rules:
//   - Loopback (the app's WebView, the laptop through adb forward) is trusted, with one exception: a browser
//     request (it carries an Origin header) must be same-origin and, for a write, send Content-Type application/json
//     (CSRF: a page on another site cannot do either without a CORS preflight, which this server never grants).
//     curl / adb shell callers send no Origin and are unchanged.
//   - Off the device, a write needs the API token (X-API-Token) AND Content-Type application/json.
//   - Off the device, the sensitive reads (chat sessions, exports, daily summaries, prod status) need the read token
//     (X-API-Token holding the read token or the API token). Other reads stay open (a wall display on the LAN).
//   - The demo endpoints (/api/inject, /api/scenarios, /api/chaos) answer 404 unless demo mode is on.
//   - csrf_strict=1 (profile / SCE_CSRF_STRICT) additionally requires the header X-Requested-With on every write.
//
// Tokens: API token = SCE_API_TOKEN or the first line of <dir>/state/api_token; read token = SCE_READ_TOKEN or
// <dir>/state/read_token. With none set, off-device writes and sensitive reads are refused. Token files are 0600.

import (
	"crypto/rand"
	"crypto/subtle"
	"encoding/hex"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
)

func loadAPIToken(dir string) string {
	if t := strings.TrimSpace(os.Getenv("SCE_API_TOKEN")); t != "" {
		return t
	}
	return firstLine(filepath.Join(dir, "state", "api_token"))
}

func loadReadToken(dir string) string {
	if t := strings.TrimSpace(os.Getenv("SCE_READ_TOKEN")); t != "" {
		return t
	}
	return firstLine(filepath.Join(dir, "state", "read_token"))
}

func firstLine(p string) string {
	if b, err := os.ReadFile(p); err == nil {
		return strings.TrimSpace(strings.SplitN(string(b), "\n", 2)[0])
	}
	return ""
}

// ensureTokenModes tightens state/api_token and state/read_token to 0600 (they were created 0644 by hand).
func ensureTokenModes(dir string) {
	for _, n := range []string{"api_token", "read_token"} {
		p := filepath.Join(dir, "state", n)
		if fi, err := os.Stat(p); err == nil && fi.Mode().Perm() != 0o600 {
			os.Chmod(p, 0o600)
		}
	}
}

// newToken is a fresh random token (helper for first-time setup; written 0600).
func newToken(dir, name string) (string, error) {
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	t := hex.EncodeToString(b)
	return t, atomicWrite(filepath.Join(dir, "state", name), []byte(t+"\n"), 0o600)
}

func isLoopback(remoteAddr string) bool {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

// ---------------------------------------------------------------- demo mode

var demoOverride atomic.Int32 // tests: 1 = on, 2 = off, 0 = follow the profile

// demoActive: demo endpoints and the demo banner. Off unless htpd_profile demo=1 or SCE_DEMO=1.
func demoActive() bool {
	switch demoOverride.Load() {
	case 1:
		return true
	case 2:
		return false
	}
	return profOn("demo")
}

func isDemoPath(p string) bool {
	return p == "/api/inject" || p == "/api/scenarios" || strings.HasPrefix(p, "/api/chaos")
}

// sensitiveRead: GETs that expose operator conversations, exports or production internals.
func sensitiveRead(p string) bool {
	return strings.HasPrefix(p, "/api/chat/sessions") || p == "/api/incidents/export" || strings.HasPrefix(p, "/api/daily") ||
		strings.HasPrefix(p, "/api/prod/")
}

func tokenEq(got, want string) bool {
	return want != "" && subtle.ConstantTimeCompare([]byte(got), []byte(want)) == 1
}

func isJSONType(ct string) bool {
	ct = strings.ToLower(strings.TrimSpace(ct))
	return ct == "application/json" || strings.HasPrefix(ct, "application/json;")
}

// sameOrigin: the Origin header names this server (or is absent: a non-browser caller).
func sameOrigin(r *http.Request) (present, same bool) {
	o := r.Header.Get("Origin")
	if o == "" {
		return false, true
	}
	u, err := url.Parse(o)
	return true, err == nil && u.Host == r.Host
}

func (s *Server) guard(next http.Handler) http.Handler {
	ensureTokenModes(s.dir)
	return recoverMW(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if isDemoPath(r.URL.Path) && !demoActive() {
			http.Error(w, "demo mode is off on this board (htpd_profile demo=1 turns it on)", http.StatusNotFound)
			return
		}
		loop := isLoopback(r.RemoteAddr)
		read := r.Method == http.MethodGet || r.Method == http.MethodHead || r.Method == http.MethodOptions
		if read {
			if !loop && sensitiveRead(r.URL.Path) {
				got := r.Header.Get("X-API-Token")
				if !tokenEq(got, loadReadToken(s.dir)) && !tokenEq(got, loadAPIToken(s.dir)) {
					http.Error(w, "this data from off the device needs the X-API-Token header (read token)", http.StatusForbidden)
					return
				}
			}
			next.ServeHTTP(w, r)
			return
		}
		// writes
		if present, same := sameOrigin(r); !same {
			http.Error(w, "cross-origin request refused", http.StatusForbidden)
			return
		} else if (present || !loop) && !isJSONType(r.Header.Get("Content-Type")) && r.ContentLength != 0 {
			http.Error(w, "writes need Content-Type: application/json", http.StatusUnsupportedMediaType)
			return
		}
		if profOn("csrf_strict") && r.Header.Get("X-Requested-With") == "" {
			http.Error(w, "writes need the X-Requested-With header", http.StatusForbidden)
			return
		}
		if !loop && r.URL.Path != "/api/clock/viewer" { // viewer clock: bounded, vote-based (clockviewer.go)
			if !tokenEq(r.Header.Get("X-API-Token"), loadAPIToken(s.dir)) {
				http.Error(w, "changes from off the device need the X-API-Token header (see HANDBOOK 2.35)", http.StatusForbidden)
				return
			}
		}
		next.ServeHTTP(w, r)
	}))
}
