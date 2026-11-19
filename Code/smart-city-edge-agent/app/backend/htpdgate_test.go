package main

import (
	"bufio"
	"context"
	"errors"
	"io"
	"net"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// crashyHtpd: a fake htpd that drops the connection (process death mid-request) for the first `crashes` requests,
// then serves like fakeHtpd.
func crashyHtpd(t *testing.T, crashes int) (*GenieRunner, *atomic.Int32) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { ln.Close() })
	f := &fakeHtpd{answerFor: fakeAnswer}
	var n atomic.Int32
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			if int(n.Add(1)) <= crashes {
				bufio.NewReader(c).ReadBytes('\n')
				c.Close() // EOF for the client: the process died
				continue
			}
			go f.serve(c)
		}
	}()
	t.Setenv("SCE_NPU_ENGINE", "htpd")
	t.Setenv("SCE_HTPD", ln.Addr().String())
	t.Setenv("SCE_GENIE_BATCH", "")
	cool := filepath.Join(t.TempDir(), "thermal")
	os.WriteFile(cool, []byte("cool"), 0o644)
	t.Setenv("SCE_THERMAL_FAKE", cool)
	dir := t.TempDir()
	return NewGenieRunner(dir, dir, false), &n
}

func TestHtpdCrashOnFirstBatchThenRerunOK(t *testing.T) {
	g, _ := crashyHtpd(t, 1)
	b := g.AgentModel()
	p := "agent prompt" + AgentPrefill
	res := g.Run(context.Background(), b, p, AgentPrefill, 5*time.Second, nil)
	if !strings.HasPrefix(res.Error, "NPU unavailable") {
		t.Fatalf("crash not classified as NPU unavailable: %q", res.Error)
	}
	res = g.Run(context.Background(), b, p, AgentPrefill, 5*time.Second, nil) // the end-of-incident re-run
	if res.Error != "" || !strings.Contains(res.Text, `"status": "normal"`) {
		t.Fatalf("re-run: err=%q text=%q", res.Error, res.Text)
	}
}

func TestHtpdEmptyReplyIsNPUUnavailable(t *testing.T) {
	if !htpdEmptyOut(htpdOut{}) || htpdEmptyOut(htpdOut{Stop: "eos"}) || htpdEmptyOut(htpdOut{Text: "x", Tokens: 1}) {
		t.Fatal("htpdEmptyOut")
	}
	for _, e := range []error{io.EOF, io.ErrUnexpectedEOF, errors.New("read tcp: connection reset by peer"),
		errors.New("dial tcp: connection refused"), errors.New("write: broken pipe")} {
		if !htpdTransportErr(e) {
			t.Fatalf("%v not a transport failure", e)
		}
	}
	if htpdTransportErr(errors.New("read tcp: i/o timeout")) {
		t.Fatal("a timeout is a stall, not a crash")
	}
}

func TestHtpdPersistentCrashStaysUnavailable(t *testing.T) {
	g, n := crashyHtpd(t, 1000)
	b := g.AgentModel()
	p := "agent prompt" + AgentPrefill
	for i := 0; i < 3; i++ {
		res := g.Run(context.Background(), b, p, AgentPrefill, 5*time.Second, nil)
		if !strings.HasPrefix(res.Error, "NPU unavailable") || res.Text != "" {
			t.Fatalf("run %d: err=%q text=%q", i, res.Error, res.Text)
		}
	}
	if n.Load() != 3 {
		t.Fatalf("%d connections", n.Load())
	}
	// the policy gate never turns such a result into a finding, so it can never count as agreement
	call := checkAgentWin(SensorRef{}, GenieResult{Error: "NPU unavailable (x)"}, p, nil)
	if call.Valid || call.Parsed != nil {
		t.Fatal("NPU error counted as a valid finding")
	}
}

