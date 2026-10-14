package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

type Target struct {
	Node   string   `json:"node"`
	Metric string   `json:"metric"`
	Kind   string   `json:"kind"`
	Dur    int      `json:"duration_buckets"`
	Amp    float64  `json:"amplitude"`
	Hold   bool     `json:"hold"`
	Alt    []string `json:"alternatives,omitempty"` // other nodes (same metric) used if the primary is idle/noisy now
}

type Scenario struct {
	ID          string   `json:"id"`
	Title       string   `json:"title"`
	Description string   `json:"description"`
	Domains     []string `json:"domains"`
	Targets     []Target `json:"targets"`
}

var Scenarios = []Scenario{
	{"ventilation_failure", "Ventilation failure (KH level 03)", "CO2 rises exponentially in a room on KH level 03.", []string{"air_quality"},
		[]Target{{"SR-AQ-KH03-03", "co2", "exp_rise", 30, 1300, false, nil}}},
	{"pm_spike", "Outdoor PM2.5 spike", "Short burst of PM2.5 at the VN outdoor air station (e.g. nearby burning).", []string{"air_quality"},
		[]Target{{"AQ-VN90-00", "pm25", "spike", 8, 120, false, []string{"AQ-KN00-00"}}}},
	{"power_throttling", "Load hits a ceiling (throttling)", "Room load on KH level 04 climbs and then flat-lines at a cap.", []string{"power"},
		[]Target{{"SR-EM-KH04-01", "power_kw", "throttle", 30, 18, false, nil}}},
	{"load_surge", "Load surge spike (KH level 04)", "Short power spike on a KH level-04 room energy meter.", []string{"power"},
		[]Target{{"SR-EM-KH04-02", "power_kw", "spike", 8, 30, false, []string{"SR-EM-KH04-01", "SR-EM-KH04-00", "EM-CR-SB00-00"}}}},
	{"tank_leak", "Tank level falling (possible leak)", "KH tank level drains steadily without refill.", []string{"water"},
		[]Target{{"WM-WL-KH98-00", "level", "ramp_down", 36, 45, true, nil}}},
	{"pump_cycling", "Pump cycling (tank level)", "The KH tank level swings up and down repeatedly as the pump cycles on and off.", []string{"water"},
		[]Target{{"WM-WL-KH00-00", "level", "oscillate", 36, 8, false, []string{"WM-WL-KH98-00"}}}},
	{"stuck_sensor", "Stuck temperature sensor", "Indoor temperature freezes at one value.", []string{"air_quality"},
		[]Target{{"SR-AQ-KH00-02", "temp", "flatline", 30, 0, false, []string{"SR-AQ-KH03-03"}}}},
	{"heat_buildup", "Heat build-up", "Outdoor temperature climbs steadily at the rooftop station.", []string{"weather"},
		[]Target{{"WE-VN04-00", "temp", "ramp_up", 36, 8, false, nil}}},
	{"off_hours_presence", "Presence at night", "A KH room reports occupancy (best demonstrated when the replay clock is 22:00-06:00).", []string{"occupancy"},
		[]Target{{"SR-OC-GW-KH95-22", "occ", "set", 24, 1, false, []string{"SR-OC-GW-KH95-01"}}}},
	{"crowded_room", "Crowded room (cross-domain)", "Occupancy turns on, CO2 climbs and room power steps up together.", []string{"occupancy", "air_quality", "power"},
		[]Target{{"SR-OC-GW-KH95-01", "occ", "set", 36, 1, false, nil},
			// SR-AQ-KH95-00 is not present in every topology; fall back to the KH03 AQ node so the
			// cross-domain scenario stays injectable (PickTargets only remaps via Alt).
			{"SR-AQ-KH95-00", "co2", "ramp_up", 36, 900, false, []string{"SR-AQ-KH03-03"}},
			{"SR-EM-KH04-01", "power_kw", "step_up", 36, 6, false, []string{"SR-EM-KH04-02", "SR-EM-KH04-00"}}}},
}

// ---------------------------------------------------------------- SSE hub
type Hub struct {
	mu   sync.Mutex
	subs map[chan []byte]bool
}

func NewHub() *Hub { return &Hub{subs: map[chan []byte]bool{}} }

func (h *Hub) Publish(kind string, data any) {
	b, _ := json.Marshal(data)
	msg := []byte(fmt.Sprintf("event: %s\ndata: %s\n\n", kind, b))
	h.mu.Lock()
	for c := range h.subs {
		select {
		case c <- msg:
		default:
		}
	}
	h.mu.Unlock()
}

