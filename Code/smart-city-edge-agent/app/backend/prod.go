package main

// Production features (proofs/2026-11-09_production/FEATURES.md). Every feature is OFF unless its htpd_profile key
// (or the matching SCE_* environment variable) turns it on, so a board without the keys behaves exactly as before:
//
//	mqtt_url=...          MQTT ingest bridge          prod_mqtt.go
//	time_sync=1           clock check + NTP/first trusted source   prod_time.go
//	alert_webhook=... / alert_smtp=...   alert delivery            prod_alert.go
//	heartbeat_url=... / heartbeat_s=...  heartbeat + health        prod_heartbeat.go
//	fog_upload=1 (+ fog_url)             fog uploader              prod_fog.go
//	warm_idle_min=N       NPU warm-up after N min idle             prod_warm.go
//
// The keys are read once at start (a change needs an app restart), except where a file says otherwise.

import (
	"log"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync/atomic"
	"time"
)

// profStr: htpd_profile key k, or env SCE_<K> (upper case) when set.
func profStr(k string) string {
	return strings.TrimSpace(reasonerProfile(k, "SCE_"+strings.ToUpper(k)))
}

func profInt(k string, def, lo, hi int) int {
	n, err := strconv.Atoi(profStr(k))
	if err != nil || n < lo || n > hi {
		return def
	}
	return n
}

func profOn(k string) bool {
	switch strings.ToLower(profStr(k)) {
	case "1", "on", "true", "yes":
		return true
	}
	return false
}

func profList(k string) []string {
	var out []string
	for _, s := range strings.Split(profStr(k), ",") {
		if s = strings.TrimSpace(s); s != "" {
			out = append(out, s)
		}
	}
	return out
}

// persistHook receives every incident version written to the store (store.go persist), as its JSON line, with the
// Reasoner that wrote it. nil (the default) = nothing happens.
var persistHook atomic.Pointer[func(*Reasoner, []byte)]

// addPersistHook registers f for the incidents of r only (a fog box's upserted copies have their own Reasoner).
func addPersistHook(r *Reasoner, f func([]byte)) {
	addHook(func(w *Reasoner, b []byte) {
		if w == r {
			f(b)
		}
	})
}

func addHook(f func(*Reasoner, []byte)) {
	for {
		old := persistHook.Load()
		nf := f
		if old != nil {
			prev := *old
			nf = func(r *Reasoner, b []byte) { prev(r, b); f(r, b) }
		}
		if persistHook.CompareAndSwap(old, &nf) {
			return
		}
	}
}

// prodState: the running production features (nil fields = off), for the routes and the heartbeat.
type prodState struct {
	start time.Time
	mqtt  *mqttBridge
	alert *alerter
	fog   *fogUploader
	hb    *heartbeat
	warm  *idleWarmer
}

var prod = &prodState{start: time.Now()}

// startProd starts every production feature whose key is set. Called once from main after the server is built.
func startProd(s *Server) {
	prod.start = s.start
	if timeSyncEnabled() {
		startTimeSync(s.dir)
	}
	if u := profStr("mqtt_url"); u != "" {
		prod.mqtt = newMQTTBridge(mqttConfigFromProfile(), s.eng)
		safeGo("mqtt", func() { prod.mqtt.Run(nil) })
		log.Printf("prod: MQTT bridge on %s topics %v", redactURL(u), prod.mqtt.cfg.Topics)
	}
	if a := newAlerterFromProfile(s.dir); a != nil {
		prod.alert = a
		addPersistHook(s.rsn, a.OnIncident)
		safeGo("prod feature", func() { a.Run(nil) })
		log.Printf("prod: alert delivery on (%d channels)", len(a.chans))
	}
	if f := newFogUploaderFromProfile(s.dir, s.eng); f != nil {
		prod.fog = f
		addPersistHook(s.rsn, f.OnIncident)
		safeGo("prod feature", func() { f.Run(nil) })
		log.Printf("prod: fog uploader to %s every %v", redactURL(fogURL()), f.every)
	}
	if x := newSupaSync(s.dir); x != nil {
		x.s, supa = s, x
		addPersistHook(s.rsn, x.OnIncident)
		safeGo("supabase sync", func() { x.Run(nil) })
		log.Printf("prod: supabase fog (reports only) board %s", x.board)
	}
	if h := newHeartbeatFromProfile(s); h != nil {
		prod.hb = h
		safeGo("prod feature", func() { h.Run(nil) })
		log.Printf("prod: heartbeat every %v", h.every)
	}
	if w := newIdleWarmerFromProfile(s); w != nil {
		prod.warm = w
		safeGo("prod feature", func() { w.Run(nil) })
		log.Printf("prod: NPU warm-up after %v idle", w.idle)
	}
}

