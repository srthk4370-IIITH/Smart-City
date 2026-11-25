package main

// Fog tools with a deterministic device fallback, the all-time incident index, and three local cross-domain tools
// (rsn_v3 4B r3, 2026-11-06; proofs/2026-11-06_4b_local/TOOLS.md). Training side: tools/tools_r3_impl.py there; both are
// checked on one fixture (chat_fog_parity_test.go).
//
//   - Device store = the newest 1000 incidents in full (store.go) + an index of every archived incident
//     (incidents.archive.jsonl, read back stripped to the index fields: id, time, title, severity, label, flagged sensors with
//     pattern/status/fault kind, approval, workflow, outcome, injected). The chat tools count over both, so offline counts stay
//     exact (DECISIONS.md "Device store").
//   - Fog tools (fog_search_history, fog_analytics, search_knowledge, fog_status; get_incident for an archived id) first ask the
//     fog: POST {fog_url}/v1/tool {"name","args"} -> the same result object computed over the fog's full store, within
//     fog_timeout_ms (default 2000, DECISIONS.md). Fog unset, unreachable, timeout or HTTP error -> the backend runs the same
//     query on the device store and returns source "device_fallback", fog "unreachable" and a coverage block saying what the
//     device holds. The model never decides the fallback. After a failure the fog is not asked again for 30 s (no second
//     timeout inside one answer).
//   - The chat prompt's fog sentence follows the live state (chatFogLine), refreshed by a background /v1/status probe.
//   - FogHandler serves the same queries over a full store (a laptop or fog box running this backend; also the tests).

import (
	"bufio"
	"bytes"
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

//go:embed fog_kb_cache.txt
var fogKBCacheJSON []byte

type kbPassage struct {
	ID     string `json:"id"`
	Title  string `json:"title"`
	Source string `json:"source"`
	Text   string `json:"text"`
}

var fogKBCache = func() []kbPassage {
	var ps []kbPassage
	if err := json.Unmarshal(fogKBCacheJSON, &ps); err != nil {
		panic("fog_kb_cache.txt: " + err.Error())
	}
	return ps
}()

// ---------------------------------------------------------------- fog client and live state

const fogRetryAfter = 30 * time.Second

var errFogUnreachable = errors.New("fog unreachable")

type fogClient struct {
	mu        sync.Mutex
	lastOK    time.Time // last successful fog contact (the last sync until the uploader exists)
	lastFail  time.Time
	probing   bool
	stateFile string
	saved     time.Time
}

var fogC = &fogClient{}

func fogURL() string { return strings.TrimRight(reasonerProfile("fog_url", "SCE_FOG_URL"), "/") }

func fogTimeout() time.Duration {
	if v, err := strconv.Atoi(reasonerProfile("fog_timeout_ms", "SCE_FOG_TIMEOUT_MS")); err == nil && v >= 100 && v <= 10000 {
		return time.Duration(v) * time.Millisecond
	}
	return 2 * time.Second
}

// fogInit: the last sync survives restarts (state/fog_state.json).
func fogInit(dir string) {
	f := fogC
	f.mu.Lock()
	defer f.mu.Unlock()
	f.stateFile = filepath.Join(dir, "state", "fog_state.json")
	var st struct {
		LastSync int64 `json:"last_sync"`
	}
	if b, err := os.ReadFile(f.stateFile); err == nil && json.Unmarshal(b, &st) == nil && st.LastSync > 0 {
		f.lastOK = time.Unix(st.LastSync, 0)
	}
}

func (f *fogClient) mark(ok bool) {
	f.mu.Lock()
	defer f.mu.Unlock()
	now := time.Now()
	if !ok {
		f.lastFail = now
		return
	}
	f.lastOK = now
	if f.stateFile != "" && now.Sub(f.saved) > time.Minute {
		f.saved = now
		b, _ := json.Marshal(map[string]int64{"last_sync": now.Unix()})
		atomicWrite(f.stateFile, b, 0o644)
	}
}

// down: the last contact failed less than fogRetryAfter ago (answer from the device at once).
func (f *fogClient) down() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return !f.lastFail.IsZero() && f.lastFail.After(f.lastOK) && time.Since(f.lastFail) < fogRetryAfter
}

func (f *fogClient) do(ctx context.Context, method, path string, body any) (map[string]any, error) {
	u := fogURL()
	if u == "" {
		return nil, errFogUnreachable
	}
	ctx, cancel := context.WithTimeout(ctx, fogTimeout())
	defer cancel()
	var rd io.Reader
	if body != nil {
		b, _ := json.Marshal(body)
		rd = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, u+path, rd)
	if err != nil {
		f.mark(false)
		return nil, errFogUnreachable
	}
	req.Header.Set("Content-Type", "application/json")
	if tok := reasonerProfile("fog_token", "SCE_FOG_TOKEN"); tok != "" {
		req.Header.Set("Authorization", "Bearer "+tok)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		f.mark(false)
		return nil, errFogUnreachable
	}
	defer resp.Body.Close()
	var out map[string]any
	if resp.StatusCode != http.StatusOK || json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(&out) != nil || out == nil {
		f.mark(false)
		return nil, errFogUnreachable
	}
	f.mark(true)
	return out, nil
}