func (h *Hub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	fl, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "stream unsupported", 500)
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	c := make(chan []byte, 64)
	h.mu.Lock()
	h.subs[c] = true
	h.mu.Unlock()
	defer func() { h.mu.Lock(); delete(h.subs, c); h.mu.Unlock() }()
	fmt.Fprint(w, ": connected\n\n")
	fl.Flush()
	ping := time.NewTicker(15 * time.Second)
	defer ping.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case m := <-c:
			w.Write(m)
			fl.Flush()
		case <-ping.C:
			fmt.Fprint(w, ": ping\n\n")
			fl.Flush()
		}
	}
}

// ---------------------------------------------------------------- HTTP API
type Server struct {
	eng   *Engine
	rsn   *Reasoner
	genie *GenieRunner
	hub   *Hub
	dir   string
	start time.Time
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	json.NewEncoder(w).Encode(v)
}

func readBody(r *http.Request, v any) error {
	defer r.Body.Close()
	return json.NewDecoder(r.Body).Decode(v)
}

// Thermal zones by type (read once). NPU = nsphvx/nsphmx junctions, skin = skin-msm-therm.
var thermalZones = map[string][]string{}

func initThermal() {
	files, _ := filepath.Glob("/sys/class/thermal/thermal_zone*/type")
	for _, f := range files {
		b, err := os.ReadFile(f)
		if err != nil {
			continue
		}
		t := strings.TrimSpace(string(b))
		temp := filepath.Join(filepath.Dir(f), "temp")
		switch {
		case strings.HasPrefix(t, "nsp"):
			thermalZones["npu"] = append(thermalZones["npu"], temp)
		case strings.Contains(t, "skin"):
			thermalZones["skin"] = append(thermalZones["skin"], temp)
		case strings.HasPrefix(t, "cpu"):
			thermalZones["cpu"] = append(thermalZones["cpu"], temp)
		}
	}
}

func zoneMax(kind string) float64 {
	m := 0.0
	for _, f := range thermalZones[kind] {
		b, err := os.ReadFile(f)
		if err != nil {
			continue
		}
		v, err := strconv.ParseFloat(strings.TrimSpace(string(b)), 64)
		if err != nil || v <= 0 {
			continue
		}
		if v > 1000 {
			v /= 1000
		}
		if v < 150 && v > m {
			m = v
		}
	}
	return m
}

// ThermalHot: NPU junction >= 88 C or skin >= 60 C -> defer real-data LLM incidents (thermal guard).
func ThermalHot() (bool, float64, float64) {
	// Test hook: the guard's queue-and-resume path cannot be exercised by heating a real board to
	// 88 C on demand, so SCE_THERMAL_FAKE names a file containing "hot" or "cool". Unset in production.
	if f := os.Getenv("SCE_THERMAL_FAKE"); f != "" {
		b, _ := os.ReadFile(f)
		if strings.TrimSpace(string(b)) == "hot" {
			return true, 90, 61
		}
		return false, 40, 35
	}
	npu, skin := zoneMax("npu"), zoneMax("skin")
	return npu >= 88 || skin >= 60, npu, skin
}

func deviceStats() map[string]any {
	hot, npu, skin := ThermalHot()
	memAvail := 0.0
	if b, err := os.ReadFile("/proc/meminfo"); err == nil {
		for _, l := range strings.Split(string(b), "\n") {
			if strings.HasPrefix(l, "MemAvailable:") {
				f := strings.Fields(l)
				kb, _ := strconv.ParseFloat(f[1], 64)
				memAvail = kb / 1024
			}
		}
	}
	return map[string]any{"thermal_max_c": npu, "npu_c": npu, "skin_c": skin, "cpu_c": zoneMax("cpu"),
		"thermal_guard": hot, "mem_available_mb": int(memAvail)}
}

