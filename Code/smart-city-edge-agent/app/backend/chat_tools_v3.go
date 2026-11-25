package main

import (
	"errors"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Chat tools v3 (proofs/2026-10-29_rsn_v3/TOOLS_V3_CHAT.md): six read-only tools added to the nine rsn_v1 ones.
// The training store (proofs/2026-10-29_rsn_v3/pipeline/tools_v3_impl.py) returns the same JSON for the same data;
// chat_tools_v3_parity_test.go checks both on pipeline/parity_cases.json. The question router (chat_router.go)
// calls them directly for the questions it recognises; the model calls them once it is trained on them.
//
// Shared rules (the Python side implements the same ones):
//   - reading window of a period [a, b): the readings with a <= t < b and t <= now (chatWindow).
//   - live status (chatLiveStatus): sensor_fault when the engine's rules say so or a non-injected incident created in
//     the last 4 h flags the sensor as faulty; otherwise the latest reading against the rule limits (chatLimitStatus).
//   - what_if: see whatIf.

// chatMetricEnum: the metric enum of the chat tool header.
var chatMetricEnum = []string{"co2", "temp", "rh", "pm25", "pm10", "level", "flow", "tds", "ph", "power_kw", "pf", "occ", "wind",
	"room_temp", "setpoint", "ac_on", "ac_units_on"}

const (
	chatFaultWindow  = 4 * time.Hour // the device's 48-reading window
	chatKeepReadings = 2016 + 1      // 7 days of 5-min readings (both ends)
	chatMaxEstimates = 5
	chatOccNote      = "occupancy is a 0/1 presence sensor: values are the occupied fraction of an hour (above 1 = extrapolated)"
)

// chatRound rounds like get_sensor_history: 1 decimal, pf and ph 3.
func chatRound(metric string, x float64) float64 {
	p := 10.0
	if metric == "pf" || metric == "ph" {
		p = 1000
	}
	return math.Round(x*p) / p
}

func chatTS(x time.Time) string { return x.In(IST).Format("2006-01-02 15:04") }

// chatNull: "" as JSON null (the training store's NULL columns).
func chatNull(s string) any {
	if s == "" {
		return nil
	}
	return s
}

// chatLocMatch: the location argument is a case-insensitive substring of the node id, its location text or building.
func chatLocMatch(loc string, s SensorState, building string) bool {
	return loc == "" || strings.Contains(strings.ToLower(s.Node+" "+s.Location+" "+building), strings.ToLower(loc)) || chatLocStructural(loc, s, building)
}

// chatBuilding: the building a node belongs to (sensors.json), "" when unknown. Meta.Nodes is written once in NewEngine.
func (t chatTools) chatBuilding(node string) string {
	if t.r.eng == nil {
		return ""
	}
	return t.r.eng.Meta.Nodes[node].Building
}

// chatWindow: the readings of the period [a, b) that exist by now: the newest bucket end (<= b-1s and <= now) and
// how many readings reach back to a (at most the 7 days the engine keeps).
func (t chatTools) chatWindow(a, b time.Time) (int64, int) {
	last := b.Add(-time.Second)
	if last.After(t.now) {
		last = t.now
	}
	end := last.Unix() / bucketSec * bucketSec
	first := (a.Unix() + bucketSec - 1) / bucketSec * bucketSec
	if end < first {
		return end, 0
	}
	n := int((end-first)/bucketSec) + 1
	if n > chatKeepReadings {
		n = chatKeepReadings
	}
	return end, n
}

// chatReadingCoverage: coverage of a readings answer (the device keeps 7 days of readings).
func (t chatTools) chatReadingCoverage(a, b time.Time) map[string]any {
	keep := t.now.Add(-7 * 24 * time.Hour)
	from := a
	if from.Before(keep) {
		from = keep
	}
	if b.After(t.now) {
		b = t.now
	}
	return map[string]any{"source": "device", "complete": !a.Before(keep), "from": chatTS(from), "to": chatTS(b),
		"note": "device keeps readings from " + keep.In(IST).Format("2006-01-02")}
}

// chatLimitStatus: one reading against the rule limits (features.go Metrics; rules.go StatusOf's limit branch):
// high-side metrics warning >= Warn, critical >= Crit; low-side (pf) warning < Warn, critical < Crit; pH both sides
// (warning < 6.5 or >= 8.5, critical < 6.0 or >= 9.0). Metrics without limits are normal.
func chatLimitStatus(role, metric string, v float64) string {
	m, ok := Metrics[role+"/"+metric]
	if !ok || !m.HasLimits {
		return "normal"
	}
	switch {
	case metric == "ph":
		if v < 6.0 || v >= m.Crit {
			return "critical"
		}
		if v < 6.5 || v >= m.Warn {
			return "warning"
		}
	case m.Dir == "low":
		if v < m.Crit {
			return "critical"
		}
		if v < m.Warn {
			return "warning"
		}
	default:
		if v >= m.Crit {
			return "critical"
		}
		if v >= m.Warn {
			return "warning"
		}
	}
	return "normal"
}

// chatFaultsNow: sensors a non-injected incident created in the last 4 h flags as faulty (its severity or the
// sensor's status sensor_fault) -> the earliest such incident time.
func (t chatTools) chatFaultsNow(incs []chatInc) map[string]time.Time {
	out := map[string]time.Time{}
	from := t.now.Add(-chatFaultWindow)
	for _, ci := range incs {
		if ci.inc.Injected || ci.at.Before(from) || ci.at.After(t.now) {
			continue
		}
		for _, s := range ci.sensors {
			if normSeverity(ci.inc.Severity) == "sensor_fault" || ci.status[s.Ref] == "sensor_fault" {
				k := key(s.Node, s.Metric)
				if old, ok := out[k]; !ok || ci.at.Before(old) {
					out[k] = ci.at
				}
			}
		}
	}
	return out
}

// chatLiveStatus: the status the chat tools report for a sensor now (see the file comment).
func chatLiveStatus(s SensorState, faults map[string]time.Time) string {
	if _, ok := faults[key(s.Node, s.Metric)]; ok || normSeverity(s.Status) == "sensor_fault" {
		return "sensor_fault"
	}
	if s.Last == nil {
		return "no_data"
	}
	return chatLimitStatus(s.Role, s.Metric, *s.Last)
}

func (t chatTools) runV3(name string, args map[string]any) (map[string]any, error) {
	if t.r.eng == nil && name != "recent_incidents" && name != "open_incidents" && name != "faulty_sensors" {
		return nil, errors.New("no sensor engine on this device")
	}
	switch name {
	case "rank_readings":
		return t.rankReadings(args)
	case "current_levels":
		return t.currentLevels(args)
	case "recent_incidents":
		return t.recentIncidents(args)
	case "open_incidents":
		return t.openIncidents(args)
	case "faulty_sensors":
		return t.faultySensors(args)
	case "what_if":
		return t.whatIf(args)
	}
	return nil, fmt.Errorf("unknown tool %q", name)
}

// checkDomMetric validates the optional domain / metric enums.
func checkDomMetric(dom, metric string) error {
	if dom != "" && !contains(chatDomains, dom) {
		return fmt.Errorf("unknown domain %q", dom)
	}
	if metric != "" && !contains(chatMetricEnum, metric) {
		return fmt.Errorf("unknown metric %q", metric)
	}
	return nil
}

// ---------------------------------------------------------------- 1. rank_readings

// rankReadings: each sensor's own extreme of the metric in the period (its first occurrence), sorted by value (ties
// node+metric); "sensors" = sensors compared (after include_faulty).
func (t chatTools) rankReadings(args map[string]any) (map[string]any, error) {
	metric, dom, loc := strArg(args, "metric"), strArg(args, "domain"), strArg(args, "location")
	if metric == "" {
		return nil, errors.New("'metric' is required")
	}
	if err := checkDomMetric(dom, metric); err != nil {
		return nil, err
	}
	order := strArg(args, "order")
	if order == "" {
		order = "highest"
	}
	if order != "highest" && order != "lowest" {
		return nil, errors.New("order must be highest|lowest")
	}
	low := order == "lowest"
	limit := 3
	if f, ok := args["limit"].(float64); ok {
		limit = int(math.Max(1, math.Min(5, f)))
	}
	withFaulty := true
	if v, ok := args["include_faulty"].(bool); ok {
		withFaulty = v
	}
	tv := args["time"]
	if tv == nil {
		tv = map[string]any{"preset": "today"}
	}
	a, b, err := t.span(tv, true)
	if err != nil {
		return nil, err
	}
	end, n := t.chatWindow(a, b)
	incs := t.incidents()
	faults := t.chatFaultsNow(incs)
	// sensors with a sensor_fault incident in the period (the incident's severity, or the sensor's own status in it)
	faultyInc := map[string]bool{}
	for _, ci := range incs {
		if ci.at.Before(a) || !ci.at.Before(b) || ci.inc.Injected {
			continue
		}
		for _, s := range ci.sensors {
			if normSeverity(ci.inc.Severity) == "sensor_fault" || ci.status[s.Ref] == "sensor_fault" {
				faultyInc[key(s.Node, s.Metric)] = true
			}
		}
	}
	type hit struct {
		s      SensorState
		val    float64
		at     int64
		fault  bool
		status string
	}
	var hits []hit
	_, states, _ := t.r.eng.Snapshot()
	matched := false
	for _, s := range states {
		if s.Metric != metric || s.Injected || (dom != "" && s.Role != dom) || !chatLocMatch(loc, s, t.chatBuilding(s.Node)) {
			continue
		}
		matched = true
		if n <= 0 {
			continue
		}
		xs := t.r.eng.HistoryAt(s.Node, s.Metric, end, n)
		if len(xs) == 0 {
			continue
		}
		k := 0
		for i, x := range xs {
			if (low && x < xs[k]) || (!low && x > xs[k]) {
				k = i
			}
		}
		st := chatLiveStatus(s, faults)
		fault := st == "sensor_fault" || faultyInc[key(s.Node, s.Metric)]
		if fault && !withFaulty {
			continue
		}
		hits = append(hits, hit{s, xs[k], end - int64(len(xs)-1-k)*bucketSec, fault, st})
	}
	if !matched {
		if loc != "" {
			return nil, fmt.Errorf("no %s sensor matching %q", metric, loc)
		}
		return nil, fmt.Errorf("no %s sensor", metric)
	}
	sort.SliceStable(hits, func(i, j int) bool {
		if hits[i].val != hits[j].val {
			return (low && hits[i].val < hits[j].val) || (!low && hits[i].val > hits[j].val)
		}
		return hits[i].s.Node+hits[i].s.Metric < hits[j].s.Node+hits[j].s.Metric
	})
	items := []map[string]any{}
	for _, h := range hits[:min(limit, len(hits))] {
		items = append(items, map[string]any{"node": h.s.Node, "location": h.s.Location, "value": chatRound(metric, h.val), "unit": h.s.Unit,
			"at": chatTS(time.Unix(h.at, 0)), "status": h.status, "faulty_suspect": h.fault})
	}
	return map[string]any{"metric": metric, "order": order, "items": items, "sensors": len(hits), "coverage": t.chatReadingCoverage(a, b)}, nil
}

// ---------------------------------------------------------------- 2. current_levels

// chatLimit: the rule thresholds the device alerts on (features.go Metrics), nil when the metric has none. pf alerts
// below its limits ("alert": "below"); pH also alerts below 6.5 / 6.0 (rules.go StatusOf).
func chatLimit(role, metric string) any {
	m, ok := Metrics[role+"/"+metric]
	if !ok || !m.HasLimits {
		return nil
	}
	o := map[string]any{"warning": m.Warn, "critical": m.Crit}
	if m.Dir == "low" {
		o["alert"] = "below"
	}
	if metric == "ph" {
		o["low_warning"], o["low_critical"] = 6.5, 6.0
	}
	return o
}

func (t chatTools) currentLevels(args map[string]any) (map[string]any, error) {
	metric, dom, loc := strArg(args, "metric"), strArg(args, "domain"), strArg(args, "location")
	if metric == "" && dom == "" && loc == "" {
		return nil, errors.New("give at least one of 'metric', 'domain', 'location'")
	}
	if err := checkDomMetric(dom, metric); err != nil {
		return nil, err
	}
	a, b, _ := t.span(map[string]any{"preset": "today"}, true)
	end, n := t.chatWindow(a, b)
	faults := t.chatFaultsNow(t.incidents())
	items := []map[string]any{}
	count := 0
	_, states, _ := t.r.eng.Snapshot()
	for _, s := range states {
		if s.Injected || (metric != "" && s.Metric != metric) || (dom != "" && s.Role != dom) || !chatLocMatch(loc, s, t.chatBuilding(s.Node)) {
			continue
		}
		count++
		if len(items) >= 20 {
			continue
		}
		var last, today any
		if s.Last != nil {
			last = chatRound(s.Metric, *s.Last)
		}
		if n > 0 {
			if xs := t.r.eng.HistoryAt(s.Node, s.Metric, end, n); len(xs) > 0 {
				mn, mx, sum := xs[0], xs[0], 0.0
				for _, x := range xs {
					mn, mx, sum = math.Min(mn, x), math.Max(mx, x), sum+x
				}
				today = map[string]any{"min": chatRound(s.Metric, mn), "max": chatRound(s.Metric, mx), "mean": chatRound(s.Metric, sum/float64(len(xs)))}
				if last == nil {
					last = chatRound(s.Metric, xs[len(xs)-1]) // newest stored reading (the live value is set at the next poll)
				}
			}
		}
		items = append(items, map[string]any{"node": s.Node, "metric": s.Metric, "location": s.Location, "last": last, "unit": s.Unit,
			"status": chatLiveStatus(s, faults), "today": today, "limit": chatLimit(s.Role, s.Metric)})
	}
	if count == 0 {
		return nil, fmt.Errorf("no sensor matches metric=%s domain=%s location=%s", metric, dom, loc)
	}
	res := map[string]any{"items": items, "count": count, "coverage": t.chatReadingCoverage(a, b)}
	if count > 20 {
		res["note"] = "first 20 shown"
	}
	return res, nil
}

// ---------------------------------------------------------------- 3. recent_incidents

func (t chatTools) recentIncidents(args map[string]any) (map[string]any, error) {
	if err := checkDomMetric(strArg(args, "domain"), strArg(args, "metric")); err != nil {
		return nil, err
	}
	limit := 5
	if f, ok := args["limit"].(float64); ok {
		limit = int(math.Max(1, math.Min(10, f)))
	}
	// any day: the filter's "all" period; severity/domain/metric as find_incidents
	incs, a, b, err := t.filter(map[string]any{"domain": args["domain"], "metric": args["metric"], "severity": args["severity"]}, false)
	if err != nil {
		return nil, err
	}
	// newest = raised last (the incident id order); the sim clock can jump between replay days, so sim time
	// put old incidents first (board 2026-10-29: "latest" listed INC-0178 above INC-0490)
	sort.SliceStable(incs, func(i, j int) bool { return chatIncSeq(incs[i].inc.ID) > chatIncSeq(incs[j].inc.ID) })
	items := []map[string]any{}
	for _, ci := range incs[:min(limit, len(incs))] {
		items = append(items, map[string]any{"id": ci.inc.ID, "time": chatTS(ci.at), "title": ci.inc.Title, "severity": normSeverity(ci.inc.Severity),
			"label": chatNull(ci.label), "domains": ci.domains, "approval": ci.inc.Approval, "outcome": chatNull(ci.inc.Outcome)})
	}
	return map[string]any{"items": items, "total": len(incs), "coverage": chatCoverage(a, b, t.now)}, nil
}

// ---------------------------------------------------------------- 4. open_incidents

var chatSevOrder = map[string]int{"critical": 0, "sensor_fault": 1, "warning": 2, "normal": 3}

// openIncidents: per domain, incidents waiting for an operator decision (workflow needs_decision) and those the AI is
// still analysing; domains with neither are left out (unless asked for), busiest first. Demo injections are left out,
// as in domain_health. total_pending_review counts each incident once (an incident can involve several domains);
// top_pending = up to 3 pending incidents, worst severity first, then oldest.
func (t chatTools) openIncidents(args map[string]any) (map[string]any, error) {
	want := strArg(args, "domain")
	if err := checkDomMetric(want, ""); err != nil {
		return nil, err
	}
	incs := t.incidents()
	sort.SliceStable(incs, func(i, j int) bool {
		if !incs[i].at.Equal(incs[j].at) {
			return incs[i].at.Before(incs[j].at)
		}
		return incs[i].inc.ID < incs[j].inc.ID
	})
	out := []map[string]any{}
	pending := map[string]chatInc{}
	for _, d := range chatDomains {
		if want != "" && d != want {
			continue
		}
		npend, analysing := 0, 0
		bySev := map[string]int{}
		var oldest any
		for _, ci := range incs {
			if ci.inc.Injected || !contains(ci.domains, d) {
				continue
			}
			switch wfOf(ci.inc) {
			case wfAnalysing:
				analysing++
			case wfNeeds:
				npend++
				if _, ok := pending[ci.inc.ID]; !ok {
					pending[ci.inc.ID] = ci
				}
				if s := normSeverity(ci.inc.Severity); s != "" {
					bySev[s]++
				}
				if oldest == nil {
					oldest = chatTS(ci.at)
				}
			}
		}
		if npend == 0 && analysing == 0 && want == "" {
			continue
		}
		out = append(out, map[string]any{"domain": d, "pending_review": npend, "analysing": analysing, "by_severity": bySev, "oldest_pending": oldest})
	}
	sort.SliceStable(out, func(i, j int) bool {
		pi, pj := out[i]["pending_review"].(int), out[j]["pending_review"].(int)
		if pi != pj {
			return pi > pj
		}
		return out[i]["domain"].(string) < out[j]["domain"].(string)
	})
	list := make([]chatInc, 0, len(pending))
	for _, ci := range pending {
		list = append(list, ci)
	}
	sort.Slice(list, func(i, j int) bool {
		si, sj := chatSevOrder[normSeverity(list[i].inc.Severity)], chatSevOrder[normSeverity(list[j].inc.Severity)]
		if si != sj {
			return si < sj
		}
		if !list[i].at.Equal(list[j].at) {
			return list[i].at.Before(list[j].at)
		}
		return list[i].inc.ID < list[j].inc.ID
	})
	top := []map[string]any{}
	for _, ci := range list[:min(3, len(list))] {
		d := want
		if d == "" && len(ci.domains) > 0 {
			d = ci.domains[0]
		}
		top = append(top, map[string]any{"id": ci.inc.ID, "severity": normSeverity(ci.inc.Severity), "title": ci.inc.Title, "domain": d})
	}
	a, b, _ := t.span(nil, false)
	return map[string]any{"domains": out, "total_pending_review": len(pending), "top_pending": top,
		"definition": "pending_review = approval pending (no operator decision yet); analysing = AI still running",
		"coverage":   chatCoverage(a, b, t.now)}, nil
}

// ---------------------------------------------------------------- 5. faulty_sensors

func (t chatTools) faultySensors(args map[string]any) (map[string]any, error) {
	tv := args["time"]
	if tv == nil {
		tv = map[string]any{"preset": "last_7d"}
	}
	a, b, err := t.span(tv, true)
	if err != nil {
		return nil, err
	}
	incs := t.incidents()
	faults := t.chatFaultsNow(incs)
	distinct := map[string]bool{}
	live := []map[string]any{}
	locOf := map[string]string{}
	if t.r.eng != nil {
		sim, states, _ := t.r.eng.Snapshot()
		for _, s := range states {
			locOf[s.Node] = s.Location
			if s.Injected || chatLiveStatus(s, faults) != "sensor_fault" {
				continue
			}
			// since: the first faulty incident in the window, or (engine rules) the start of the abnormal run
			since, ok := faults[key(s.Node, s.Metric)]
			if normSeverity(s.Status) == "sensor_fault" {
				run := time.Unix(sim-int64(maxi(s.AbnormalFor-1, 0))*bucketSec, 0)
				if !ok || run.Before(since) {
					since = run
				}
			}
			live = append(live, map[string]any{"node": s.Node, "metric": s.Metric, "location": s.Location, "status": "sensor_fault",
				"since": chatTS(since)})
			distinct[key(s.Node, s.Metric)] = true
		}
	}
	type agg struct {
		node, metric, loc, fault string
		n                        int
		last                     time.Time
	}
	byKey := map[string]*agg{}
	for _, ci := range incs {
		if ci.at.Before(a) || !ci.at.Before(b) || ci.inc.Injected {
			continue
		}
		for _, s := range ci.sensors {
			if ci.status[s.Ref] != "sensor_fault" {
				continue
			}
			k := key(s.Node, s.Metric)
			g := byKey[k]
			if g == nil {
				loc := s.Location
				if loc == "" {
					loc = locOf[s.Node]
				}
				g = &agg{node: s.Node, metric: s.Metric, loc: loc}
				byKey[k] = g
			}
			g.n++
			if !ci.at.Before(g.last) {
				g.last = ci.at
				if f := ci.faults[s.Ref]; f != "" {
					g.fault = f
				}
			}
			distinct[k] = true
		}
	}
	list := make([]*agg, 0, len(byKey))
	for _, g := range byKey {
		list = append(list, g)
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].n != list[j].n {
			return list[i].n > list[j].n
		}
		return list[i].node+list[i].metric < list[j].node+list[j].metric
	})
	ai := []map[string]any{}
	for _, g := range list[:min(10, len(list))] {
		ai = append(ai, map[string]any{"node": g.node, "metric": g.metric, "location": g.loc, "incidents": g.n, "last": chatTS(g.last), "fault_kind": chatNull(g.fault)})
	}
	return map[string]any{"live": live, "ai_diagnosed": ai, "count_distinct": len(distinct), "coverage": chatCoverage(a, b, t.now)}, nil
}

