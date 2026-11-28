package main

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// sink: a local HTTP endpoint standing in for ntfy / Slack / an SMS gateway.
type sink struct {
	mu   sync.Mutex
	fail bool
	got  []map[string]any
	hdrs []http.Header
	srv  *httptest.Server
}

func newSink(t *testing.T) *sink {
	s := &sink{}
	s.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()
		defer s.mu.Unlock()
		if s.fail {
			http.Error(w, "down", 503)
			return
		}
		b, _ := io.ReadAll(r.Body)
		var m map[string]any
		if json.Unmarshal(b, &m) != nil {
			m = map[string]any{"text": string(b)}
		}
		s.got = append(s.got, m)
		s.hdrs = append(s.hdrs, r.Header.Clone())
	}))
	t.Cleanup(s.srv.Close)
	return s
}

func (s *sink) n() int { s.mu.Lock(); defer s.mu.Unlock(); return len(s.got) }

func (s *sink) setFail(f bool) { s.mu.Lock(); s.fail = f; s.mu.Unlock() }

func incJSON(id, sev, approval string, acked int64, injected bool) []byte {
	b, _ := json.Marshal(map[string]any{"id": id, "state": "done", "severity": sev, "title": "CO2 rising in KH03", "approval": approval,
		"acked_at": acked, "injected": injected, "created_wall": "2026-11-15 10:00:00",
		"sensors": []map[string]any{{"node": "SR-AQ-KH03-03", "metric": "co2", "location": "KH level 03"}}})
	return b
}

type fakeClock struct{ t time.Time }

func (c *fakeClock) now() time.Time { return c.t }

func testAlerter(t *testing.T, file string, main, esc *sink) (*alerter, *fakeClock) {
	var escal []alertChan
	if esc != nil {
		escal = []alertChan{webhookChan("escalate_webhook", esc.srv.URL, "json", "")}
	}
	a := newAlerter(file, []alertChan{webhookChan("webhook1", main.srv.URL, "json", "")}, escal)
	clk := &fakeClock{time.Unix(1_800_000_000, 0)}
	a.now = clk.now
	return a, clk
}

func TestAlertCriticalDedupInjected(t *testing.T) {
	s := newSink(t)
	a, _ := testAlerter(t, filepath.Join(t.TempDir(), "q.json"), s, nil)
	a.OnIncident(incJSON("INC-0001", "critical", "pending", 0, false))
	a.OnIncident(incJSON("INC-0001", "critical", "pending", 0, false)) // the same incident stored again
	a.OnIncident(incJSON("INC-0002", "critical", "pending", 0, true))  // demo injection: no page
	a.OnIncident(incJSON("INC-0003", "warning", "pending", 0, false))  // warnings off by default
	a.Tick()
	if s.n() != 1 || s.got[0]["reason"] != "critical" || s.got[0]["incident"] != "INC-0001" {
		t.Fatalf("got %v", s.got)
	}
	a.OnIncident(incJSON("INC-0001", "critical", "pending", 0, false))
	a.Tick()
	if s.n() != 1 {
		t.Fatalf("duplicate sent: %d", s.n())
	}
	a.OnIncident(incJSON("INC-0003", "warning", "approved", 0, false)) // operator approved: alert
	a.Tick()
	if s.n() != 2 || s.got[1]["reason"] != "approved" {
		t.Fatalf("approved: %v", s.got)
	}
}

// A dead channel: retried with backoff, and the queue survives a restart.
func TestAlertRetryPersistsAcrossRestart(t *testing.T) {
	s := newSink(t)
	file := filepath.Join(t.TempDir(), "q.json")
	a, clk := testAlerter(t, file, s, nil)
	s.setFail(true)
	a.OnIncident(incJSON("INC-0007", "critical", "pending", 0, false))
	a.Tick()
	clk.t = clk.t.Add(5 * time.Second)
	a.Tick() // backoff not over: no second try
	if a.Queue[0].Tries != 1 {
		t.Fatalf("tries %d", a.Queue[0].Tries)
	}
	// restart: a fresh alerter reads the queue file
	b, _ := testAlerter(t, file, s, nil)
	if len(b.Queue) != 1 {
		t.Fatalf("queue not restored: %+v", b.Queue)
	}
	s.setFail(false)
	b.Tick()
	if s.n() != 1 || len(b.Queue) != 0 {
		t.Fatalf("not delivered after restart: sink %d queue %d", s.n(), len(b.Queue))
	}
	b.OnIncident(incJSON("INC-0007", "critical", "pending", 0, false))
	b.Tick()
	if s.n() != 1 {
		t.Fatal("re-sent after delivery")
	}
}

func TestAlertEscalationUnlessAcknowledged(t *testing.T) {
	s, esc := newSink(t), newSink(t)
	a, clk := testAlerter(t, filepath.Join(t.TempDir(), "q.json"), s, esc)
	a.OnIncident(incJSON("INC-0010", "critical", "pending", 0, false))
	a.OnIncident(incJSON("INC-0011", "critical", "pending", 0, false))
	a.Tick()
	clk.t = clk.t.Add(5 * time.Minute)
	a.OnIncident(incJSON("INC-0011", "critical", "pending", clk.t.Unix(), false)) // acknowledged in the app
	clk.t = clk.t.Add(11 * time.Minute)
	a.Tick()
	if esc.n() != 1 || esc.got[0]["incident"] != "INC-0010" || esc.got[0]["escalated"] != true {
		t.Fatalf("escalation: %v", esc.got)
	}
	clk.t = clk.t.Add(time.Hour)
	a.Tick()
	if esc.n() != 3 { // the ladder: 15, 30 and 60 min (hardening); the acknowledged INC-0011 never escalates
		t.Fatalf("ladder: %d escalations, want 3", esc.n())
	}
	for _, g := range esc.got {
		if g["incident"] != "INC-0010" {
			t.Fatalf("escalated %v", g["incident"])
		}
	}
	clk.t = clk.t.Add(5 * time.Hour)
	a.Tick()
	if esc.n() != 3 {
		t.Fatal("ladder repeats")
	}
}

