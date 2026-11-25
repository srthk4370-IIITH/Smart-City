package main

// Polish pass, engine side (owner 2026-11-19/20):
//   - reboot blindness: the readings bank and the per-sensor episode flags are saved to state/engine.json every 5 min
//     (tmp + fsync + rename) and restored at start when younger than 2 h, before the campus backfill fills the gap;
//   - every boot is recorded in state/boots.jsonl (time, uptime before, memory, thermal); /api/health shows the
//     7-day restart count;
//   - maintenance snooze: a sensor or room is snoozed for up to 72 h with a mandatory reason; snoozed sensors open no
//     incidents except criticals (those still alert).

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const (
	stateEvery      = 5 * time.Minute
	stateMaxAge     = 2 * time.Hour
	snoozeMaxHours  = 72
	restartAlertDay = 2 // more than this many boots in 24 h raise restart_alert
)

// ---------------------------------------------------------------- state persistence

type engFlag struct {
	Alerted, Reported       bool
	AlertedAt, ClearedAt    int64
	NormalRun, Same         int
	RiseRun, CritRun        int
	ReportedSev             int
	FastAt, EarlyAt         int64
	MaintFrom, MaintUntil   int64
	MaintWhy                string
	ReplacedAt              int64
	SnoozeFrom, SnoozeUntil int64
	SnoozeWhy, SnoozeBy     string
}

type engSnap struct {
	Version int                          `json:"version"`
	SavedAt int64                        `json:"saved_at"` // device time (nowTime), unix
	Sim     int64                        `json:"sim"`
	Series  map[string]map[int64]float64 `json:"series"`
	Cnt     map[string]map[int64]int     `json:"cnt"`
	Flags   map[string]engFlag           `json:"flags"`
}

func enginePath(dir string) string { return filepath.Join(dir, "state", "engine.json") }

// SaveState writes the bank and the episode flags atomically. A no-op unless the engine runs on live feeds.
func (e *Engine) SaveState(dir string) error {
	e.mu.RLock()
	if !e.Live {
		e.mu.RUnlock()
		return nil
	}
	snap := engSnap{Version: 1, SavedAt: nowTime().Unix(), Sim: e.sim,
		Series: make(map[string]map[int64]float64, len(e.series)), Cnt: map[string]map[int64]int{}, Flags: map[string]engFlag{}}
	for k, m := range e.series {
		cp := make(map[int64]float64, len(m))
		for b, v := range m {
			cp[b] = v
		}
		snap.Series[k] = cp
	}
	for k, st := range e.states {
		f := engFlag{Alerted: st.alerted, Reported: st.Reported, AlertedAt: st.alertedAt, ClearedAt: st.clearedAt,
			NormalRun: st.normalRun, Same: st.same, RiseRun: st.riseRun, CritRun: st.critRun, ReportedSev: st.reportedSev,
			FastAt: st.fastAt, EarlyAt: st.earlyAt}
		if fs := e.dq[k]; fs != nil {
			f.MaintFrom, f.MaintUntil, f.MaintWhy, f.ReplacedAt = fs.maintFrom, fs.maintUntil, fs.maintWhy, fs.replacedAt
			f.SnoozeFrom, f.SnoozeUntil, f.SnoozeWhy, f.SnoozeBy = fs.snoozeFrom, fs.snoozeUntil, fs.snoozeWhy, fs.snoozeBy
			if len(fs.cnt) > 0 {
				cp := make(map[int64]int, len(fs.cnt))
				for b, n := range fs.cnt {
					cp[b] = n
				}
				snap.Cnt[k] = cp
			}
		}
		snap.Flags[k] = f
	}
	e.mu.RUnlock()
	b, err := json.Marshal(snap)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(enginePath(dir)), 0o755); err != nil {
		return err
	}
	tmp := enginePath(dir) + ".tmp"
	f, err := os.OpenFile(tmp, os.O_CREATE|os.O_TRUNC|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	_, werr := f.Write(b)
	serr := f.Sync()
	f.Close()
	if werr != nil || serr != nil {
		os.Remove(tmp)
		return fmt.Errorf("engine state write: %v %v", werr, serr)
	}
	if err := os.Rename(tmp, enginePath(dir)); err != nil {
		os.Remove(tmp)
		return err
	}
	return nil
}