// ---------------------------------------------------------------- 6. what_if

const (
	whatIfMinHours = 24  // hours where driver and target both have a mean
	whatIfMinR2    = 0.2 // weaker fits are listed under no_clear_link
)

// chatHourly: hourly means (IST hours) of a sensor's readings in the window ending at end; an hour needs 6 of its 12.
func (t chatTools) chatHourly(node, metric string, end int64, n int) map[int64]float64 {
	out := map[int64]float64{}
	if n <= 0 {
		return out
	}
	xs := t.r.eng.HistoryAt(node, metric, end, n)
	sum, cnt := map[int64]float64{}, map[int64]int{}
	for i, x := range xs {
		h := (end - int64(len(xs)-1-i)*bucketSec + 19800) / 3600
		sum[h] += x
		cnt[h]++
	}
	for h, c := range cnt {
		if c >= 6 {
			out[h] = sum[h] / float64(c)
		}
	}
	return out
}

// chatFit: least squares y = a + b*x over the hours both series have; slope, r2, hours.
func chatFit(xs, ys map[int64]float64) (slope, r2 float64, n int) {
	var hs []int64
	for h := range xs {
		if _, ok := ys[h]; ok {
			hs = append(hs, h)
		}
	}
	n = len(hs)
	if n < 3 {
		return 0, 0, n
	}
	var mx, my float64
	for _, h := range hs {
		mx, my = mx+xs[h], my+ys[h]
	}
	mx, my = mx/float64(n), my/float64(n)
	var sxx, sxy, syy float64
	for _, h := range hs {
		dx, dy := xs[h]-mx, ys[h]-my
		sxx, sxy, syy = sxx+dx*dx, sxy+dx*dy, syy+dy*dy
	}
	if sxx < 1e-12 || syy < 1e-12 {
		return 0, 0, n // a constant driver or target says nothing about a link
	}
	slope = sxy / sxx
	return slope, sxy * sxy / (sxx * syy), n
}

