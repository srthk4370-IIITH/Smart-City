package main

// Early-AI gate study harness (2026-11-12; proofs/2026-11-12_early_ai). Copied into a scratch copy of app/backend
// in WSL (never into the repo backend). For each gate-study row (proofs/2026-10-28_master/gate_study/eval3e.jsonl:
// the same real-history event rendered after k = 3..8 abnormal readings, teacher gold per k) it feeds the row's
// 12 h history into a real Engine as a measured device feed, reads the gate state the engine reached, and - when
// the rules flag the sensor - runs the app's own Mode-3 analysis (domain agents through an htpd-protocol shim on a
// host llama-server, reasoner v3 through llamaServerLLM) on the incident buildIncident makes at that reading.
//
//	EAS_DATA=eval3e.jsonl EAS_OUT=out.jsonl EAS_SHARD=0 EAS_NSHARD=2 go test -run TestEarlyAIStudy -timeout 0 .

import (
	"bufio"
	"context"
	"encoding/json"
	"math"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"
)

type easRow struct {
	ID       string    `json:"id"`
	Group    string    `json:"group"`
	Shape    string    `json:"shape"`
	K        int       `json:"k"`
	Role     string    `json:"role"`
	Node     string    `json:"node"`
	Metric   string    `json:"metric"`
	Seen     string    `json:"seen"`
	EndEpoch int64     `json:"end_epoch"`
	Hist     []float64 `json:"hist"`
	Pattern  string    `json:"pattern"`
	Status   string    `json:"status"`
	Cause    string    `json:"likely_cause"`
	Fault    *string   `json:"fault_kind"`
	Sub      string    `json:"sub"`
}

func TestEarlyAIStudy(t *testing.T) {
	data, out := os.Getenv("EAS_DATA"), os.Getenv("EAS_OUT")
	if data == "" {
		t.Skip("EAS_DATA not set")
	}
	shard, _ := strconv.Atoi(os.Getenv("EAS_SHARD"))
	nshard, _ := strconv.Atoi(os.Getenv("EAS_NSHARD"))
	if nshard <= 0 {
		nshard = 1
	}
	maxGroups, _ := strconv.Atoi(os.Getenv("EAS_GROUPS")) // per role x shape; 0 = all
	initAgentVersion("../device")
	htpdWorkDir = os.Getenv("EAS_WORK")
	done := map[string]bool{}
	if f, err := os.Open(out); err == nil {
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 1<<20), 1<<26)
		for sc.Scan() {
			var r struct{ ID string }
			if json.Unmarshal(sc.Bytes(), &r) == nil {
				done[r.ID] = true
			}
		}
		f.Close()
	}
	// group order: round-robin over role x shape so a partial run stays balanced
	var rows []easRow
	f, err := os.Open(data)
	if err != nil {
		t.Fatal(err)
	}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<26)
	for sc.Scan() {
		var r easRow
		if json.Unmarshal(sc.Bytes(), &r) == nil {
			rows = append(rows, r)
		}
	}
	f.Close()
	byCell := map[string][]string{}
	grp := map[string][]easRow{}
	var cells []string
	for _, r := range rows {
		c := r.Role + "/" + r.Shape
		if _, ok := byCell[c]; !ok {
			cells = append(cells, c)
		}
		if len(grp[r.Group]) == 0 {
			byCell[c] = append(byCell[c], r.Group)
		}
		grp[r.Group] = append(grp[r.Group], r)
	}
	var order []string
	for i := 0; ; i++ {
		any := false
		for _, c := range cells {
			if i < len(byCell[c]) && (maxGroups == 0 || i < maxGroups) {
				order = append(order, byCell[c][i])
				any = true
			}
		}
		if !any {
			break
		}
	}
	w, err := os.OpenFile(out, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Close()
	n := 0
	for gi, g := range order {
		if gi%nshard != shard {
			continue
		}
		for _, r := range grp[g] {
			if done[r.ID] {
				continue
			}
			for _, err := os.Stat(os.Getenv("EAS_PAUSE")); err == nil; _, err = os.Stat(os.Getenv("EAS_PAUSE")) {
				time.Sleep(10 * time.Second)
			}
			if _, err := os.Stat(os.Getenv("EAS_STOP")); err == nil {
				t.Logf("stop file: %d rows this run", n)
				return
			}
			rec := easRun(t, r)
			b, _ := json.Marshal(rec)
			w.Write(append(b, '\n'))
			n++
		}
	}
	t.Logf("shard %d done: %d rows", shard, n)
}

