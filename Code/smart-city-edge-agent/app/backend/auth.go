package main

// Who may change state.
//
// The backend listens on 0.0.0.0:8000 so a real sensor can POST readings over Wi-Fi (HANDBOOK 4).
// Without a check, anyone on that network could also approve or dismiss incidents, switch modes or
// inject faults. Reads stay open (a wall display on the LAN is fine); anything else from off the
// device needs the API token. Loopback - the app's WebView, and the laptop through adb forward -
// is unchanged.
//
// Token: SCE_API_TOKEN, or the first line of <dir>/state/api_token. With neither set, off-device
// writes are refused.

import (
	"crypto/subtle"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

func loadAPIToken(dir string) string {
	if t := strings.TrimSpace(os.Getenv("SCE_API_TOKEN")); t != "" {
		return t
	}
	if b, err := os.ReadFile(filepath.Join(dir, "state", "api_token")); err == nil {
		return strings.TrimSpace(strings.SplitN(string(b), "\n", 2)[0])
	}
	return ""
}

func isLoopback(remoteAddr string) bool {
	host, _, err := net.SplitHostPort(remoteAddr)
	if err != nil {
		host = remoteAddr
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}

func (s *Server) guard(next http.Handler) http.Handler {
	token := loadAPIToken(s.dir)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet || r.Method == http.MethodHead || isLoopback(r.RemoteAddr) {
			next.ServeHTTP(w, r)
			return
		}
		got := r.Header.Get("X-API-Token")
		if token == "" || subtle.ConstantTimeCompare([]byte(got), []byte(token)) != 1 {
			http.Error(w, "changes from off the device need the X-API-Token header (see HANDBOOK 2.35)", http.StatusForbidden)
			return
		}
		next.ServeHTTP(w, r)
	})
}
