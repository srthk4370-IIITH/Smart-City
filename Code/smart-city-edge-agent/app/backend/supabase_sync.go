package main

// Fog sync (owner 2026-11-20): REPORTS ONLY go to Supabase (incident reports, operator decisions, board health).
// Raw readings, windows, evidence and prompts NEVER leave the board. Off unless htpd_profile supabase_url +
// supabase_key (or SCE_SUPABASE_URL / SCE_SUPABASE_KEY) are set. Rows are appended to a bounded on-disk queue
// and sent in the background with backoff; the engine never waits on the network.

import (
	"bytes"
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	sbMaxRows  = 5000
	sbMaxBytes = 20 << 20
)

type sbRow struct {
	T string         `json:"t"` // table
	D map[string]any `json:"d"`
}

type sbSeen struct {
	Rev  int    `json:"rev"`
	Hash string `json:"hash"`
	Seq  int    `json:"seq"`
}

type supaSync struct {
	url, key, board, site string
	relay                 string    // owner 2026-11-20: Wi-Fi internet first, then the laptop relay, else queue
	directDown            time.Time // direct path failed at the network level: skip it until then
	dir                   string
	client                *http.Client
	mu                    sync.Mutex
	rows                  []sbRow
	seen                  map[string]sbSeen
	lastOK                time.Time
	lastErr               string
	boardSent             bool
	wake                  chan struct{}
	s                     *Server
}

func newSupaSync(dir string) *supaSync {
	u, k := profStr("supabase_url"), profStr("supabase_key")
	if u == "" || k == "" {
		return nil
	}
	b := profStr("board_id")
	if b == "" {
		b, _ = os.Hostname()
	}
	x := &supaSync{url: strings.TrimRight(u, "/"), key: k, board: b, site: profStr("site_id"), dir: dir,
		client: &http.Client{Timeout: 15 * time.Second}, seen: map[string]sbSeen{}, wake: make(chan struct{}, 1)}
	x.relay = strings.TrimRight(profStr("supabase_relay"), "/")
	x.load()
	return x
}

// bases: the direct project URL (Wi-Fi internet) first, then the laptop relay; a direct path that just failed
// at the network level is skipped for 5 min so a board without internet does not wait 15 s per row.
func (x *supaSync) bases(now time.Time) []string {
	var out []string
	if x.relay == "" || now.After(x.directDown) {
		out = append(out, x.url)
	}
	if x.relay != "" && x.relay != x.url {
		out = append(out, x.relay)
	}
	if len(out) == 0 {
		out = append(out, x.url)
	}
	return out
}

func (x *supaSync) qpath() string    { return filepath.Join(x.dir, "supabase_queue.jsonl") }
func (x *supaSync) seenPath() string { return filepath.Join(x.dir, "supabase_seen.json") }

func (x *supaSync) load() {
	if b, err := os.ReadFile(x.qpath()); err == nil {
		for _, ln := range strings.Split(string(b), "\n") {
			var r sbRow
			if json.Unmarshal([]byte(ln), &r) == nil && r.T != "" {
				x.rows = append(x.rows, r)
			}
		}
	}
	if b, err := os.ReadFile(x.seenPath()); err == nil {
		json.Unmarshal(b, &x.seen)
	}
}

// saveLocked rewrites the queue (small: capped) via tmp+rename.
func (x *supaSync) saveLocked() {
	var buf bytes.Buffer
	for _, r := range x.rows {
		b, _ := json.Marshal(r)
		buf.Write(b)
		buf.WriteByte('\n')
	}
	tmp := x.qpath() + ".part"
	if os.WriteFile(tmp, buf.Bytes(), 0o600) == nil {
		os.Rename(tmp, x.qpath())
	}
	if b, err := json.Marshal(x.seen); err == nil {
		if os.WriteFile(x.seenPath()+".part", b, 0o600) == nil {
			os.Rename(x.seenPath()+".part", x.seenPath())
		}
	}
}

// enqueueLocked adds rows and enforces the cap: oldest health rows go first, then the oldest rows.
func (x *supaSync) enqueueLocked(rs ...sbRow) {
	x.rows = append(x.rows, rs...)
	size := func() int {
		n := 0
		for _, r := range x.rows {
			b, _ := json.Marshal(r)
			n += len(b) + 1
		}
		return n
	}
	for len(x.rows) > sbMaxRows || (len(x.rows) > 1 && size() > sbMaxBytes) {
		drop := -1
		for i, r := range x.rows {
			if r.T == "board_health" {
				drop = i
				break
			}
		}
		if drop < 0 {
			drop = 0
		}
		x.rows = append(x.rows[:drop], x.rows[drop+1:]...)
	}
	x.saveLocked()
	select {
	case x.wake <- struct{}{}:
	default:
	}
}