// RestoreState loads state/engine.json when it is younger than 2 h. Existing readings are never overwritten, so the
// campus backfill that follows only fills what is missing. Returns a one-line summary of what happened.
func (e *Engine) RestoreState(dir string, now time.Time) (string, error) {
	b, err := os.ReadFile(enginePath(dir))
	if err != nil {
		return "no saved engine state", nil
	}
	var snap engSnap
	if err := json.Unmarshal(b, &snap); err != nil || snap.Version != 1 {
		return "saved engine state unreadable, ignored", nil
	}
	age := now.Unix() - snap.SavedAt
	if age < 0 || age > int64(stateMaxAge.Seconds()) {
		return fmt.Sprintf("saved engine state is %d min old (limit %d): not restored", age/60, int(stateMaxAge.Minutes())), nil
	}
	nowB := now.Unix() / bucketSec * bucketSec
	e.mu.Lock()
	defer e.mu.Unlock()
	readings, flags := 0, 0
	for k, m := range snap.Series {
		if e.bank[k] == nil {
			continue
		}
		if e.series[k] == nil {
			e.series[k] = map[int64]float64{}
		}
		for bk, v := range m {
			if _, have := e.series[k][bk]; !have && bk <= nowB {
				e.series[k][bk] = v
				readings++
			}
		}
	}
	for k, m := range snap.Cnt {
		if e.bank[k] == nil {
			continue
		}
		fs := e.feedOf(k)
		for bk, n := range m {
			if _, have := fs.cnt[bk]; !have {
				fs.cnt[bk] = n
			}
		}
	}
	for k, f := range snap.Flags {
		st := e.states[k]
		if st == nil {
			continue
		}
		st.alerted, st.Reported, st.alertedAt, st.clearedAt = f.Alerted, f.Reported, f.AlertedAt, f.ClearedAt
		st.normalRun, st.same, st.riseRun, st.critRun, st.reportedSev = f.NormalRun, f.Same, f.RiseRun, f.CritRun, f.ReportedSev
		st.fastAt, st.earlyAt = f.FastAt, f.EarlyAt
		st.abTimes = nil
		for i := 0; i < f.Same && i < 24; i++ { // the restored run counts as consecutive readings inside the gate window
			st.abTimes = append(st.abTimes, snap.Sim-int64(i)*bucketSec)
		}
		fs := e.feedOf(k)
		fs.maintFrom, fs.maintUntil, fs.maintWhy, fs.replacedAt = f.MaintFrom, f.MaintUntil, f.MaintWhy, f.ReplacedAt
		fs.snoozeFrom, fs.snoozeUntil, fs.snoozeWhy, fs.snoozeBy = f.SnoozeFrom, f.SnoozeUntil, f.SnoozeWhy, f.SnoozeBy
		flags++
	}
	return fmt.Sprintf("restored %d readings and %d sensor flags from %d min ago", readings, flags, age/60), nil
}

// StartStateSaver saves the engine state every 5 min (and the alive marker the next boot reads its uptime from).
func (e *Engine) StartStateSaver(dir string) {
	go func() {
		defer recoverLog("state saver")
		for {
			time.Sleep(stateEvery)
			if err := e.SaveState(dir); err != nil {
				trace("engine state save failed: %v", err)
			}
			writeAlive(dir)
		}
	}()
}

func alivePath(dir string) string { return filepath.Join(dir, "state", "alive.json") }

func writeAlive(dir string) {
	b, _ := json.Marshal(map[string]int64{"ts": nowTime().Unix()})
	atomicWrite(alivePath(dir), b, 0o644)
}

// ---------------------------------------------------------------- boot record

type bootRec struct {
	TS          int64          `json:"ts"`
	WallIST     string         `json:"wall_ist"`
	ClockValid  bool           `json:"clock_valid"`
	PrevUptimeS int64          `json:"prev_uptime_s,omitempty"` // lower bound: from the previous boot to the last alive marker
	MemMB       any            `json:"mem_available_mb,omitempty"`
	Device      map[string]any `json:"device,omitempty"`
	Htpd        string         `json:"htpd,omitempty"`
}

func bootsPath(dir string) string { return filepath.Join(dir, "state", "boots.jsonl") }

