package main

// Heartbeat (ROADMAP 2026-11-09 §4 "Monitoring"). OFF unless heartbeat_url is set or the fog uploader is on.
//
//	heartbeat_url=http://laptop:8787/heartbeat   POST of the health snapshot (tools/heartbeat_monitor.py raises the
//	                                              dead-man alert when they stop; any webhook works)
//	heartbeat_s=60                                period
//	board_id= / site_id=                          names on every snapshot (and every fog row)
//
// With the fog uploader on (prod_fog.go), each snapshot is also queued as a "health" row. A failed POST is not
// retried: the next snapshot replaces it, and silence is exactly what the monitor watches for.

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"time"
)

type heartbeat struct {
	url   string
	every time.Duration
	snap  func() map[string]any
	fog   *fogUploader
	sent  int
	fails int
}

func newHeartbeatFromProfile(s *Server) *heartbeat {
	u := profStr("heartbeat_url")
	if u == "" && prod.fog == nil {
		return nil
	}
	return &heartbeat{url: u, every: time.Duration(profInt("heartbeat_s", 60, 5, 3600)) * time.Second,
		snap: func() map[string]any { return healthSnapshot(s) }, fog: prod.fog}
}

// healthSnapshot: what the dead-man monitor and the fog see of the board.
func healthSnapshot(s *Server) map[string]any {
	sim, states, _ := s.eng.Snapshot()
	silent, faults := 0, 0
	for _, st := range states {
		if !st.DataOK {
			silent++
		}
		if st.Status == "sensor_fault" {
			faults++
		}
	}
	s.rsn.mu.RLock()
	q := map[string]any{"active": s.rsn.active, "pending": len(s.rsn.pending), "jobs": len(s.rsn.jobs),
		"early": len(s.rsn.early), "refines": len(s.rsn.refines), "cool_wait": s.rsn.coolWait}
	incs := s.rsn.visibleCountLocked()
	s.rsn.mu.RUnlock()
	npu := map[string]any{"engine": npuEngine(), "status": s.genie.Status(), "reasoner": reasonerModelLabel()}
	if htpdEnabled() {
		npu["htpd_up"] = htpdUp()
	}
	if prod.alert != nil {
		q["alerts"] = prod.alert.Stats()["queued"]
	}
	if prod.fog != nil {
		q["fog_outbox_bytes"] = prod.fog.Stats()["outbox_bytes"]
	}
	out := map[string]any{"kind": "heartbeat", "board_id": profStr("board_id"), "site_id": profStr("site_id"),
		"ts": nowTime().Unix(), "clock_valid": clockValid(), "uptime_s": int(time.Since(s.start).Seconds()),
		"sim_time": sim, "incidents": incs, "sensors": len(states), "sensors_silent": silent, "sensor_faults": faults,
		"npu": npu, "queues": q, "device": deviceStats(), "agent": agentVer}
	out["restarts_7d"], out["restarts_24h"] = restartCounts(s.dir, nowTime())
	if prod.mqtt != nil {
		out["mqtt"] = prod.mqtt.Stats()
	}
	return out
}

// Beat sends one snapshot. Returns the POST error (nil when no URL).
func (h *heartbeat) Beat() error {
	snap := h.snap()
	if h.fog != nil {
		h.fog.Enqueue("health", "", snap)
	}
	if h.url == "" {
		return nil
	}
	b, _ := json.Marshal(snap)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, h.url, bytes.NewReader(b))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if tok := profStr("heartbeat_token"); tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	resp, err := http.DefaultClient.Do(req)
	if err == nil {
		if resp.StatusCode/100 == 2 {
			noteHTTPDate(resp.Header, "heartbeat Date header")
		}
		io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
		resp.Body.Close()
	}
	if err == nil && resp.StatusCode/100 != 2 {
		err = &httpStatusErr{resp.StatusCode}
	}
	if err != nil {
		h.fails++
	} else {
		h.sent++
	}
	return err
}

type httpStatusErr struct{ code int }

func (e *httpStatusErr) Error() string { return "HTTP " + http.StatusText(e.code) }

func (h *heartbeat) Run(stop <-chan struct{}) {
	h.Beat() // one at start: the monitor sees a reboot at once (uptime resets)
	t := time.NewTicker(h.every)
	defer t.Stop()
	for {
		select {
		case <-stop:
			return
		case <-t.C:
			h.Beat()
		}
	}
}