func rowTime(unix int64) any {
	if unix <= 0 {
		return nil
	}
	return time.Unix(unix, 0).UTC().Format(time.RFC3339)
}

// OnIncident is the persist hook: a changed report is a new revision; every new workflow event is a decision.
func (x *supaSync) OnIncident(line []byte) {
	var inc Incident
	if json.Unmarshal(line, &inc) != nil || inc.ID == "" || inc.SystemCheck || inc.Watermark != "" {
		return
	}
	loc := ""
	if len(inc.Sensors) > 0 {
		loc = inc.Sensors[0].Location
	}
	rep := map[string]any{}
	var label, root string
	var domains []string
	if inc.Final != nil && inc.Final.Parsed != nil { // text fields only: no Evidence / Observations / Raw / Prompt
		p := inc.Final.Parsed
		label, root, domains = p.Label, p.RootCause, p.AffectedDomains
		rep = map[string]any{"action": p.Action, "explanation": p.Explanation, "confidence": p.Confidence,
			"causal_chain": p.CausalChain, "monitor_next": p.MonitorNext, "requires_human": p.RequiresHuman,
			"stage": inc.RefineStage, "approval": inc.Approval, "approval_note": inc.ApprovalNote,
			"outcome": inc.Outcome, "outcome_note": inc.OutcomeNote, "closed_by": inc.ClosedBy, "owner": inc.Owner}
	}
	if domains == nil {
		domains = inc.Roles
	}
	if domains == nil {
		domains = []string{}
	}
	steps := []map[string]any{}
	for _, st := range inc.Steps {
		steps = append(steps, map[string]any{"id": st.ID, "action": st.Action, "target": st.Target, "text": st.Text, "state": st.State})
	}
	state := wfOf(&inc)
	h := sha1.New()
	for _, v := range []any{inc.Severity, inc.Title, domains, loc, label, root, steps, rep, state} {
		b, _ := json.Marshal(v)
		h.Write(b)
	}
	hash := hex.EncodeToString(h.Sum(nil))

	x.mu.Lock()
	defer x.mu.Unlock()
	sn, known := x.seen[inc.ID]
	var rows []sbRow
	if !known || sn.Hash != hash {
		rev := 0
		if known {
			rev = sn.Rev + 1
		}
		var created any
		if t, err := time.Parse(time.RFC3339, inc.CreatedWall); err == nil {
			created = t.UTC().Format(time.RFC3339)
		}
		rows = append(rows, sbRow{"incident_reports", map[string]any{"board_id": x.board, "incident_id": inc.ID, "revision": rev,
			"created_at": created, "severity": inc.Severity, "title": inc.Title, "domains": domains, "location": loc,
			"label": label, "root_cause": root, "checklist": steps, "report": rep, "state": state}})
		sn.Rev, sn.Hash = rev, hash
	}
	for _, ev := range inc.Events {
		if ev.Seq <= sn.Seq {
			continue
		}
		rows = append(rows, sbRow{"decisions", map[string]any{"board_id": x.board, "incident_id": inc.ID,
			"at": rowTime(ev.At), "actor": ev.Actor, "action": ev.Event, "outcome": ev.Outcome, "note": ev.Note}})
		sn.Seq = ev.Seq
	}
	x.seen[inc.ID] = sn
	if len(rows) > 0 {
		x.enqueueLocked(rows...)
	} else {
		x.saveLocked()
	}
}

func cpuTempC() any {
	b, err := os.ReadFile("/sys/class/thermal/thermal_zone0/temp")
	if err != nil {
		return nil
	}
	n, err := strconv.Atoi(strings.TrimSpace(string(b)))
	if err != nil {
		return nil
	}
	if n > 1000 {
		return float64(n) / 1000
	}
	return float64(n)
}

func (x *supaSync) healthRow() sbRow {
	crit, warn := 0, 0
	if x.s != nil && x.s.rsn != nil {
		for _, inc := range x.s.rsn.List() {
			if inc.SystemCheck || wfOf(inc) == wfClosed {
				continue
			}
			switch normSeverity(inc.Severity) {
			case "critical":
				crit++
			case "warning":
				warn++
			}
		}
	}
	d := map[string]any{"board_id": x.board, "at": nowTime().UTC().Format(time.RFC3339), "app_version": appBuildVersion(),
		"agent_model": filepath.Base(htpdProfile()["model"]), "reasoner_model": filepath.Base(profStr("reasoner_model")),
		"open_critical": crit, "open_warning": warn, "temp_c": cpuTempC()}
	status := map[string]any{"agent": agentVer}
	if x.s != nil {
		d["uptime_s"] = int64(time.Since(x.s.start).Seconds())
		w, _ := restartCounts(x.s.dir, nowTime())
		d["restarts_7d"] = w
		if di := diskInfo(x.s.dir); di.OK {
			d["disk_used_pct"] = di.UsedPct
		}
		status["store_write_errors"] = storeWriteErrors.Load()
	}
	d["status"] = status
	return sbRow{"board_health", d}
}