func (s *Server) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/status", func(w http.ResponseWriter, r *http.Request) {
		s.genie.Refresh()
		sim, _, inj := s.eng.Snapshot()
		s.eng.mu.RLock()
		replay := map[string]any{"start": s.eng.Meta.Start, "speed_buckets_per_poll": s.eng.Speed,
			"poll_ms": s.eng.PollMs, "playing": s.eng.Playing, "noise_scale": s.eng.NoiseScale,
			"source": "live sensors: dashboard sliders and /api/ingest (one 5-minute reading per sensor per poll)"}
		s.eng.mu.RUnlock()
		s.rsn.mu.RLock()
		mode := s.rsn.Mode
		n := len(s.rsn.incidents)
		s.rsn.mu.RUnlock()
		writeJSON(w, map[string]any{
			"sim_time": sim, "sim_time_ist": time.Unix(sim, 0).In(IST).Format("Mon 02 Jan 2006 15:04"),
			"mode": mode, "replay": replay, "injections": inj,
			"models": map[string]any{"agent": s.genie.AgentModel(), "reasoner": s.genie.Base, "base": s.genie.Base, "tuned": s.genie.Tuned},
			"npu":    s.genie.Status(), "device": deviceStats(), "incidents": n, "uptime_s": int(time.Since(s.start).Seconds()),
			// whether the persistent-dialog fast path is live, so a silent fallback to the
			// per-call CLI (which costs ~700 ms of model init per request) is visible
			"genie_daemon": daemonStatus(),
			"running_on":   runningOn(),
		})
	})
	mux.HandleFunc("/api/live", func(w http.ResponseWriter, r *http.Request) {
		sim, states, _ := s.eng.Snapshot()
		byRole := map[string][]SensorState{}
		for _, st := range states {
			st.Finding = nil
			byRole[st.Role] = append(byRole[st.Role], st)
		}
		roles := map[string]any{}
		for role, list := range byRole {
			// card header: real warnings/criticals outrank sensor faults (faults stay visible per tile)
			rank := map[string]int{"critical": 3, "warning": 2, "sensor_fault": 1}
			worst := "normal"
			for _, st := range list {
				if rank[st.Status] > rank[worst] {
					worst = st.Status
				}
			}
			roles[role] = map[string]any{"status": worst, "sensors": list}
		}
		writeJSON(w, map[string]any{"sim_time": sim, "roles": roles})
	})
	mux.HandleFunc("/api/series", func(w http.ResponseWriter, r *http.Request) {
		h, _ := strconv.Atoi(r.URL.Query().Get("hours"))
		if h <= 0 || h > 24 {
			h = 8
		}
		writeJSON(w, s.eng.Series(r.URL.Query().Get("node"), r.URL.Query().Get("metric"), h))
	})
	mux.HandleFunc("/api/topology", func(w http.ResponseWriter, r *http.Request) {
		type bnode struct {
			Node string `json:"node"`
			NodeInfo
		}
		build := map[string]map[string][]bnode{}
		for n, info := range s.eng.Meta.Nodes {
			if build[info.Building] == nil {
				build[info.Building] = map[string][]bnode{}
			}
			build[info.Building][info.Level] = append(build[info.Building][info.Level], bnode{n, info})
		}
		for _, lv := range build {
			for k := range lv {
				sort.Slice(lv[k], func(i, j int) bool { return lv[k][i].Node < lv[k][j].Node })
			}
		}
		writeJSON(w, map[string]any{"buildings": build, "source_weeks": s.eng.Meta.SourceWeeks, "coverage": s.eng.Meta.Coverage})
	})
	mux.HandleFunc("/api/incidents", func(w http.ResponseWriter, r *http.Request) {
		list := s.rsn.List()
		type sum struct {
			ID, State, Severity, Title, CreatedWall, Approval, Label string
			Mode, NPUCalls                                           int
			CreatedSim                                               int64
			Roles                                                    []string
			Injected                                                 bool
			TotalMs                                                  float64
		}
		out := []map[string]any{}
		for _, i := range list {
			lab := i.Mode1.Label
			if i.Final != nil && i.Final.Parsed != nil {
				lab = i.Final.Parsed.Label
			}
			out = append(out, map[string]any{"id": i.ID, "state": i.State, "severity": i.Severity, "title": i.Title, "mode": i.Mode,
				"created_sim": i.CreatedSim, "created_sim_ist": time.Unix(i.CreatedSim, 0).In(IST).Format("Mon 15:04"),
				"created_wall": i.CreatedWall, "roles": i.Roles, "injected": i.Injected, "label": lab, "approval": i.Approval,
				"npu_calls": i.NPUCalls, "total_ms": i.TotalMs})
		}
		writeJSON(w, out)
	})
	mux.HandleFunc("/api/incidents/", func(w http.ResponseWriter, r *http.Request) {
		parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/api/incidents/"), "/")
		inc := s.rsn.Get(parts[0])
		if inc == nil {
			http.Error(w, "not found", 404)
			return
		}
		if len(parts) == 2 && r.Method == http.MethodPost {
			var body struct {
				Note string `json:"note"`
			}
			readBody(r, &body)
			// A decision before the analysis has finished would approve a recommendation the operator
			// has not seen yet (found by the app stress test: approve on a running incident returned
			// 200 and was recorded). The dashboard already disables the button; the API must agree.
			if (parts[1] == "approve" || parts[1] == "dismiss") && inc.State == "running" {
				http.Error(w, "analysis still running - decide once the report is ready", http.StatusConflict)
				return
			}
			switch parts[1] {
			case "approve":
				s.rsn.SetApproval(inc.ID, "approved", body.Note)
			case "dismiss":
				if strings.TrimSpace(body.Note) == "" {
					http.Error(w, "dismiss needs a note", 400)
					return
				}
				s.rsn.SetApproval(inc.ID, "dismissed", body.Note)
			case "rerun":
				mode, _ := strconv.Atoi(r.URL.Query().Get("mode"))
				if mode < 1 || mode > 3 {
					mode = 3
				}
				var cands []Candidate
				for _, sr := range inc.Sensors {
					if sr.Context {
						continue // the orchestrator rebuilds the same related-domain context
					}
					cands = append(cands, Candidate{sr.Node, sr.Metric, sr.Role, sr.Rule, sr.Xs, sr.End, sr.Injected})
				}
				s.rsn.Submit(cands, mode) // queued behind current work, never interleaved with it
			default:
				http.Error(w, "unknown action "+parts[1]+" (approve, dismiss, rerun)", 400)
				return
			}
			writeJSON(w, map[string]any{"ok": true})
			return
		}
		writeJSON(w, inc)
	})
	mux.HandleFunc("/api/mode", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Mode int `json:"mode"`
		}
		if readBody(r, &body) != nil || body.Mode < 1 || body.Mode > 3 {
			http.Error(w, "mode must be 1, 2 or 3", 400)
			return
		}
		s.rsn.mu.Lock()
		s.rsn.Mode = body.Mode
		s.rsn.mu.Unlock()
		s.hub.Publish("mode", map[string]int{"mode": body.Mode})
		writeJSON(w, map[string]int{"mode": body.Mode})
	})
	mux.HandleFunc("/api/replay", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Playing *bool  `json:"playing"`
			Speed   int    `json:"speed"`
			PollMs  int    `json:"poll_ms"`
			Restart bool   `json:"restart"`
			Clock   string `json:"clock"` // "HH:MM" sensor time of day
		}
		readBody(r, &body)
		if body.Clock != "" {
			var hh, mm int
			if _, err := fmt.Sscanf(body.Clock, "%d:%d", &hh, &mm); err != nil || hh < 0 || hh > 23 || mm < 0 || mm > 59 {
				http.Error(w, "clock must be HH:MM", 400)
				return
			}
			s.eng.SetClock(hh*60 + mm)
		}
		s.eng.mu.Lock()
		if body.Playing != nil {
			s.eng.Playing = *body.Playing
		}
		if body.Speed >= 1 && body.Speed <= 12 {
			s.eng.Speed = body.Speed
		}
		if body.PollMs >= 500 && body.PollMs <= 10000 {
			s.eng.PollMs = body.PollMs
		}
		if body.Restart {
			s.eng.injects = nil
			s.eng.reset()
		}
		out := map[string]any{"playing": s.eng.Playing, "speed": s.eng.Speed, "poll_ms": s.eng.PollMs,
			"sensor_time_ist": time.Unix(s.eng.sim, 0).In(IST).Format("15:04")}
		s.eng.mu.Unlock()
		writeJSON(w, out)
	})
	// Live sensor bank. GET lists sensors with ranges + current values; POST sets values (sliders).
	//   POST /api/sensors {"node":..,"metric":..,"value":..}      one sensor
	//   POST /api/sensors {"values":[{"node","metric","value"},..]} several at once
	//   POST /api/sensors {"reset_values":true} | {"noise_scale":0..3}
	mux.HandleFunc("/api/sensors", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodPost {
			type one struct {
				Node   string   `json:"node"`
				Metric string   `json:"metric"`
				Value  *float64 `json:"value"`
			}
			var body struct {
				one
				Values      []one    `json:"values"`
				ResetValues bool     `json:"reset_values"`
				NoiseScale  *float64 `json:"noise_scale"`
			}
			if readBody(r, &body) != nil {
				http.Error(w, "bad JSON", 400)
				return
			}
			if body.ResetValues {
				s.eng.ResetValues()
			}
			if body.NoiseScale != nil && *body.NoiseScale >= 0 && *body.NoiseScale <= 3 {
				s.eng.mu.Lock()
				s.eng.NoiseScale = *body.NoiseScale
				s.eng.mu.Unlock()
			}
			if body.Value != nil {
				body.Values = append(body.Values, body.one)
			}
			for _, v := range body.Values {
				if v.Value == nil {
					continue
				}
				if _, err := s.eng.SetSensor(v.Node, v.Metric, *v.Value, "slider"); err != nil {
					http.Error(w, err.Error(), 400)
					return
				}
			}
		}
		s.eng.mu.RLock()
		ns := s.eng.NoiseScale
		s.eng.mu.RUnlock()
		writeJSON(w, map[string]any{"noise_scale": ns, "sensors": s.eng.Sensors()})
	})
	// Real-device feed, same effect as a slider: {"node":..,"metric":..,"value":..}
	mux.HandleFunc("/api/ingest", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Node   string   `json:"node"`
			Metric string   `json:"metric"`
			Value  *float64 `json:"value"`
		}
		if r.Method != http.MethodPost || readBody(r, &body) != nil || body.Value == nil {
			http.Error(w, `POST {"node":"SR-AQ-KH03-03","metric":"co2","value":850}`, 400)
			return
		}
		v, err := s.eng.SetSensor(body.Node, body.Metric, *body.Value, "api")
		if err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		s.hub.Publish("ingest", map[string]any{"node": body.Node, "metric": body.Metric, "value": v})
		writeJSON(w, map[string]any{"ok": true, "stored": v})
	})
	mux.HandleFunc("/api/scenarios", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, Scenarios) })
	mux.HandleFunc("/api/inject", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Scenario string `json:"scenario"`
		}
		readBody(r, &body)
		if body.Scenario == "clear" {
			s.eng.ClearInjections()
			writeJSON(w, map[string]any{"ok": true})
			return
		}
		for _, sc := range Scenarios {
			if sc.ID == body.Scenario {
				sc.Targets = s.eng.PickTargets(sc.Targets)
				for _, t := range sc.Targets {
					if _, ok := s.eng.states[key(t.Node, t.Metric)]; !ok {
						http.Error(w, "scenario target "+t.Node+" "+t.Metric+" is not a live sensor", 400)
						return
					}
				}
				inj := s.eng.Inject(sc)
				s.hub.Publish("inject", map[string]any{"scenario": sc.ID, "title": sc.Title})
				writeJSON(w, map[string]any{"ok": true, "injections": inj})
				return
			}
		}
		http.Error(w, "unknown scenario", 400)
	})
	mux.HandleFunc("/api/analyze", func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Node   string `json:"node"`
			Metric string `json:"metric"`
			Mode   int    `json:"mode"`
		}
		readBody(r, &body)
		s.eng.mu.RLock()
		info, ok := s.eng.Meta.Nodes[body.Node]
		xs, wok := s.eng.Window(body.Node, body.Metric, s.eng.sim)
		sim := s.eng.sim
		s.eng.mu.RUnlock()
		if !ok || !wok || info.Role == "hvac" {
			http.Error(w, "no 4-hour window available for this sensor", 400)
			return
		}
		if body.Mode < 1 || body.Mode > 3 {
			s.rsn.mu.RLock()
			body.Mode = s.rsn.Mode
			s.rsn.mu.RUnlock()
		}
		f := RuleFinding(info.Role, body.Metric, body.Node, xs, sim)
		s.rsn.Submit([]Candidate{{body.Node, body.Metric, info.Role, f, xs, sim, false}}, body.Mode)
		writeJSON(w, map[string]any{"ok": true})
	})
	mux.Handle("/api/events", s.hub)
	web := http.FileServer(http.Dir(filepath.Join(s.dir, "web")))
	// Always revalidate the dashboard files. Without this the WebView judged freshness from
	// Last-Modified, which is meaningless here: the board's clock resets to 2023 on every boot while
	// the files carry 2026 timestamps, so a new APK's UI could keep showing the previous version
	// even after the service worker was bumped. "no-cache" still allows a cheap 304 when unchanged.
	mux.Handle("/", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-cache")
		web.ServeHTTP(w, r)
	}))
	return mux
}

var runningOnCache string

// getprop runs Android's getprop by ABSOLUTE path: inside an Android app the seccomp filter kills the
// process (SIGSYS) on the faccessat2 syscall that Go's exec.LookPath uses for bare command names.
func getprop(key string) string {
	bin := "/system/bin/getprop"
	if _, err := os.Stat(bin); err != nil {
		return ""
	}
	out, err := exec.Command(bin, key).Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

func runningOn() string {
	if runningOnCache != "" {
		return runningOnCache
	}
	if model := getprop("ro.product.model"); model != "" {
		runningOnCache = fmt.Sprintf("QIDK %s (%s), Android, standalone on device", model, getprop("ro.soc.model"))
		return runningOnCache
	}
	h, _ := os.Hostname()
	runningOnCache = "development host " + h
	return runningOnCache
}