// Call asks the fog for one tool result. A result with "error" (bad arguments) is the fog's answer, not an outage.
func (f *fogClient) Call(ctx context.Context, name string, args map[string]any) (map[string]any, error) {
	if fogURL() == "" || f.down() {
		return nil, errFogUnreachable
	}
	return f.do(ctx, http.MethodPost, "/v1/tool", map[string]any{"name": name, "args": args})
}

// Refresh probes /v1/status in the background when the state is older than a minute (prompt build, keep-warm).
func (f *fogClient) Refresh() {
	if fogURL() == "" {
		return
	}
	f.mu.Lock()
	last := f.lastOK
	if f.lastFail.After(last) {
		last = f.lastFail
	}
	if f.probing || time.Since(last) < time.Minute {
		f.mu.Unlock()
		return
	}
	f.probing = true
	f.mu.Unlock()
	go func() {
		defer recoverLog("fog probe")
		f.do(context.Background(), http.MethodGet, "/v1/status", nil)
		f.mu.Lock()
		f.probing = false
		f.mu.Unlock()
	}()
}

// State: configured, reachable (the last contact succeeded within 3 min), last sync.
func (f *fogClient) State() (bool, bool, time.Time) {
	conf := fogURL() != ""
	f.mu.Lock()
	defer f.mu.Unlock()
	ok := conf && !f.lastOK.IsZero() && !f.lastFail.After(f.lastOK) && time.Since(f.lastOK) < 3*time.Minute
	return conf, ok, f.lastOK
}

// chatFogLine: the fog sentence of the r3 chat prompt (training: tools/gen_chat_r3.py fog_line()).
func chatFogLine() string {
	fogC.Refresh()
	_, ok, last := fogC.State()
	if ok {
		return "The device is online: the fog server is reachable."
	}
	if last.IsZero() {
		return "The device is offline: the fog server is unreachable (never synced)."
	}
	return "The device is offline: the fog server is unreachable (last sync " + last.In(IST).Format("2006-01-02 15:04") + ")."
}

// chatFogRef: the Reasoner the chat serves (set per question and keep-warm), for the prompt's device-store sentence.
var chatFogRef atomic.Pointer[Reasoner]

// chatDeviceSince: the date of the oldest full incident record on the device (the device time's date when there is none).
func chatDeviceSince(now time.Time) string {
	since := now
	if r := chatFogRef.Load(); r != nil {
		r.mu.RLock()
		for _, p := range r.incidents {
			if x := time.Unix(p.CreatedSim, 0); x.Before(since) {
				since = x
			}
		}
		r.mu.RUnlock()
	}
	return fogDate(since)
}

// ---------------------------------------------------------------- the all-time incident index (archived incidents)

type archiveCache struct {
	mu   sync.Mutex
	path string
	size int64
	mod  time.Time
	incs []*Incident
}

var chatArchive archiveCache

// chatArchived: the archived incidents as index rows, oldest first (re-read when the archive file changes).
func (r *Reasoner) chatArchived() []*Incident {
	if r == nil || r.store == "" {
		return nil
	}
	p := archivePath(r.store)
	st, err := os.Stat(p)
	if err != nil {
		return nil
	}
	c := &chatArchive
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.path == p && c.size == st.Size() && c.mod.Equal(st.ModTime()) {
		return c.incs
	}
	f, err := os.Open(p)
	if err != nil {
		return nil
	}
	defer f.Close()
	last := map[string]*Incident{}
	var order []string
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 64<<20)
	for sc.Scan() {
		var inc Incident
		if json.Unmarshal(sc.Bytes(), &inc) != nil || inc.ID == "" {
			continue
		}
		if _, ok := last[inc.ID]; !ok {
			order = append(order, inc.ID)
		}
		last[inc.ID] = chatIndexRow(&inc)
	}
	out := make([]*Incident, 0, len(order))
	for _, id := range order {
		out = append(out, last[id])
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].CreatedSim < out[j].CreatedSim })
	c.path, c.size, c.mod, c.incs = p, st.Size(), st.ModTime(), out
	return out
}

// chatIndexRow keeps only the index fields of an incident (about 300 B: what the device keeps after archiving).
func chatIndexRow(p *Incident) *Incident {
	x := &Incident{ID: p.ID, State: p.State, CreatedSim: p.CreatedSim, CreatedWall: p.CreatedWall, Severity: p.Severity, Title: p.Title,
		Injected: p.Injected, Approval: p.Approval, RefineStage: p.RefineStage}
	x.Workflow, x.Outcome = p.Workflow, p.Outcome
	for _, s := range p.Sensors {
		if !s.Context {
			x.Sensors = append(x.Sensors, SensorRef{Ref: s.Ref, Node: s.Node, Metric: s.Metric, Role: s.Role, Rule: Finding{Status: s.Rule.Status, Pattern: s.Rule.Pattern}})
		}
	}
	for _, a := range p.Agents {
		if a.Valid && a.Parsed != nil {
			x.Agents = append(x.Agents, AgentCall{Ref: a.Ref, Valid: true, Parsed: &Finding{Status: a.Parsed.Status, Pattern: a.Parsed.Pattern, FaultKind: a.Parsed.FaultKind}})
		}
	}
	if p.Final != nil && p.Final.Parsed != nil && !p.Final.Preliminary {
		x.Final = &ReportCall{Valid: true, Parsed: &Report{Label: p.Final.Parsed.Label}}
	}
	return x
}