// prodRoutes: /api/prod/* (status, time push, self-test). Answers 404 while every feature is off, as before.
func (s *Server) prodRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/api/prod/status", func(w http.ResponseWriter, r *http.Request) {
		if !prodAny() {
			http.NotFound(w, r)
			return
		}
		writeJSON(w, prodStatus(s))
	})
	mux.HandleFunc("/api/prod/time", func(w http.ResponseWriter, r *http.Request) {
		if !timeSyncEnabled() {
			http.NotFound(w, r)
			return
		}
		handleTimePush(w, r)
	})
	mux.HandleFunc("/api/prod/selftest", func(w http.ResponseWriter, r *http.Request) {
		if !prodAny() && !profOn("selftest") {
			http.NotFound(w, r)
			return
		}
		res := selfTest(s)
		if ok, _ := res["ok"].(bool); !ok {
			w.WriteHeader(http.StatusServiceUnavailable)
		}
		writeJSON(w, res)
	})
}

func prodAny() bool {
	return prod.mqtt != nil || prod.alert != nil || prod.fog != nil || prod.hb != nil || prod.warm != nil || supa != nil || timeSyncEnabled()
}

func prodStatus(s *Server) map[string]any {
	out := map[string]any{"clock": clockStatus()}
	if campus != nil {
		st := campus.Status()
		out["campus_link"], out["campus_link_label"] = st["link"], st["link_label"]
		// night sweep 2026-11-27 #108: when the campus API went away (0 = online)
		out["campus_offline_since_unix"] = st["offline_since_unix"]
		out["campus"] = map[string]any{"link": st["link"], "online": st["online"], "offline_since_unix": st["offline_since_unix"],
			"last_error": st["last_error"]}
	}
	if prod.mqtt != nil {
		out["mqtt"] = prod.mqtt.Stats()
	}
	if prod.alert != nil {
		out["alerts"] = prod.alert.Stats()
	}
	if prod.fog != nil {
		fs := prod.fog.Stats()
		out["fog_upload"] = fs
		out["fog"] = fs // #10: contract name (offline_since_unix, last_ok_unix, last_error)
	}
	// night sweep 2026-11-27 #11: is the reports sync reaching Supabase? {queued, sent, last_ok_unix, last_error}
	out["supabase"] = supaStats()
	if prod.warm != nil {
		out["warm"] = prod.warm.Stats()
	}
	return out
}

// selfTest: the OTA health gate (fastcheck-like, no NPU call): engine ticking, store writable, htpd up when it is
// the engine, clock valid.
func selfTest(s *Server) map[string]any {
	checks := map[string]any{}
	ok := true
	sim1, _, _ := s.eng.Snapshot()
	checks["sim_time"] = sim1
	if sim1 <= 0 {
		ok = false
	}
	f, err := os.CreateTemp(s.dir+"/state", ".selftest*")
	if err == nil {
		f.Close()
		os.Remove(f.Name())
	}
	checks["store_writable"] = err == nil
	ok = ok && err == nil
	if htpdEnabled() {
		up := htpdUp()
		checks["htpd_up"] = up
		ok = ok && up
	}
	cs := clockStatus()
	checks["clock_valid"] = cs["valid"]
	checks["ok"] = ok
	return checks
}

// redactURL drops user:password from a URL for logs.
func redactURL(u string) string {
	if i := strings.Index(u, "://"); i >= 0 {
		if j := strings.LastIndex(u[i+3:], "@"); j >= 0 {
			return u[:i+3] + "***@" + u[i+3+j+1:]
		}
	}
	return u
}