func easRun(t *testing.T, r easRow) map[string]any {
	rec := map[string]any{"id": r.ID, "group": r.Group, "shape": r.Shape, "k": r.K, "role": r.Role, "node": r.Node,
		"metric": r.Metric, "seen": r.Seen, "sub": r.Sub, "gold_pattern": r.Pattern, "gold_status": r.Status,
		"gold_cause": r.Cause, "gold_fault": r.Fault}
	e, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	e.NoiseScale = 0
	// the app's sensor bank has one live sensor per role/metric (device/data/sensors.json): an event from another
	// node is replayed on the bank sensor of the same role and metric whose range holds every reading
	if e.bank[key(r.Node, r.Metric)] == nil {
		lo, hi := r.Hist[0], r.Hist[0]
		for _, v := range r.Hist {
			lo, hi = math.Min(lo, v), math.Max(hi, v)
		}
		for _, k := range e.bankOrder {
			if sn := e.bank[k]; sn.Role == r.Role && sn.Metric == r.Metric && sn.Min <= lo && hi <= sn.Max {
				rec["standin"] = sn.Node
				r.Node = sn.Node
				break
			}
		}
		if rec["standin"] == nil {
			rec["error"] = "no bank sensor for " + r.Role + "/" + r.Metric + " in range"
			return rec
		}
	}
	// sensor clock: the row's own time of day (IST) for the first history reading
	first := r.EndEpoch - int64(len(r.Hist)-1)*bucketSec
	ist := time.Unix(first, 0).In(time.FixedZone("IST", 19800))
	e.SetClock(ist.Hour()*60 + ist.Minute())
	wall := int64(2_000_000_000)
	for _, v := range r.Hist {
		wall += bucketSec
		v := v
		if _, err := e.IngestReading(Reading{Node: r.Node, Metric: r.Metric, Value: &v, Ts: float64(wall)}, wall); err != nil {
			rec["error"] = "ingest: " + err.Error()
			return rec
		}
		e.Tick()
	}
	e.mu.RLock()
	st := e.states[key(r.Node, r.Metric)]
	var c *Candidate
	if st != nil {
		rec["rule_pattern"], rec["rule_status"], rec["abnormal_for"] = st.Pattern, st.Status, st.AbnormalFor
		if st.Finding != nil && sevRank(st.Status) > 0 {
			rec["rule_shape"] = shapeOf(*st.Finding)
			c = &Candidate{st.Node, st.Metric, st.Role, *st.Finding, nil, e.sim, false, false, r.K < persistReadings}
		}
	}
	e.mu.RUnlock()
	if c == nil {
		rec["gated"] = false // the rules do not flag the sensor at this reading: the app would not call the AI
		return rec
	}
	xs, ok := e.Window(c.Node, c.Metric, c.End)
	if !ok {
		rec["gated"] = false
		rec["error"] = "no window"
		return rec
	}
	c.Xs = xs
	rec["gated"] = true
	if os.Getenv("EAS_DRY") != "" {
		return rec
	}
	dir := t.TempDir()
	rs := NewReasoner(NewGenieRunner(dir, dir, false), e, dir, func(string, any) {})
	inc := rs.buildIncident([]Candidate{*c}, 3)
	t0 := time.Now()
	ok = rs.analyse(context.Background(), inc, 3, t0, nil)
	rec["ok"], rec["ms"], rec["npu_calls"] = ok, time.Since(t0).Milliseconds(), inc.NPUCalls
	var ag []map[string]any
	for _, a := range inc.Agents {
		m := map[string]any{"ref": a.Ref, "role": a.Role, "valid": a.Valid}
		if a.Parsed != nil {
			m["pattern"], m["status"], m["cause"] = a.Parsed.Pattern, a.Parsed.Status, a.Parsed.LikelyCause
		}
		ag = append(ag, m)
	}
	rec["agents"] = ag
	rec["inc_severity"] = inc.Severity
	rec["title"] = inc.Title
	if fc := inc.Final; fc != nil {
		rec["valid"], rec["model"], rec["errors"], rec["gen_tokens"] = fc.Valid, fc.Model, fc.Errors, fc.GenTokens
		if p := fc.Parsed; p != nil {
			var acts []string
			for _, x := range p.Checklist {
				acts = append(acts, x.Action)
			}
			var vs []string
			for _, x := range p.AgentChecks {
				vs = append(vs, x.Ref+":"+x.Verdict)
			}
			rec["severity"], rec["label"], rec["checklist"], rec["agent_checks"] = p.Severity, p.Label, acts, vs
			rec["suspects"], rec["needs_more_data"], rec["source"] = p.SuspectSensors, p.NeedsMoreData, p.Source
		}
		if len(fc.Prompt) > 0 {
			i := strings.Index(fc.Prompt, "CONTEXT:")
			if i >= 0 {
				j := i + 60
				if j > len(fc.Prompt) {
					j = len(fc.Prompt)
				}
				rec["context"] = fc.Prompt[i:j]
			}
		}
	}
	return rec
}