// ---------------------------------------------------------------- views a fog query runs over

type fogView struct {
	incs      []chatInc // oldest first
	nFull     int
	fullFrom  time.Time
	indexFrom time.Time
	onFog     bool
	kb        []kbPassage
}

// deviceView: full records + index rows.
func (t chatTools) deviceView() fogView {
	incs := t.incidents()
	sort.SliceStable(incs, func(i, j int) bool {
		if !incs[i].at.Equal(incs[j].at) {
			return incs[i].at.Before(incs[j].at)
		}
		return incs[i].inc.ID < incs[j].inc.ID
	})
	v := fogView{incs: incs, kb: fogKBCache, fullFrom: t.now, indexFrom: t.now}
	first := true
	for _, ci := range incs {
		if ci.archived {
			continue
		}
		v.nFull++
		if first || ci.at.Before(v.fullFrom) {
			v.fullFrom, first = ci.at, false
		}
	}
	if len(incs) > 0 {
		v.indexFrom = incs[0].at
	}
	return v
}

// fogViewOf: every incident is a full record (FogHandler on a fog box).
func (t chatTools) fogViewOf(kb []kbPassage) fogView {
	v := t.deviceView()
	for i := range v.incs {
		v.incs[i].archived = false
	}
	v.nFull, v.fullFrom, v.onFog, v.kb = len(v.incs), v.indexFrom, true, kb
	return v
}

func fogDate(x time.Time) string { return x.In(IST).Format("2006-01-02") }

func (t chatTools) fogCov(v fogView, a, b time.Time, countsExact, index bool) map[string]any {
	if b.After(t.now) {
		b = t.now
	}
	if v.onFog {
		return map[string]any{"from": fogDate(v.indexFrom), "to": chatTS(b), "incidents": len(v.incs), "complete": true}
	}
	start := v.fullFrom
	if index {
		start = v.indexFrom
	}
	return map[string]any{"from": fogDate(v.fullFrom), "to": chatTS(b), "incidents": v.nFull,
		"complete": !a.Before(start) || (index && a.Year() == 2000), "index_from": fogDate(v.indexFrom), "counts_exact": countsExact,
		"note": fmt.Sprintf("fog unreachable: full records for the last %d incidents on this device (since %s); older incidents from the all-time index (no root cause or checklist)", v.nFull, fogDate(v.fullFrom))}
}

var fogSevs = []string{"critical", "warning", "sensor_fault", "normal"}

func fogSevSet(v any) (map[string]bool, error) {
	out := map[string]bool{}
	add := func(s string) error {
		if !contains(fogSevs, s) {
			return fmt.Errorf("unknown severity %q", s)
		}
		out[s] = true
		return nil
	}
	switch x := v.(type) {
	case nil:
	case string:
		if x != "" {
			return out, add(x)
		}
	case []any:
		for _, e := range x {
			s, _ := e.(string)
			if err := add(s); err != nil {
				return nil, err
			}
		}
	default:
		return nil, errors.New("severity must be a string or a list")
	}
	return out, nil
}

// fogFilter: non-injected incidents of [a, b) matching the filters, newest first (training: Store.filter).
func fogFilter(incs []chatInc, args map[string]any, a, b time.Time) ([]chatInc, error) {
	dom, metric, node, label := strArg(args, "domain"), strArg(args, "metric"), strArg(args, "node"), strArg(args, "label")
	if dom != "" && !contains(chatDomains, dom) {
		return nil, fmt.Errorf("unknown domain %q", dom)
	}
	sevs, err := fogSevSet(args["severity"])
	if err != nil {
		return nil, err
	}
	words := strings.Fields(strings.ToLower(strArg(args, "text")))
	var out []chatInc
	for _, ci := range incs {
		p := ci.inc
		if p.Injected || ci.at.Before(a) || !ci.at.Before(b) {
			continue
		}
		if len(sevs) > 0 && !sevs[normSeverity(p.Severity)] {
			continue
		}
		if label != "" && ci.label != label {
			continue
		}
		if dom != "" || metric != "" || node != "" {
			ok := false
			for _, s := range ci.sensors {
				if (dom == "" || s.Role == dom) && (metric == "" || s.Metric == metric) &&
					(node == "" || strings.Contains(s.Node, node) || strings.Contains(strings.ReplaceAll(s.Node, "-", ""), node)) {
					ok = true
				}
			}
			if !ok {
				continue
			}
		}
		if len(words) > 0 {
			hay := strings.ToLower(p.Title + " " + ci.root + " " + ci.label)
			miss := false
			for _, w := range words {
				miss = miss || !strings.Contains(hay, w)
			}
			if miss {
				continue
			}
		}
		out = append(out, ci)
	}
	sort.SliceStable(out, func(i, j int) bool {
		if !out[i].at.Equal(out[j].at) {
			return out[i].at.After(out[j].at)
		}
		return out[i].inc.ID > out[j].inc.ID
	})
	return out, nil
}