// whatIf: data-fitted effect of changing one metric on the other readings of the same building.
//   - driver sensors = every sensor of the driver metric matching location (node, location text or building), grouped
//     by building; per building the driver series is the mean of its sensors' hourly means; with several buildings
//     the one with the most linked targets is used (ties: alphabetical).
//   - driver_now = mean of the driver sensors' latest readings; a percent change on a driver that is ~0 now (<= 10% of
//     its mean over the hours it was above 0) is applied to that typical in-use level (driver_basis says so).
//   - driver_after is floored at the metric's physical minimum, never capped (occupancy is the hourly occupied
//     fraction of a 0/1 presence sensor: above 1 means busier than a fully occupied hour, an extrapolation).
//   - targets: every other-metric sensor of the building; linked = >= 24 common hours, r2 >= 0.2 and a latest reading;
//     after = latest + slope*delta, clamped to the metric's physical range; at most 5 estimates, best r2 first;
//     no_clear_link = the (sorted) metrics without any link; location = the building that was fitted.
func (t chatTools) whatIf(args map[string]any) (map[string]any, error) {
	driver, loc := strArg(args, "driver"), strArg(args, "location")
	if driver == "" {
		return nil, errors.New("'driver' is required")
	}
	if err := checkDomMetric("", driver); err != nil {
		return nil, err
	}
	pct, hasPct := args["change_pct"].(float64)
	abs, hasAbs := args["change_abs"].(float64)
	if !hasPct && !hasAbs {
		return nil, errors.New("'change_pct' or 'change_abs' is required")
	}
	tv := args["time"]
	if tv == nil {
		tv = map[string]any{"preset": "last_7d"}
	}
	a, b, err := t.span(tv, true)
	if err != nil {
		return nil, err
	}
	end, n := t.chatWindow(a, b)
	_, states, _ := t.r.eng.Snapshot()
	var buildings []string
	drivers := map[string][]SensorState{}
	for _, s := range states {
		bl := t.chatBuilding(s.Node)
		if s.Metric != driver || s.Injected || !chatLocMatch(loc, s, bl) {
			continue
		}
		if drivers[bl] == nil {
			buildings = append(buildings, bl)
		}
		drivers[bl] = append(drivers[bl], s)
	}
	if len(buildings) == 0 {
		e := "no " + driver + " sensor on this device"
		if loc != "" {
			e = "no " + driver + " sensor at " + loc
		}
		return nil, errors.New(e)
	}
	sort.Strings(buildings)
	type est struct {
		m      map[string]any
		r2     float64
		metric string
		k      string
		linked bool
	}
	type outcome struct {
		building, unit string
		now, after     float64
		typical        bool // now = typical in-use level, not the current reading
		ests           []est
		linked         int
	}
	fit := func(bl string) outcome {
		o := outcome{building: bl}
		// driver: mean of the building's driver sensors, hour by hour and now
		hs := map[int64][]float64{}
		var nows []float64
		role := ""
		for _, s := range drivers[bl] {
			if o.unit == "" {
				o.unit, role = s.Unit, s.Role
			}
			for h, v := range t.chatHourly(s.Node, s.Metric, end, n) {
				hs[h] = append(hs[h], v)
			}
			if s.Last != nil {
				nows = append(nows, *s.Last)
			}
		}
		dx := map[int64]float64{}
		var lastH int64
		for h, vs := range hs {
			sum := 0.0
			for _, v := range vs {
				sum += v
			}
			dx[h] = sum / float64(len(vs))
			if h > lastH {
				lastH = h
			}
		}
		if len(nows) > 0 {
			sum := 0.0
			for _, v := range nows {
				sum += v
			}
			o.now = sum / float64(len(nows))
		} else {
			o.now = dx[lastH]
		}
		// a percent change of a driver that is ~0 right now (an empty building at night) says nothing: apply it to the
		// typical in-use level instead (mean of the hours where the driver was above zero)
		var inUse, nUse float64
		for _, v := range dx {
			if v > 0 {
				inUse, nUse = inUse+v, nUse+1
			}
		}
		if hasPct && nUse > 0 && o.now <= 0.1*inUse/nUse {
			o.now, o.typical = inUse/nUse, true
		}
		delta := abs
		if hasPct {
			delta = o.now * pct / 100
		}
		o.after = o.now + delta
		if m, ok := Metrics[role+"/"+driver]; ok && m.Hi > m.Lo {
			o.after = math.Max(m.Lo, o.after) // floored, not capped (see above)
		}
		delta = o.after - o.now
		for _, s := range states {
			if s.Metric == driver || s.Injected || t.chatBuilding(s.Node) != bl {
				continue
			}
			slope, r2, hours := chatFit(dx, t.chatHourly(s.Node, s.Metric, end, n))
			e := est{r2: r2, metric: s.Metric, k: s.Node + s.Metric, linked: hours >= whatIfMinHours && r2 >= whatIfMinR2 && s.Last != nil}
			if e.linked {
				now := *s.Last
				after := now + slope*delta
				if m, ok := Metrics[s.Role+"/"+s.Metric]; ok && m.Hi > m.Lo {
					after = math.Max(m.Lo, math.Min(m.Hi, after)) // a physically possible reading
				}
				e.m = map[string]any{"metric": s.Metric, "node": s.Node, "now": chatRound(s.Metric, now), "after": chatRound(s.Metric, after),
					"unit": s.Unit, "slope": math.Round(slope*1000) / 1000, "r2": math.Round(r2*100) / 100, "hours": hours}
				o.linked++
			}
			o.ests = append(o.ests, e)
		}
		return o
	}
	// no location given and the driver is measured in several buildings: the building where it links to most readings
	best := fit(buildings[0])
	for _, bl := range buildings[1:] {
		if o := fit(bl); o.linked > best.linked {
			best = o
		}
	}
	estimates := []map[string]any{}
	linkedMetric := map[string]bool{}
	sort.SliceStable(best.ests, func(i, j int) bool {
		if best.ests[i].r2 != best.ests[j].r2 {
			return best.ests[i].r2 > best.ests[j].r2
		}
		return best.ests[i].k < best.ests[j].k
	})
	for _, e := range best.ests {
		if e.linked {
			if len(estimates) < chatMaxEstimates {
				estimates = append(estimates, e.m)
			}
			linkedMetric[e.metric] = true
		}
	}
	noLink := []string{}
	for _, e := range best.ests {
		if !e.linked && !linkedMetric[e.metric] && !contains(noLink, e.metric) {
			noLink = append(noLink, e.metric)
		}
	}
	sort.Strings(noLink)
	change := fmt.Sprintf("%+g%%", pct)
	if !hasPct {
		change = strings.TrimSpace(fmt.Sprintf("%+g %s", abs, best.unit))
	}
	basis := "current reading"
	if best.typical {
		basis = "typical in-use level (the current reading is about zero)"
	}
	res := map[string]any{"driver": driver, "change": change, "driver_now": chatRound(driver, best.now), "driver_after": chatRound(driver, best.after),
		"driver_basis": basis, "unit": best.unit, "location": best.building, "estimates": estimates, "no_clear_link": noLink,
		"method":   "linear fit of hourly means over the window; association, not a controlled experiment",
		"coverage": t.chatReadingCoverage(a, b)}
	if driver == "occ" {
		res["note"] = chatOccNote
	}
	return res, nil
}

// chatIncSeq: the sequence number of an incident id ("INC-0490" -> 490; 0 when not of that form).
func chatIncSeq(id string) int {
	n, _ := strconv.Atoi(strings.TrimPrefix(id, "INC-"))
	return n
}