// Flood guard: at most alert_rate_per_hour sends; the rest wait (critical first), none are dropped.
func TestAlertRateLimit(t *testing.T) {
	s := newSink(t)
	a, clk := testAlerter(t, filepath.Join(t.TempDir(), "q.json"), s, nil)
	a.rate = 2
	for i := 0; i < 4; i++ {
		a.OnIncident(incJSON(fmt.Sprintf("INC-%04d", 20+i), "warning", "approved", 0, false))
	}
	a.OnIncident(incJSON("INC-0099", "critical", "pending", 1, false))
	a.Tick()
	if s.n() != 2 || s.got[0]["incident"] != "INC-0099" {
		t.Fatalf("first hour: %v", s.got)
	}
	clk.t = clk.t.Add(61 * time.Minute)
	a.Tick()
	clk.t = clk.t.Add(61 * time.Minute)
	a.Tick()
	if s.n() != 5 || len(a.Queue) != 0 {
		t.Fatalf("after 2 h: sent %d queued %d", s.n(), len(a.Queue))
	}
}

func TestAlertNtfyFormat(t *testing.T) {
	s := newSink(t)
	a := newAlerter(filepath.Join(t.TempDir(), "q.json"), []alertChan{webhookChan("w", s.srv.URL, "ntfy", "Authorization: Bearer tk")}, nil)
	a.link = "http://board:8000"
	a.OnIncident(incJSON("INC-0005", "critical", "pending", 0, false))
	a.Tick()
	if s.n() != 1 {
		t.Fatal("not sent")
	}
	h := s.hdrs[0]
	if h.Get("Priority") != "urgent" || !strings.Contains(h.Get("Title"), "CRITICAL") || h.Get("Authorization") != "Bearer tk" ||
		h.Get("Click") != "http://board:8000/#incident=INC-0005" || !strings.Contains(s.got[0]["text"].(string), "SR-AQ-KH03-03") {
		t.Fatalf("headers %v body %v", h, s.got[0])
	}
}

// SMTP: a minimal local SMTP server receives the e-mail.
func TestAlertSMTP(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	got := make(chan string, 1)
	go func() {
		c, err := ln.Accept()
		if err != nil {
			return
		}
		defer c.Close()
		r := bufio.NewReader(c)
		fmt.Fprint(c, "220 test\r\n")
		var data strings.Builder
		inData := false
		for {
			line, err := r.ReadString('\n')
			if err != nil {
				return
			}
			if inData {
				if line == ".\r\n" {
					inData = false
					fmt.Fprint(c, "250 ok\r\n")
					got <- data.String()
					continue
				}
				data.WriteString(line)
				continue
			}
			switch strings.ToUpper(strings.Fields(line)[0]) {
			case "EHLO", "HELO":
				fmt.Fprint(c, "250 test\r\n")
			case "DATA":
				inData = true
				fmt.Fprint(c, "354 go\r\n")
			case "QUIT":
				fmt.Fprint(c, "221 bye\r\n")
				return
			default:
				fmt.Fprint(c, "250 ok\r\n")
			}
		}
	}()
	a := newAlerter(filepath.Join(t.TempDir(), "q.json"), []alertChan{smtpChan("email", ln.Addr().String(), "", "", "edge@campus", []string{"ops@campus"})}, nil)
	a.OnIncident(incJSON("INC-0042", "critical", "pending", 0, false))
	a.Tick()
	select {
	case m := <-got:
		if !strings.Contains(m, "Subject: CRITICAL: CO2 rising in KH03 (INC-0042)") {
			t.Fatalf("mail %q", m)
		}
	case <-time.After(5 * time.Second):
		t.Fatalf("no mail; stats %v queue %+v", a.Stats(), a.Queue)
	}
}

// night sweep 2026-11-27 #48: a mail server that accepts and then says nothing no longer blocks forever.
func TestSMTPStalledServerHitsDeadline(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			defer c.Close() // never greets
		}
	}()
	old := smtpTimeout
	smtpTimeout = 300 * time.Millisecond
	defer func() { smtpTimeout = old }()
	t0 := time.Now()
	err = smtpSendDeadline(context.Background(), ln.Addr().String(), nil, "a@b", []string{"c@d"}, []byte("x"))
	if err == nil || time.Since(t0) > 3*time.Second {
		t.Fatalf("err %v after %v", err, time.Since(t0))
	}
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	smtpTimeout = time.Minute
	t0 = time.Now()
	if err := smtpSendDeadline(ctx, ln.Addr().String(), nil, "a@b", []string{"c@d"}, []byte("x")); err == nil || time.Since(t0) > 3*time.Second {
		t.Fatalf("ctx: err %v after %v", err, time.Since(t0))
	}
}