func fogItem(ci chatInc, root bool) map[string]any {
	doms := ci.domains
	if doms == nil {
		doms = []string{}
	}
	m := map[string]any{"id": ci.inc.ID, "time": chatTS(ci.at), "title": ci.inc.Title, "severity": normSeverity(ci.inc.Severity),
		"label": chatNull(ci.label), "domains": doms, "outcome": chatNull(ci.inc.Outcome)}
	if root {
		m["root_cause"] = chatNull(ci.root)
	}
	return m
}

func intArg(args map[string]any, k string, def, lo, hi int) int {
	f, ok := args[k].(float64)
	if !ok {
		if s, ok2 := args[k].(string); ok2 {
			if v, err := strconv.Atoi(strings.TrimSpace(s)); err == nil {
				f, ok = float64(v), true
			}
		}
	}
	if !ok {
		return def
	}
	return int(math.Max(float64(lo), math.Min(float64(hi), math.Trunc(f))))
}

func round1(x float64) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', 1, 64), 64)
	return v
}

func median(xs []float64) float64 {
	s := append([]float64(nil), xs...)
	sort.Float64s(s)
	n := len(s)
	if n%2 == 1 {
		return s[n/2]
	}
	return (s[n/2-1] + s[n/2]) / 2
}

// fogWallOf: an incident's creation time on the people clock (resolve times use wall clocks on both ends).
func fogWallOf(p *Incident) time.Time {
	for _, f := range []string{"2006-01-02 15:04:05", "2006-01-02 15:04", time.RFC3339} {
		if x, err := time.ParseInLocation(f, p.CreatedWall, IST); err == nil {
			return x
		}
	}
	return time.Unix(p.CreatedSim, 0)
}

