package main

// edge-agent: standalone smart-city monitor for the Qualcomm QIDK.
// Runs on the device as a native linux/arm64 binary (started via adb as the shell user), polls the
// live sensors (dashboard sliders / real devices), computes live statistics, gates anomalies and reasons over them in Mode 1/2/3 with
// Llama 3.2 3B on the Hexagon NPU through Qualcomm Genie. Serves the PWA dashboard on :8000.

import (
	"flag"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"time"
)

func main() {
	exe, _ := os.Executable()
	defDir := filepath.Dir(exe)
	dir := flag.String("dir", defDir, "app directory (contains data/, web/, state/)")
	port := flag.String("addr", "0.0.0.0:8000", "listen address")
	runtime := flag.String("genie", "/data/local/tmp/genie_bundle", "Genie runtime + base model bundle dir")
	mock := flag.Bool("mock", false, "development only: fake LLM responses (never on device)")
	mode := flag.Int("mode", 3, "initial reasoning mode 1|2|3")
	speed := flag.Int("speed", 1, "readings (5-minute buckets) taken per poll")
	poll := flag.Int("poll-ms", 2000, "poll interval in ms")
	clockUnix := flag.Int64("clock-unix", 0, "correct wall clock: current unix time (device clocks can be wrong)")
	flag.Parse()
	if *clockUnix > 0 {
		clockOffset = time.Unix(*clockUnix, 0).Sub(time.Now())
		if !needClockFix() {
			log.Printf("device clock already synced (%s), ignoring --clock-unix offset of %s", time.Now().Format(time.RFC3339), clockOffset.Round(time.Second))
			clockOffset = 0
		} else {
			log.Printf("clock corrected by %s", clockOffset.Round(time.Second))
		}
	}

	initThermal()
	eng, err := NewEngine(*dir)
	if err != nil {
		log.Fatalf("engine: %v", err)
	}
	eng.Speed, eng.PollMs = *speed, *poll
	genie := NewGenieRunner(*runtime, *dir, *mock)
	// persistent Genie dialog (genieclient.go): pays model init once instead of on every call;
	// absent or failed, every call falls back to the per-call CLI exactly as before
	htpdWorkDir = *dir
	if htpdEnabled() {
		superviseHtpd(genie, *dir) // batched NPU engine; genied stays stopped (HANDBOOK 2.37)
	} else {
		superviseDaemon(genie, *dir)
	}
	hub := NewHub()
	rsn := NewReasoner(genie, eng, *dir, hub.Publish)
	rsn.Mode = *mode
	eng.onEvent = rsn.HandleCandidates
	eng.onTick = func(sim int64) {
		hub.Publish("tick", map[string]any{"sim_time": sim, "sim_time_ist": time.Unix(sim, 0).In(IST).Format("Mon 02 Jan 15:04"), "npu": genie.Status()})
		// push live sensor values to the dashboard (no polling needed)
		_, states, _ := eng.Snapshot()
		live := make([]map[string]any, 0, len(states))
		for _, st := range states {
			live = append(live, map[string]any{"node": st.Node, "metric": st.Metric, "role": st.Role, "last": st.Last,
				"sma_1h": st.SMA1h, "ema_1h": st.EMA1h, "slope_per_h": st.SlopePerH, "pattern": st.Pattern,
				"status": st.Status, "injected": st.Injected, "data_ok": st.DataOK, "updated": st.Updated,
				"abnormal_for": st.AbnormalFor, "reported": st.Reported, "persist_readings": persistReadings})
		}
		hub.Publish("live", map[string]any{"sim_time": sim, "sensors": live})
	}
	go func() {
		for {
			eng.mu.RLock()
			ms := eng.PollMs
			eng.mu.RUnlock()
			time.Sleep(time.Duration(ms) * time.Millisecond)
			eng.Tick()
		}
	}()
	srv := &Server{eng: eng, rsn: rsn, genie: genie, hub: hub, dir: *dir, start: time.Now()}
	log.Printf("edge-agent: %d live sensors (sliders / %s), clock from %s, agent model: %s (available=%v), listening on %s",
		len(eng.states), "/api/ingest", eng.Meta.StartIST, genie.AgentModel().Name, genie.AgentModel().Available, *port)
	// header and idle timeouts stop slow or abandoned clients holding connections open; no write
	// timeout, because /api/events is a long-lived stream
	hsrv := &http.Server{Addr: *port, Handler: srv.routes(), ReadHeaderTimeout: 10 * time.Second,
		IdleTimeout: 120 * time.Second, MaxHeaderBytes: 64 << 10}
	log.Fatal(hsrv.ListenAndServe())
}
