package main

// Time sync (ROADMAP 2026-11-09 §4 "Time sync"). OFF unless htpd_profile time_sync=1.
//
// The QIDK's RTC comes up in 2023 after a power loss (sensors.go needClockFix). Android fixes it by NTP once Wi-Fi
// has internet, and the app restores a saved offset (--clock-unix); a long power-off on a LAN without internet
// leaves neither, and every window and incident would be stamped years in the past. With time_sync=1:
//
//   - at start the clock counts as invalid while the device says < 2025 and no offset was applied;
//   - NTP (ntp_servers=pool.ntp.org,time.google.com; a LAN server such as the gateway is best) is tried every 60 s;
//   - otherwise the first trusted source wins: POST /api/prod/time {"unix":<seconds>} from the laptop (loopback or
//     X-API-Token, as every write), or MQTT payload timestamps (time_trust_mqtt=1, default when time_sync is on):
//     3 readings whose implied offsets agree within 2 min;
//   - while invalid, incidents get no wall stamp ("created_wall" empty, "clock_uncertain": true; the log says why).
//     When the clock is fixed they are re-stamped from the monotonic time they were created at.

import (
	"context"
	"encoding/binary"
	"errors"
	"log"
	"net"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

func timeSyncEnabled() bool { return profOn("time_sync") }

// syncOffset: the correction time sync found (ns), 0 = none. nowTime applies it.
var syncOffset atomic.Int64

var clockSync struct {
	sync.Mutex
	started  bool
	source   string    // ntp:<server> | api | mqtt
	syncedAt time.Time // monotonic
	mqttObs  []int64   // offsets (s) implied by recent MQTT timestamps
	pending  []clockPending
	onSynced func([]clockPending) // re-stamps incidents (set by startTimeSync's caller)
	ntpTry   func(ctx context.Context, server string) (time.Duration, error)
}

type clockPending struct {
	inc *Incident
	at  time.Time // devClock() at creation (monotonic reading kept)
}

// timeSyncOffset: the time-sync correction, dropped once the OS clock itself was fixed (NTP by Android).
func timeSyncOffset() time.Duration {
	d := time.Duration(syncOffset.Load())
	if d != 0 && (d > 24*time.Hour || d < -24*time.Hour) && !needClockFix() {
		return 0
	}
	return d
}

// clockValid: the wall clock can be trusted (device clock already after 2024, an offset was applied at start, or
// time sync fixed it).
func clockValid() bool {
	return !needClockFix() || clockOffset != 0 || syncOffset.Load() != 0
}

func clockStatus() map[string]any {
	clockSync.Lock()
	defer clockSync.Unlock()
	out := map[string]any{"valid": clockValid(), "device": devClock().UTC().Format(time.RFC3339),
		"corrected": nowTime().UTC().Format(time.RFC3339), "source": clockSync.source, "uncertain_incidents": len(clockSync.pending)}
	if clockOffset != 0 && clockSync.source == "" {
		out["source"] = "start offset (--clock-unix)"
	}
	if n := clockNetStatus(); n != nil {
		out["source"], out["net_age_s"], out["net_offset_s"], out["valid"] = n["source"], n["age_s"], n["offset_s"], true
	}
	return out
}

// incidentWall: an incident's wall stamp, or "" while time sync is on and the clock is invalid.
func incidentWall() string {
	if timeSyncEnabled() && !clockValid() {
		return ""
	}
	return nowTime().In(IST).Format("2006-01-02 15:04:05")
}

// clockPendingAdd remembers an incident created with an invalid clock (caller holds r.mu).
func clockPendingAdd(inc *Incident) {
	inc.ClockUnsure = true
	clockSync.Lock()
	clockSync.pending = append(clockSync.pending, clockPending{inc: inc, at: devClock()})
	if len(clockSync.pending) > 1000 {
		clockSync.pending = clockSync.pending[len(clockSync.pending)-1000:]
	}
	clockSync.Unlock()
	log.Printf("time: incident created while the clock is invalid (device %s): no wall stamp until the clock is synced",
		devClock().UTC().Format(time.RFC3339))
}

// setClock applies a trusted time once; later sources are ignored.
func setClock(trusted time.Time, measuredAt time.Time, source string) bool {
	clockSync.Lock()
	if clockValid() || trusted.Year() < 2025 {
		clockSync.Unlock()
		return false
	}
	off := trusted.Sub(measuredAt)
	if off == 0 {
		off = time.Nanosecond
	}
	syncOffset.Store(int64(off))
	clockSync.source, clockSync.syncedAt = source, devClock()
	pend := clockSync.pending
	clockSync.pending = nil
	cb := clockSync.onSynced
	clockSync.Unlock()
	log.Printf("time: clock set from %s, correction %s", source, off.Round(time.Second))
	if cb != nil && len(pend) > 0 {
		cb(pend)
	}
	return true
}

// timeSyncObserve: a device timestamp from a trusted feed (MQTT). Three that agree within 2 min set the clock.
func timeSyncObserve(ts int64, source string) {
	if !timeSyncEnabled() || clockValid() || ts < 1735689600 { // 2025-01-01
		return
	}
	now := devClock()
	off := ts - now.Unix()
	clockSync.Lock()
	o := append(clockSync.mqttObs, off)
	if len(o) > 3 {
		o = o[len(o)-3:]
	}
	clockSync.mqttObs = o
	clockSync.Unlock()
	if len(o) < 3 {
		return
	}
	lo, hi := o[0], o[0]
	for _, x := range o {
		if x < lo {
			lo = x
		}
		if x > hi {
			hi = x
		}
	}
	if hi-lo <= 120 {
		setClock(time.Unix(ts, 0), now, source)
	}
}

func handleTimePush(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodGet {
		writeJSON(w, clockStatus())
		return
	}
	var body struct {
		Unix float64 `json:"unix"`
	}
	if r.Method != http.MethodPost || readBody(r, &body) != nil || body.Unix < 1735689600 {
		http.Error(w, `POST {"unix": <seconds since 1970, after 2025-01-01>}`, http.StatusBadRequest)
		return
	}
	sec := int64(body.Unix)
	applied := setClock(time.Unix(sec, int64((body.Unix-float64(sec))*1e9)), devClock(), "api")
	out := clockStatus()
	out["applied"] = applied
	writeJSON(w, out)
}

// sntpQuery asks one NTP server (SNTP v4, UDP 123) and returns the clock correction (server - local).
func sntpQuery(ctx context.Context, server string) (time.Duration, error) {
	if !strings.Contains(server, ":") {
		server += ":123"
	}
	d := net.Dialer{}
	c, err := d.DialContext(ctx, "udp", server)
	if err != nil {
		return 0, err
	}
	defer c.Close()
	dl, ok := ctx.Deadline()
	if !ok {
		dl = time.Now().Add(3 * time.Second)
	}
	c.SetDeadline(dl)
	req := make([]byte, 48)
	req[0] = 0x23 // LI 0, version 4, client
	t0 := devClock()
	if _, err := c.Write(req); err != nil {
		return 0, err
	}
	resp := make([]byte, 48)
	n, err := c.Read(resp)
	if err != nil {
		return 0, err
	}
	rtt := devClock().Sub(t0)
	if n < 48 || resp[0]&7 != 4 || resp[1] == 0 { // mode server, stratum > 0
		return 0, errors.New("bad NTP reply")
	}
	sec := binary.BigEndian.Uint32(resp[40:44])
	frac := binary.BigEndian.Uint32(resp[44:48])
	srv := time.Unix(int64(sec)-2208988800, int64(uint64(frac)*1e9>>32))
	return srv.Add(rtt / 2).Sub(devClock()), nil
}

// startTimeSync: log the clock state and, while it is invalid, try NTP every 60 s.
func startTimeSync(dir string) {
	clockSync.Lock()
	if clockSync.started {
		clockSync.Unlock()
		return
	}
	clockSync.started = true
	if clockSync.ntpTry == nil {
		clockSync.ntpTry = sntpQuery
	}
	try := clockSync.ntpTry
	clockSync.Unlock()
	if clockValid() {
		log.Printf("time: clock valid at start (%s)", nowTime().UTC().Format(time.RFC3339))
		return
	}
	log.Printf("time: device clock invalid at start (%s, RTC reset?): incidents stay unstamped until NTP, the laptop "+
		"(POST /api/prod/time) or MQTT timestamps give the time", devClock().UTC().Format(time.RFC3339))
	servers := profList("ntp_servers")
	if len(servers) == 0 {
		servers = []string{"pool.ntp.org", "time.google.com"}
	}
	go func() {
		defer recoverLog("time sync")
		for !clockValid() {
			for _, s := range servers {
				ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
				t0 := devClock()
				off, err := try(ctx, s)
				cancel()
				if err == nil && setClock(t0.Add(off), t0, "ntp:"+s) {
					return
				}
			}
			time.Sleep(time.Minute)
		}
	}()
}

// restampClock gives incidents created with an invalid clock their wall stamp (offset now known).
func (r *Reasoner) restampClock(pend []clockPending) {
	r.mu.Lock()
	var done []*Incident
	for _, p := range pend {
		if p.inc.CreatedWall == "" {
			p.inc.CreatedWall = p.at.Add(timeSyncOffset()).In(IST).Format("2006-01-02 15:04:05")
		}
		p.inc.ClockUnsure = false
		done = append(done, p.inc)
	}
	r.mu.Unlock()
	for _, inc := range done {
		if inc.ID != "" {
			r.persist(inc)
		}
	}
	log.Printf("time: %d incident(s) re-stamped after the clock sync", len(done))
}