// runFogQuery: one fog tool over a view (the fog's full store, or the device store as the fallback).
func (t chatTools) runFogQuery(name string, args map[string]any, v fogView) (map[string]any, error) {
	switch name {
	case "fog_search_history":
		for k := range args {
			if !contains([]string{"time", "domain", "metric", "node", "severity", "label", "text", "limit"}, k) {
				return nil, fmt.Errorf("unknown argument %q", k)
			}
		}
		a, b, err := t.span(args["time"], true)
		if err != nil {
			return nil, err
		}
		incs, err := fogFilter(v.incs, args, a, b)
		if err != nil {
			return nil, err
		}
		limit := intArg(args, "limit", 5, 1, 10)
		items := []map[string]any{}
		for i := 0; i < len(incs) && i < limit; i++ {
			items = append(items, fogItem(incs[i], true))
		}
		return map[string]any{"total": len(incs), "items": items, "coverage": t.fogCov(v, a, b, strArg(args, "text") == "", false)}, nil
	case "fog_analytics":
		an := strArg(args, "analysis")
		if an == "sensor_monthly" {
			return t.fogSensorMonthly(args, v)
		}
		if an != "incident_trend" && an != "resolve_time" {
			return nil, errors.New("analysis must be incident_trend|resolve_time|sensor_monthly")
		}
		a, b, err := t.span(args["time"], true)
		if err != nil {
			return nil, err
		}
		incs, err := fogFilter(v.incs, args, a, b)
		if err != nil {
			return nil, err
		}
		if an == "incident_trend" {
			bucket := strArg(args, "bucket")
			if bucket == "" {
				bucket = "month"
			}
			if bucket != "month" && bucket != "week" {
				return nil, errors.New("bucket must be month|week")
			}
			key := func(x time.Time) string {
				x = x.In(IST)
				if bucket == "month" {
					return x.Format("2006-01")
				}
				y, w := x.ISOWeek()
				return fmt.Sprintf("%d-W%02d", y, w)
			}
			start, end := a, b
			if v.indexFrom.After(start) {
				start = v.indexFrom
			}
			if end.After(t.now) {
				end = t.now
			}
			s := start.In(IST)
			var cur time.Time
			if bucket == "month" {
				cur = time.Date(s.Year(), s.Month(), 1, 0, 0, 0, 0, IST)
			} else {
				d := time.Date(s.Year(), s.Month(), s.Day(), 0, 0, 0, 0, IST)
				cur = d.AddDate(0, 0, -((int(d.Weekday()) + 6) % 7))
			}
			cnt := map[string]int{}
			for _, ci := range incs {
				cnt[key(ci.at)]++
			}
			buckets := []map[string]any{}
			var peak map[string]any
			for cur.Before(end) {
				k := key(cur)
				bk := map[string]any{"key": k, "count": cnt[k]}
				buckets = append(buckets, bk)
				if peak == nil || cnt[k] > peak["count"].(int) {
					peak = bk
				}
				if bucket == "month" {
					cur = cur.AddDate(0, 1, 0)
				} else {
					cur = cur.AddDate(0, 0, 7)
				}
			}
			mean := 0.0
			if len(buckets) > 0 {
				mean = round1(float64(len(incs)) / float64(len(buckets)))
			}
			var pk any
			if peak != nil {
				pk = peak
			}
			cov := t.fogCov(v, a, b, true, true)
			if !v.onFog {
				cov["note"] = "fog unreachable: counted on this device from its all-time incident index (counts exact)"
			}
			return map[string]any{"analysis": an, "bucket": bucket, "total": len(incs), "buckets": buckets, "peak": pk,
				"mean_per_bucket": mean, "coverage": cov}, nil
		}
		g := strArg(args, "group_by")
		if g == "" {
			g = "label"
		}
		if g != "label" && g != "domain" {
			return nil, errors.New("group_by must be label|domain")
		}
		hrs := map[string][]float64{}
		var all []float64
		for _, ci := range incs {
			p := ci.inc
			if p.ClosedAt == 0 || wfOf(p) != wfClosed {
				continue
			}
			h := float64(time.Unix(p.ClosedAt, 0).Sub(fogWallOf(p))) / float64(time.Hour)
			all = append(all, h)
			keys := ci.domains
			if g == "label" {
				l := ci.label
				if l == "" {
					l = "none"
				}
				keys = []string{l}
			}
			for _, k := range keys {
				hrs[k] = append(hrs[k], h)
			}
		}
		groups := []map[string]any{}
		for k, xs := range hrs {
			sum := 0.0
			for _, x := range xs {
				sum += x
			}
			groups = append(groups, map[string]any{"key": k, "closed": len(xs), "mean_h": round1(sum / float64(len(xs))), "median_h": round1(median(xs))})
		}
		sort.Slice(groups, func(i, j int) bool {
			if groups[i]["closed"].(int) != groups[j]["closed"].(int) {
				return groups[i]["closed"].(int) > groups[j]["closed"].(int)
			}
			return groups[i]["key"].(string) < groups[j]["key"].(string)
		})
		if len(groups) > 8 {
			groups = groups[:8]
		}
		var mean, med any
		if len(all) > 0 {
			sum := 0.0
			for _, x := range all {
				sum += x
			}
			mean, med = round1(sum/float64(len(all))), round1(median(all))
		}
		cov := t.fogCov(v, a, b, true, false)
		if !v.onFog {
			cov["note"] = "fog unreachable: only incidents with full records on this device (since " + fogDate(v.fullFrom) + ")"
			cov["counts_exact"] = cov["complete"]
		}
		return map[string]any{"analysis": an, "group_by": g, "closed": len(all), "mean_h": mean, "median_h": med, "groups": groups, "coverage": cov}, nil
	case "search_knowledge":
		q := strArg(args, "query")
		if q == "" {
			return nil, errors.New("'query' is required")
		}
		k := intArg(args, "k", 3, 1, 5)
		qt := map[string]bool{}
		for _, w := range kbTokens(q) {
			qt[w] = true
		}
		type hit struct {
			s, i int
		}
		var hits []hit
		for i, p := range v.kb {
			pt := map[string]bool{}
			for _, w := range kbTokens(p.ID + " " + p.Title + " " + p.Text) {
				pt[w] = true
			}
			s := 0
			for w := range qt {
				if pt[w] {
					s++
				}
			}
			if s > 0 {
				hits = append(hits, hit{s, i})
			}
		}
		sort.Slice(hits, func(i, j int) bool {
			if hits[i].s != hits[j].s {
				return hits[i].s > hits[j].s
			}
			return hits[i].i < hits[j].i
		})
		ps := []map[string]any{}
		for i := 0; i < len(hits) && i < k; i++ {
			p := v.kb[hits[i].i]
			ps = append(ps, map[string]any{"id": p.ID, "title": p.Title, "source": p.Source, "text": p.Text})
		}
		res := map[string]any{"available": len(ps) > 0, "passages": ps}
		if !v.onFog {
			res["coverage"] = map[string]any{"passages": len(v.kb), "complete": false,
				"note": "fog unreachable: searched only the device cache of key limits and SOPs"}
		}
		return res, nil
	}
	return nil, fmt.Errorf("unknown fog tool %q", name)
}