// Full path: an incident whose agents hit a persistently crashing htpd is logged "agent not run" and flagged.
func TestHtpdCrashIncidentMarkedAgentNotRun(t *testing.T) {
	g, _ := crashyHtpd(t, 100000)
	e := dqEngine(t)
	ev := feedCO2(t, e, 60, 600, rep(1800, 14))
	_, ai := fpSplit(ev)
	if len(ai) == 0 {
		t.Skip("no AI candidate")
	}
	r := NewReasoner(g, e, t.TempDir(), func(string, any) {})
	r.Mode = 3
	inc := r.Process([]Candidate{ai[0].c}, 3)
	var notRun int
	for _, a := range inc.Agents {
		if a.NPUNotRun {
			notRun++
			if a.Valid || a.Parsed != nil || !strings.Contains(strings.Join(a.Errors, ";"), "NPU crashed - agent not run") {
				t.Fatalf("flagged call still looks like a judgement: %+v", a)
			}
		}
	}
	var tl string
	for _, it := range inc.Timeline {
		tl += it.Msg + "\n"
	}
	if notRun == 0 || !strings.Contains(tl, "NPU crashed - agent not run") {
		t.Fatalf("not marked (flagged %d):\n%s", notRun, tl)
	}
	if strings.Count(tl, "re-running (NPU was unavailable)") != notRun*maxNPURerun {
		t.Fatalf("expected %d re-runs per agent:\n%s", maxNPURerun, tl)
	}
}

func TestHtpdBringUpWaitsAndRetries(t *testing.T) {
	htpdReady.Store(false)
	defer htpdReady.Store(false)
	var mu sync.Mutex
	var events []string
	ev := func(s string) { mu.Lock(); events = append(events, s); mu.Unlock() }
	up, oldPid := false, true
	warmFails := 2
	b := &htpdBring{
		up: func() bool { return up },
		pids: func() []int {
			if oldPid {
				return []int{42}
			}
			return nil
		},
		start: func() {
			if oldPid { // the supervisor's start refuses while the old pid lives; here the old pid exits first
				ev("old exits")
				oldPid = false
			}
			ev("settle+start")
			up = true
		},
		kill: func(why string) { ev("kill"); up = false },
		warm: func() error {
			if warmFails > 0 {
				warmFails--
				ev("warm fail")
				return errors.New("EOF")
			}
			ev("warm ok")
			return nil
		},
		sleep: func(d time.Duration) { ev("sleep " + d.String()) },
	}
	if !b.run() || !htpdReady.Load() {
		t.Fatalf("not ready: %v", events)
	}
	want := "old exits,settle+start,sleep 20s,warm fail,kill,sleep 3s,settle+start,sleep 20s,warm fail,kill,sleep 10s,settle+start,sleep 20s,warm ok"
	if got := strings.Join(events, ","); got != want {
		t.Fatalf("events\n got %s\nwant %s", got, want)
	}
}

func TestHtpdBringUpGivesUpAfterFiveTries(t *testing.T) {
	htpdReady.Store(false)
	var starts int
	up := false
	b := &htpdBring{up: func() bool { return up }, pids: func() []int { return nil },
		start: func() { starts++; up = true }, kill: func(string) { up = false },
		warm: func() error { return errors.New("connection reset") }, sleep: func(time.Duration) {}}
	if b.run() || htpdReady.Load() || starts != 5 {
		t.Fatalf("ready=%v starts=%d", htpdReady.Load(), starts)
	}
}

func TestHtpdWaitReadyDrivesBringUp(t *testing.T) {
	htpdReady.Store(false)
	htpdGateOn.Store(true)
	defer func() { htpdGateOn.Store(false); htpdBringHook.Store(nil); htpdReady.Store(false) }()
	var called atomic.Int32
	h := func() bool { called.Add(1); htpdReady.Store(true); return true }
	htpdBringHook.Store(&h)
	// a listener so htpdUp() is true after the hook marks ready
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	defer ln.Close()
	t.Setenv("SCE_HTPD", ln.Addr().String())
	if !htpdWaitReady(context.Background(), time.Second) || called.Load() != 1 {
		t.Fatal("hook not used")
	}
	if !htpdWaitReady(context.Background(), time.Second) || called.Load() != 1 {
		t.Fatal("ready state not reused")
	}
}
