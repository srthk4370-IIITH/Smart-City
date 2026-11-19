package main

import (
	"encoding/binary"
	"net"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// rtcReset: the board's RTC came up three years behind (2023), time_sync on, no offset; restored after the test.
func rtcReset(t *testing.T, on bool) {
	t.Helper()
	if on {
		t.Setenv("SCE_TIME_SYNC", "1")
	}
	old := devClock
	devClock = func() time.Time { return time.Now().AddDate(-3, 0, 0) }
	reset := func() {
		syncOffset.Store(0)
		clockSync.Lock()
		clockSync.started, clockSync.source, clockSync.mqttObs, clockSync.pending, clockSync.onSynced, clockSync.ntpTry = false, "", nil, nil, nil, nil
		clockSync.Unlock()
	}
	reset()
	t.Cleanup(func() { devClock = old; reset() })
}

func fakeNTP(t *testing.T) string {
	pc, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { pc.Close() })
	go func() {
		buf := make([]byte, 48)
		for {
			_, addr, err := pc.ReadFrom(buf)
			if err != nil {
				return
			}
			resp := make([]byte, 48)
			resp[0], resp[1] = 0x24, 1 // version 4, server; stratum 1
			now := time.Now()
			binary.BigEndian.PutUint32(resp[40:], uint32(now.Unix()+2208988800))
			binary.BigEndian.PutUint32(resp[44:], uint32(uint64(now.Nanosecond())<<32/1e9))
			pc.WriteTo(resp, addr)
		}
	}()
	return pc.LocalAddr().String()
}

func near(a, b time.Time, d time.Duration) bool { x := a.Sub(b); return x < d && x > -d }

// Off by default: an invalid clock still stamps incidents exactly as before.
func TestTimeSyncOffByDefault(t *testing.T) {
	rtcReset(t, false)
	if clockValid() {
		t.Fatal("a 2023 clock counted as valid")
	}
	if w := incidentWall(); w == "" || !strings.HasPrefix(w, devClock().In(IST).Format("2006")) {
		t.Fatalf("stamp %q", w)
	}
}

func TestTimeSyncNTP(t *testing.T) {
	rtcReset(t, true)
	t.Setenv("SCE_NTP_SERVERS", "127.0.0.1:1,"+fakeNTP(t)) // first server dead, second answers
	startTimeSync(t.TempDir())
	waitFor(t, "NTP sync", 10*time.Second, clockValid)
	if !near(nowTime(), time.Now(), 2*time.Second) {
		t.Fatalf("nowTime %v, real %v", nowTime(), time.Now())
	}
	if s := clockStatus()["source"].(string); !strings.HasPrefix(s, "ntp:127.0.0.1:") {
		t.Fatalf("source %q", s)
	}
}

// While the clock is invalid incidents get no wall stamp; the laptop's push sets the clock once and re-stamps them.
func TestTimeSyncUnstampedThenRestampedByAPI(t *testing.T) {
	rtcReset(t, true)
	r := &Reasoner{store: filepath.Join(t.TempDir(), "incidents.jsonl"), refineQ: map[string]bool{}}
	clockSync.onSynced = r.restampClock
	if w := incidentWall(); w != "" {
		t.Fatalf("stamped %q with an invalid clock", w)
	}
	inc := &Incident{ID: "INC-0001", CreatedWall: incidentWall()}
	r.incidents = append(r.incidents, inc)
	clockPendingAdd(inc)
	created := time.Now()
	if !inc.ClockUnsure {
		t.Fatal("not flagged")
	}
	time.Sleep(50 * time.Millisecond)
	body := `{"unix":` + strconv.FormatInt(time.Now().Unix(), 10) + `}`
	w := httptest.NewRecorder()
	handleTimePush(w, httptest.NewRequest(http.MethodPost, "/api/prod/time", strings.NewReader(body)))
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"applied":true`) {
		t.Fatalf("push: %d %s", w.Code, w.Body.String())
	}
	if inc.ClockUnsure || inc.CreatedWall == "" {
		t.Fatalf("not re-stamped: %+v", inc)
	}
	got, _ := time.ParseInLocation("2006-01-02 15:04:05", inc.CreatedWall, IST)
	if !near(got, created, 3*time.Second) {
		t.Fatalf("re-stamped %s, created %s", got, created)
	}
	// a second source never moves a clock that is already set
	w = httptest.NewRecorder()
	handleTimePush(w, httptest.NewRequest(http.MethodPost, "/api/prod/time", strings.NewReader(`{"unix":2000000000}`)))
	if !strings.Contains(w.Body.String(), `"applied":false`) {
		t.Fatalf("second push applied: %s", w.Body.String())
	}
	// garbage is refused
	w = httptest.NewRecorder()
	handleTimePush(w, httptest.NewRequest(http.MethodPost, "/api/prod/time", strings.NewReader(`{"unix":12}`)))
	if w.Code != 400 {
		t.Fatalf("bad time accepted: %d", w.Code)
	}
}

// MQTT device timestamps set the clock only after three agree (one bad gateway clock is not enough).
func TestTimeSyncFromMQTTTimestamps(t *testing.T) {
	rtcReset(t, true)
	now := time.Now().Unix()
	timeSyncObserve(now, "mqtt")
	timeSyncObserve(now+86400*30, "mqtt") // one gateway with a wrong clock
	timeSyncObserve(now, "mqtt")
	if clockValid() {
		t.Fatal("set from disagreeing timestamps")
	}
	timeSyncObserve(now+1, "mqtt")
	timeSyncObserve(now+2, "mqtt")
	timeSyncObserve(now+3, "mqtt")
	if !clockValid() || !near(nowTime(), time.Now(), 5*time.Second) {
		t.Fatalf("valid=%v nowTime=%v", clockValid(), nowTime())
	}
}