// fogStatus: the fog connection as the device sees it (always answered on the device; /v1/status when configured).
func (t chatTools) fogStatus(ctx context.Context) map[string]any {
	dv := t.deviceView()
	var st map[string]any
	var err error = errFogUnreachable
	if fogURL() != "" && !fogC.down() {
		st, err = fogC.do(ctx, http.MethodGet, "/v1/status", nil)
	}
	_, _, last := fogC.State()
	var ls any
	if !last.IsZero() {
		ls = chatTS(last)
	}
	pend := 0
	for _, ci := range dv.incs {
		if last.IsZero() || fogWallOf(ci.inc).After(last) {
			pend++
		}
	}
	res := map[string]any{"source": "device_fallback", "fog": "unreachable", "last_sync": ls, "pending_uploads": pend,
		"device_store": map[string]any{"full_incidents": dv.nFull, "since": fogDate(dv.fullFrom), "index_rows": len(dv.incs), "index_from": fogDate(dv.indexFrom)}}
	if err == nil {
		res["source"], res["fog"] = "fog", "reachable"
		if n, ok := st["incidents"].(float64); ok {
			res["fog_incidents"] = int(n)
		}
	}
	return res
}

// fogSensorMonthly: monthly mean/min/max of one sensor; on the device from the readings it still holds (7 days of 5-min).
func (t chatTools) fogSensorMonthly(args map[string]any, v fogView) (map[string]any, error) {
	node, metric := strArg(args, "node"), strArg(args, "metric")
	if node == "" || metric == "" {
		return nil, errors.New("'node' and 'metric' are required for sensor_monthly")
	}
	var st *SensorState
	var cands []string
	if t.r.eng != nil {
		_, states, _ := t.r.eng.Snapshot()
		for i := range states {
			if states[i].Node == node {
				cands = append(cands, states[i].Metric)
				if states[i].Metric == metric {
					st = &states[i]
				}
			}
		}
	}
	if st == nil {
		e := fmt.Sprintf("unknown sensor %s/%s", node, metric)
		if len(cands) > 0 {
			e += "; this node has " + strings.Join(cands, ", ")
		}
		return nil, errors.New(e)
	}
	a, b, err := t.span(args["time"], true)
	if err != nil {
		return nil, err
	}
	if b.After(t.now) {
		b = t.now
	}
	xs := t.r.eng.HistoryAt(node, metric, t.now.Unix(), 2016)
	type agg struct {
		sum, mn, mx float64
		n           int
		days        map[string]bool
	}
	months := map[string]*agg{}
	var order []string
	first := ""
	for i, x := range xs {
		at := t.now.Add(-time.Duration(len(xs)-1-i) * 5 * time.Minute)
		if first == "" {
			first = fogDate(at)
		}
		if at.Before(a) || !at.Before(b) {
			continue
		}
		k := at.In(IST).Format("2006-01")
		m := months[k]
		if m == nil {
			m = &agg{mn: x, mx: x, days: map[string]bool{}}
			months[k] = m
			order = append(order, k)
		}
		m.sum, m.n = m.sum+x, m.n+1
		m.mn, m.mx = math.Min(m.mn, x), math.Max(m.mx, x)
		m.days[fogDate(at)] = true
	}
	out := []map[string]any{}
	for _, k := range order {
		m := months[k]
		out = append(out, map[string]any{"month": k, "mean": chatRound(metric, m.sum/float64(m.n)), "min": chatRound(metric, m.mn),
			"max": chatRound(metric, m.mx), "days": len(m.days)})
	}
	if first == "" {
		first = fogDate(t.now)
	}
	fd, _ := time.ParseInLocation("2006-01-02", first, IST)
	cov := map[string]any{"from": first, "to": chatTS(b), "complete": v.onFog || !a.Before(fd)}
	if !v.onFog {
		cov["note"] = "fog unreachable: monthly values from the readings still on this device (since " + first + ")"
	}
	return map[string]any{"analysis": "sensor_monthly", "sensor": node + " " + metric, "unit": st.Unit, "months": out, "coverage": cov}, nil
}

var kbStop = func() map[string]bool {
	m := map[string]bool{}
	for _, w := range strings.Fields(`a an the and or of to in on for is are was were be been what whats what's does do did say says said about how we our
with me my find show look up please pls per from at it its this that any there should when which who can could you tell give get
search knowledge base docs doc document documents sop sops manual handbook guideline guidelines i us your have has had
is there kya hai batao`) {
		m[w] = true
	}
	return m
}()

var kbWord = regexp.MustCompile(`[a-z0-9]+`)

func kbTokens(s string) []string {
	var out []string
	for _, w := range kbWord.FindAllString(strings.ToLower(s), -1) {
		if !kbStop[w] && len(w) > 1 {
			out = append(out, w)
		}
	}
	return out
}

// fogTool: ask the fog, else the same query on the device store.
func (t chatTools) fogTool(ctx context.Context, name string, args map[string]any) (map[string]any, error) {
	if res, err := fogC.Call(ctx, name, args); err == nil {
		if _, bad := res["error"]; bad {
			return res, nil
		}
		res["source"] = "fog"
		return res, nil
	}
	res, err := t.runFogQuery(name, args, t.deviceView())
	if err != nil {
		return nil, err
	}
	res["source"], res["fog"] = "device_fallback", "unreachable"
	return res, nil
}

