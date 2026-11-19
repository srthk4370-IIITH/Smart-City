package main

import (
	"bytes"
	"encoding/json"
	"net"
	"net/http"
	"os/exec"
	"strconv"
	"strings"
	"testing"
	"time"
)

func testServer(t *testing.T) *Server {
	t.Helper()
	dir := t.TempDir()
	e := dqEngine(t)
	g := NewGenieRunner(dir, dir, true)
	r := NewReasoner(g, e, dir, func(string, any) {})
	return &Server{eng: e, rsn: r, genie: g, dir: dir, start: time.Now().Add(-90 * time.Second)}
}

func TestHeartbeatSnapshotAndFog(t *testing.T) {
	s := testServer(t)
	sk := newSink(t)
	t.Setenv("SCE_BOARD_ID", "qidk-1")
	f := newFogUploader(s.dir, s.eng)
	h := &heartbeat{url: sk.srv.URL, every: time.Minute, snap: func() map[string]any { return healthSnapshot(s) }, fog: f}
	if err := h.Beat(); err != nil {
		t.Fatal(err)
	}
	if sk.n() != 1 {
		t.Fatal("no heartbeat")
	}
	got := sk.got[0]
	for _, k := range []string{"uptime_s", "npu", "queues", "device", "clock_valid", "sensors_silent", "sim_time"} {
		if _, ok := got[k]; !ok {
			t.Errorf("snapshot lacks %s: %v", k, got)
		}
	}
	if got["board_id"] != "qidk-1" || got["uptime_s"].(float64) < 89 {
		t.Errorf("snapshot %v", got)
	}
	rows := f.readRows(0, 10)
	if len(rows) != 1 || rows[0].Kind != "health" {
		t.Fatalf("fog rows %+v", rows)
	}
	sk.setFail(true)
	if h.Beat() == nil {
		t.Error("a failed POST did not report")
	}
}

// tools/heartbeat_monitor.py: a board that stops sending is reported dead once, and recovered when it is back.
func TestHeartbeatMonitorScript(t *testing.T) {
	py, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("python3 not installed")
	}
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	port := ln.Addr().(*net.TCPAddr).Port
	ln.Close()
	alerts := newSink(t)
	cmd := exec.Command(py, "../tools/heartbeat_monitor.py", "--host", "127.0.0.1", "--port", strconv.Itoa(port), "--dead-s", "1",
		"--check-s", "0.2", "--alert-url", alerts.srv.URL)
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	defer cmd.Process.Kill()
	url := "http://127.0.0.1:" + strconv.Itoa(port) + "/heartbeat"
	post := func(up int) error {
		b, _ := json.Marshal(map[string]any{"board_id": "qidk-1", "uptime_s": up, "clock_valid": true, "npu": map[string]any{"htpd_up": true}})
		resp, err := http.Post(url, "application/json", bytes.NewReader(b))
		if err == nil {
			resp.Body.Close()
		}
		return err
	}
	waitFor(t, "monitor up", 10*time.Second, func() bool { return post(100) == nil })
	waitFor(t, "dead-man alert", 5*time.Second, func() bool { return alerts.n() >= 1 })
	if txt, _ := alerts.got[0]["text"].(string); !strings.Contains(txt, "silent") {
		t.Fatalf("alert %v", alerts.got)
	}
	post(5) // back, and rebooted (uptime went down)
	waitFor(t, "recovered + restart", 5*time.Second, func() bool { return alerts.n() >= 3 })
	all := ""
	for _, m := range alerts.got {
		all += m["text"].(string) + "\n"
	}
	if !strings.Contains(all, "recovered") || !strings.Contains(all, "restarted") {
		t.Fatalf("alerts:\n%s", all)
	}
}