func readBoots(dir string) []bootRec {
	f, err := os.Open(bootsPath(dir))
	if err != nil {
		return nil
	}
	defer f.Close()
	var out []bootRec
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 64<<10), 1<<20)
	for sc.Scan() {
		var b bootRec
		if json.Unmarshal(sc.Bytes(), &b) == nil && b.TS != 0 {
			out = append(out, b)
		}
	}
	return out
}

// recordBoot appends this boot to state/boots.jsonl and returns the record.
func recordBoot(dir string) bootRec {
	now := nowTime()
	rec := bootRec{TS: now.Unix(), WallIST: now.In(IST).Format("2006-01-02 15:04:05"), ClockValid: clockValid()}
	if prev := readBoots(dir); len(prev) > 0 {
		if b, err := os.ReadFile(alivePath(dir)); err == nil {
			var a struct {
				TS int64 `json:"ts"`
			}
			if json.Unmarshal(b, &a) == nil && a.TS > prev[len(prev)-1].TS {
				rec.PrevUptimeS = a.TS - prev[len(prev)-1].TS
			}
		}
	}
	d := deviceStats()
	rec.Device, rec.MemMB = d, d["mem_available_mb"]
	if htpdEnabled() {
		rec.Htpd = "down"
		if htpdUp() {
			rec.Htpd = "up"
		}
	}
	if b, err := json.Marshal(rec); err == nil {
		os.MkdirAll(filepath.Dir(bootsPath(dir)), 0o755)
		if f, err := os.OpenFile(bootsPath(dir), os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644); err == nil {
			f.Write(append(b, '\n'))
			f.Sync()
			f.Close()
		}
	}
	writeAlive(dir)
	return rec
}

// restartCounts: boots in the last 7 days and the last 24 h.
func restartCounts(dir string, now time.Time) (week, day int) {
	for _, b := range readBoots(dir) {
		age := now.Unix() - b.TS
		if age >= 0 && age <= 7*86400 {
			week++
		}
		if age >= 0 && age <= 86400 {
			day++
		}
	}
	return
}

// ---------------------------------------------------------------- maintenance snooze

// snoozedAt: this feed is snoozed at sensor time sim.
func (fs *feedState) snoozedAt(sim int64) bool {
	return fs != nil && fs.snoozeUntil > sim && sim >= fs.snoozeFrom
}