// archivedIncident: get_incident for an incident that is only an index row on the device.
func (t chatTools) archivedIncident(ctx context.Context, args map[string]any, row map[string]any) map[string]any {
	if res, err := fogC.Call(ctx, "get_incident", args); err == nil {
		if _, bad := res["error"]; !bad {
			res["source"] = "fog"
			return res
		}
	}
	row["source"], row["fog"] = "device_fallback", "unreachable"
	row["note"] = fmt.Sprintf("full record archived off the device (it keeps the last %d incidents in full); fog unreachable: index row only, no root cause or checklist", t.deviceView().nFull)
	return row
}

// ---------------------------------------------------------------- local cross-domain tools (device store + index)

func (t chatTools) runLocalR3(name string, args map[string]any) (map[string]any, error) {
	v := t.deviceView()
	switch name {
	case "co_occurring_incidents":
		id := strings.ToUpper(strArg(args, "id"))
		if id == "" {
			return nil, errors.New("'id' is required")
		}
		var x0 *chatInc
		for i := range v.incs {
			if v.incs[i].inc.ID == id {
				x0 = &v.incs[i]
			}
		}
		if x0 == nil {
			return map[string]any{"error": "no incident " + id + " on this device"}, nil
		}
		w := intArg(args, "window_min", 60, 10, 240)
		other := true
		if b, ok := args["other_domains_only"].(bool); ok {
			other = b
		}
		type it struct {
			m   map[string]any
			off int
			id  string
		}
		var items []it
		for _, ci := range v.incs {
			if ci.inc.ID == x0.inc.ID || ci.inc.Injected {
				continue
			}
			d := ci.at.Sub(x0.at).Seconds()
			if math.Abs(d) > float64(w*60) {
				continue
			}
			if other {
				extra := false
				for _, dm := range ci.domains {
					extra = extra || !contains(x0.domains, dm)
				}
				if !extra {
					continue
				}
			}
			m := fogItem(ci, false)
			delete(m, "outcome")
			off := int(math.Floor(d / 60))
			m["offset_min"] = off
			items = append(items, it{m, off, ci.inc.ID})
		}
		sort.Slice(items, func(i, j int) bool {
			ai, aj := items[i].off, items[j].off
			if ai < 0 {
				ai = -ai
			}
			if aj < 0 {
				aj = -aj
			}
			if ai != aj {
				return ai < aj
			}
			return items[i].id < items[j].id
		})
		out := []map[string]any{}
		for i := 0; i < len(items) && i < 8; i++ {
			out = append(out, items[i].m)
		}
		doms := x0.domains
		if doms == nil {
			doms = []string{}
		}
		return map[string]any{"anchor": map[string]any{"id": x0.inc.ID, "time": chatTS(x0.at), "title": x0.inc.Title, "domains": doms},
			"window_min": w, "other_domains_only": other, "total": len(items), "items": out}, nil
	case "recurring_issues":
		a, b, err := t.span(args["time"], true)
		if err != nil {
			return nil, err
		}
		by := strArg(args, "by")
		if by == "" {
			by = "sensor"
		}
		if by != "sensor" && by != "node" {
			return nil, errors.New("by must be sensor|node")
		}
		dom, metric := strArg(args, "domain"), strArg(args, "metric")
		if dom != "" && !contains(chatDomains, dom) {
			return nil, fmt.Errorf("unknown domain %q", dom)
		}
		mc := intArg(args, "min_count", 3, 2, 50)
		type grp struct {
			n, open       int
			first, last   string
			labels, outcs map[string]int
		}
		g := map[string]*grp{}
		var order []string
		for _, ci := range v.incs { // oldest first
			p := ci.inc
			if p.Injected || ci.at.Before(a) || !ci.at.Before(b) {
				continue
			}
			var keys []string
			for _, s := range ci.sensors {
				if (dom != "" && s.Role != dom) || (metric != "" && s.Metric != metric) {
					continue
				}
				k := s.Node
				if by == "sensor" {
					k = s.Node + " " + s.Metric
				}
				if !contains(keys, k) {
					keys = append(keys, k)
				}
			}
			for _, k := range keys {
				e := g[k]
				if e == nil {
					e = &grp{first: chatTS(ci.at), labels: map[string]int{}, outcs: map[string]int{}}
					g[k] = e
					order = append(order, k)
				}
				e.n++
				e.last = chatTS(ci.at)
				l := ci.label
				if l == "" {
					l = "none"
				}
				e.labels[l]++
				if p.Outcome != "" {
					e.outcs[p.Outcome]++
				}
				if wfOf(p) != wfClosed {
					e.open++
				}
			}
		}
		var keys []string
		for _, k := range order {
			if g[k].n >= mc {
				keys = append(keys, k)
			}
		}
		sort.SliceStable(keys, func(i, j int) bool {
			if g[keys[i]].n != g[keys[j]].n {
				return g[keys[i]].n > g[keys[j]].n
			}
			return keys[i] < keys[j]
		})
		items := []map[string]any{}
		for i := 0; i < len(keys) && i < 8; i++ {
			e := g[keys[i]]
			top, tn := "", -1
			for l, n := range e.labels {
				if n > tn || (n == tn && l < top) {
					top, tn = l, n
				}
			}
			oc := map[string]any{}
			for o, n := range e.outcs {
				oc[o] = n
			}
			items = append(items, map[string]any{by: keys[i], "count": e.n, "first": e.first, "last": e.last, "top_label": top, "outcomes": oc, "open": e.open})
		}
		to := b
		if to.After(t.now) {
			to = t.now
		}
		return map[string]any{"by": by, "min_count": mc, "groups": len(keys), "items": items,
			"coverage": map[string]any{"source": "device", "from": fogDate(a), "to": chatTS(to), "complete": true}}, nil
	case "compare_periods":
		if args["period_a"] == nil || args["period_b"] == nil {
			return nil, errors.New("'period_a' and 'period_b' are required")
		}
		res := map[string]any{}
		cnt := map[string]int{}
		for _, key := range []string{"a", "b"} {
			a, b, err := t.span(args["period_"+key], true)
			if err != nil {
				return nil, err
			}
			incs, err := fogFilter(v.incs, args, a, b)
			if err != nil {
				return nil, err
			}
			sev, lab := map[string]int{}, map[string]int{}
			for _, ci := range incs {
				sev[normSeverity(ci.inc.Severity)]++
				l := ci.label
				if l == "" {
					l = "none"
				}
				lab[l]++
			}
			bs := map[string]any{}
			for _, s := range fogSevs {
				if sev[s] > 0 {
					bs[s] = sev[s]
				}
			}
			type kv struct {
				k string
				n int
			}
			var ls []kv
			for k, n := range lab {
				ls = append(ls, kv{k, n})
			}
			sort.Slice(ls, func(i, j int) bool {
				if ls[i].n != ls[j].n {
					return ls[i].n > ls[j].n
				}
				return ls[i].k < ls[j].k
			})
			top := []map[string]any{}
			for i := 0; i < len(ls) && i < 3; i++ {
				top = append(top, map[string]any{"label": ls[i].k, "count": ls[i].n})
			}
			to := b
			if to.After(t.now) {
				to = t.now
			}
			res[key] = map[string]any{"from": chatTS(a), "to": chatTS(to), "count": len(incs), "by_severity": bs, "top_labels": top}
			cnt[key] = len(incs)
		}
		res["b_minus_a"] = cnt["b"] - cnt["a"]
		if cnt["a"] > 0 {
			res["change_pct"] = round1(float64(cnt["b"]-cnt["a"]) / float64(cnt["a"]) * 100)
		} else {
			res["change_pct"] = nil
		}
		return res, nil
	}
	return nil, fmt.Errorf("unknown tool %q", name)
}