func appBuildVersion() string {
	if v := os.Getenv("SCE_APP_VERSION"); v != "" {
		return v
	}
	return "dev"
}

// plain inserts only (2026-11-20): ON CONFLICT needs a SELECT policy under RLS, which the write-only board key must not have;
// a duplicate primary key answers 409 = "already there".
var sbConflict = map[string]string{}

func (x *supaSync) post(r sbRow) error {
	var err error
	for i, base := range x.bases(time.Now()) {
		var netErr bool
		if err, netErr = x.postTo(base, r); err == nil || !netErr {
			return err
		}
		if i == 0 && base == x.url && x.relay != "" {
			x.directDown = time.Now().Add(5 * time.Minute)
		}
	}
	return err // every path down: the row stays queued for the next try
}

func (x *supaSync) postTo(base string, r sbRow) (error, bool) {
	u := base + "/rest/v1/" + r.T
	pref := "return=minimal"
	if c, ok := sbConflict[r.T]; ok {
		u += "?on_conflict=" + c
		pref += ",resolution=ignore-duplicates"
	}
	b, _ := json.Marshal(r.D)
	req, _ := http.NewRequest("POST", u, bytes.NewReader(b))
	req.Header.Set("apikey", x.key)
	req.Header.Set("Authorization", "Bearer "+x.key)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Prefer", pref)
	resp, err := x.client.Do(req)
	if err != nil {
		return fmt.Errorf("%s: %v", r.T, strings.ReplaceAll(err.Error(), x.key, "***")), true
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, io.LimitReader(resp.Body, 1024))
	if resp.StatusCode >= 300 {
		if resp.StatusCode == 409 {
			return nil, false // already there
		}
		if resp.StatusCode >= 400 && resp.StatusCode < 500 && resp.StatusCode != 429 && resp.StatusCode != 401 && resp.StatusCode != 403 {
			log.Printf("supabase: dropping unacceptable %s row (%d)", r.T, resp.StatusCode)
			return nil, false // a bad row must not block the queue
		}
		return fmt.Errorf("%s: HTTP %d", r.T, resp.StatusCode), resp.StatusCode == 502 || resp.StatusCode == 503 || resp.StatusCode == 504
	}
	return nil, false
}

// flush sends queued rows in order; stops at the first failure (kept for the next try).
func (x *supaSync) flush() error {
	for {
		x.mu.Lock()
		if !x.boardSent {
			x.boardSent = true
			x.rows = append([]sbRow{{"boards", map[string]any{"board_id": x.board, "site": x.site}}}, x.rows...)
		}
		if len(x.rows) == 0 {
			x.mu.Unlock()
			return nil
		}
		r := x.rows[0]
		x.mu.Unlock()
		if err := x.post(r); err != nil {
			x.mu.Lock()
			x.lastErr = err.Error()
			x.mu.Unlock()
			return err
		}
		x.mu.Lock()
		if len(x.rows) > 0 && x.rows[0].T == r.T { // the cap may have dropped it meanwhile
			x.rows = x.rows[1:]
		}
		x.lastOK, x.lastErr = nowTime(), ""
		x.saveLocked()
		x.mu.Unlock()
	}
}

func (x *supaSync) Stats() map[string]any {
	x.mu.Lock()
	defer x.mu.Unlock()
	lo := ""
	if !x.lastOK.IsZero() {
		lo = x.lastOK.UTC().Format(time.RFC3339)
	}
	return map[string]any{"enabled": true, "queued": len(x.rows), "last_ok": lo, "last_error": x.lastErr}
}

func (x *supaSync) Run(stop <-chan struct{}) {
	backoff := 5 * time.Second
	hc := time.NewTicker(15 * time.Minute)
	defer hc.Stop()
	x.mu.Lock()
	x.enqueueLocked(x.healthRow())
	x.mu.Unlock()
	for {
		if err := x.flush(); err != nil {
			select {
			case <-stop:
				return
			case <-time.After(backoff):
			}
			if backoff < 10*time.Minute {
				backoff *= 2
			}
			continue
		}
		backoff = 5 * time.Second
		select {
		case <-stop:
			return
		case <-x.wake:
		case <-hc.C:
			x.mu.Lock()
			x.enqueueLocked(x.healthRow())
			x.mu.Unlock()
		}
	}
}

var supa *supaSync

func supaStats() any {
	if supa == nil {
		return map[string]any{"enabled": false}
	}
	return supa.Stats()
}