// SetSnooze snoozes a sensor (node + metric, metric "" = the node's sensors) or a room (every sensor whose location
// is room) for hours (0 ends it). A reason is mandatory; the maximum is 72 h. Returns the sensor keys and the end.
func (e *Engine) SetSnooze(node, metric, room string, hours float64, reason, operator string) ([]string, int64, error) {
	reason = strings.TrimSpace(reason)
	switch {
	case (node == "") == (room == ""):
		return nil, 0, fmt.Errorf("give either node (+ optional metric) or room")
	case hours < 0 || hours > snoozeMaxHours:
		return nil, 0, fmt.Errorf("hours must be 0..%d", snoozeMaxHours)
	case hours > 0 && len(reason) < 3:
		return nil, 0, fmt.Errorf("a reason is required to snooze")
	case len(reason) > 200:
		return nil, 0, fmt.Errorf("reason too long (max 200 characters)")
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	var ks []string
	for _, k := range e.bankOrder {
		sn := e.bank[k]
		if (node != "" && sn.Node == node && (metric == "" || sn.Metric == metric)) || (room != "" && strings.EqualFold(sn.Location, room)) {
			ks = append(ks, k)
		}
	}
	if len(ks) == 0 {
		return nil, 0, fmt.Errorf("unknown sensor or room")
	}
	until := int64(0)
	for _, k := range ks {
		fs := e.feedOf(k)
		if hours > 0 {
			until = e.sim + int64(hours*3600)
			fs.snoozeFrom, fs.snoozeUntil, fs.snoozeWhy, fs.snoozeBy = e.sim, until, reason, operator
		} else {
			fs.snoozeFrom, fs.snoozeUntil, fs.snoozeWhy, fs.snoozeBy = 0, 0, "", ""
		}
	}
	return ks, until, nil
}

// SnoozeReason: why the sensor is snoozed right now ("" = not snoozed).
func (e *Engine) SnoozeReason(node, metric string) string {
	e.mu.RLock()
	defer e.mu.RUnlock()
	if fs := e.dq[key(node, metric)]; fs.snoozedAt(e.sim) {
		return fs.snoozeWhy
	}
	return ""
}

type snoozeRow struct {
	Node   string `json:"node"`
	Metric string `json:"metric"`
	Room   string `json:"room"`
	Until  int64  `json:"until"`
	Reason string `json:"reason"`
	By     string `json:"operator,omitempty"`
}

// Snoozes lists the active snoozes.
func (e *Engine) Snoozes() []snoozeRow {
	e.mu.RLock()
	defer e.mu.RUnlock()
	out := []snoozeRow{}
	for _, k := range e.bankOrder {
		if fs := e.dq[k]; fs.snoozedAt(e.sim) {
			sn := e.bank[k]
			out = append(out, snoozeRow{sn.Node, sn.Metric, sn.Location, fs.snoozeUntil, fs.snoozeWhy, fs.snoozeBy})
		}
	}
	return out
}

// ---------------------------------------------------------------- routes

type healthResp struct {
	HealthOut
	EventMode    EventModeOut `json:"event_mode"`
	Restarts7d   int          `json:"restarts_7d"`
	Restarts24h  int          `json:"restarts_24h"`
	RestartAlert bool         `json:"restart_alert"`
	// production hardening (hardening.go): the UI shows a banner for each
	DemoActive       bool     `json:"demo_active"`         // demo endpoints are on (htpd_profile demo=1): yellow "demo" banner
	NoAlertChannel   bool     `json:"no_alert_channel"`    // nothing can reach a person (no ntfy / email configured): red banner
	Disk             DiskInfo `json:"disk"`                // state partition; disk.alert when more than 85 % is used
	HtpdRulesOnly    bool     `json:"htpd_rules_only"`     // htpd crash-looped: AI paused, rules only
	HtpdRulesOnlyMin int      `json:"htpd_rules_only_min"` // minutes until htpd is started again
	StoreWriteErrors int64    `json:"store_write_errors"`  // failed incident writes since start (disk full?)
	Panics           int      `json:"panics_recovered"`
	Supabase         any      `json:"supabase"` // fog sync state (supabase_sync.go)
}

func (s *Server) healthResponse(hv HealthOut) healthResp {
	w, d := restartCounts(s.dir, nowTime())
	ro, mins := htpdLoop.status()
	return healthResp{hv, s.rsn.EventModeStatus(), w, d, d > restartAlertDay,
		demoActive(), !alertChannelConfigured(), diskInfo(s.dir), ro, mins, storeWriteErrors.Load(), panics(), supaStats()}
}

func (s *Server) polishRoutes(mux *http.ServeMux) {
	// Snooze: GET lists; POST {"node","metric"(optional) | "room","hours"(0 ends),"reason","operator"}.
	mux.HandleFunc("/api/snooze", func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet {
			list := s.eng.Snoozes()
			sort.Slice(list, func(i, j int) bool { return list[i].Node+list[i].Metric < list[j].Node+list[j].Metric })
			writeJSON(w, map[string]any{"snoozes": list})
			return
		}
		var body struct {
			Node     string  `json:"node"`
			Metric   string  `json:"metric"`
			Room     string  `json:"room"`
			Hours    float64 `json:"hours"`
			Reason   string  `json:"reason"`
			Operator string  `json:"operator"`
		}
		if r.Method != http.MethodPost || readBody(r, &body) != nil || len(body.Operator) > 80 {
			http.Error(w, `POST {"node":"SR-AQ-KH03-03","metric":"co2","hours":4,"reason":"AC repair"} or {"room":"...","hours":0}`, 400)
			return
		}
		op := strings.Join(strings.Fields(body.Operator), " ")
		ks, until, err := s.eng.SetSnooze(body.Node, body.Metric, body.Room, body.Hours, body.Reason, op)
		if err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		kind := "unsnoozed"
		if body.Hours > 0 {
			kind = "snoozed"
		}
		s.rsn.LogMaintenance(MaintRow{Node: body.Node, Metric: body.Metric, Kind: kind, Minutes: int(body.Hours * 60), Reason: strings.TrimSpace(body.Reason), Operator: op})
		out := map[string]any{"ok": true, "sensors": ks}
		if until > 0 {
			out["until"], out["until_ist"] = until, time.Unix(until, 0).In(IST).Format("Mon 02 Jan 15:04")
		}
		writeJSON(w, out)
	})
}