// ---------------------------------------------------------------- fog side: serve the same queries over a full store

// FogHandler answers POST /v1/tool and GET /v1/status over this backend's store treated as the fog's full store (every
// incident a full record; kb = the full knowledge base): a fog box (or laptop) running this backend with a large
// SCE_MAX_INCIDENTS, and the tests. Not mounted on the board.
func FogHandler(r *Reasoner, kb []kbPassage) http.Handler {
	return fogHandlerAt(r, kb, func() time.Time { return chatNowOf(r) })
}

// fogHandlerAt: FogHandler with its own clock (a laptop fog serving a board that runs a replay sim clock: fog_serve_test.go).
func fogHandlerAt(r *Reasoner, kb []kbPassage, now func() time.Time) http.Handler {
	mux := http.NewServeMux()
	write := func(w http.ResponseWriter, v any) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(v)
	}
	mux.HandleFunc("/v1/status", func(w http.ResponseWriter, req *http.Request) {
		t := chatTools{r: r, now: now()}
		write(w, map[string]any{"ok": true, "incidents": len(t.incidents())})
	})
	mux.HandleFunc("/v1/tool", func(w http.ResponseWriter, req *http.Request) {
		var q struct {
			Name string         `json:"name"`
			Args map[string]any `json:"args"`
		}
		if req.Method != http.MethodPost || json.NewDecoder(io.LimitReader(req.Body, 1<<16)).Decode(&q) != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if q.Args == nil {
			q.Args = map[string]any{}
		}
		t := chatTools{r: r, now: now()}
		var res map[string]any
		var err error
		if q.Name == "get_incident" {
			res, err = t.fogGetIncident(q.Args)
		} else {
			res, err = t.runFogQuery(q.Name, q.Args, t.fogViewOf(kb))
		}
		if err != nil {
			res = map[string]any{"error": err.Error()}
		}
		write(w, res)
	})
	return mux
}

// fogGetIncident: the full record (the fog never archives).
func (t chatTools) fogGetIncident(args map[string]any) (map[string]any, error) {
	res, err := t.run("get_incident", args)
	if err != nil {
		return nil, err
	}
	delete(res, "query_id")
	delete(res, "_archived")
	return res, nil
}
