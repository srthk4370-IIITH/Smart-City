package main

import (
	"encoding/json"
	"fmt"
	"log"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Chat polish (2026-11-20, hands-on audit proofs/2026-11-19_prod_audit/HANDS_ON.md C1-C9 and F3/F4; decisions in
// proofs/POLISH.md "Chat: BOTH, router first"). Template lookups stay templated; open questions go to the reasoner with
// the template facts as context; every answer is trimmed to the asked format and written in plain words.

// ---------------------------------------------------------------- 1. sensor lookup by place words

var (
	chatLocBLRe      = regexp.MustCompile(`(?i)^\s*(?:the\s+)?([a-z]{2,3})\s*-?\s*(?:building|bldg|block)?\s*-?\s*(?:level|floor|lvl|l)?\s*-?\s*0*(\d{1,2})\s*$`)
	chatLocLBRe      = regexp.MustCompile(`(?i)^\s*(?:the\s+)?(?:level|floor|lvl)\s*-?\s*0*(\d{1,2})\s+(?:of|in|at)?\s*(?:the\s+)?([a-z]{2,3})(?:\s*(?:building|bldg|block))?\s*$`)
	chatLocLvlOnlyRe = regexp.MustCompile(`(?i)^\s*(?:level|floor|lvl)\s*-?\s*0*(\d{1,2})\s*$`)
	chatLocLvlRe     = regexp.MustCompile(`(?i)\blevel\s+0*(\d{1,2})\b`)
	chatNodeLvRe     = regexp.MustCompile(`-[A-Z]{2}(\d{2})(?:-|$)`)
)

// chatLocStructural: "KH level 03", "KH 03", "KH03", "level 3 of KH": building + level, compared with the node (its id
// carries the building and level as KH03, its location text as "level 03").
func chatLocStructural(loc string, s SensorState, building string) bool {
	var b string
	var lv int
	if m := chatLocLvlOnlyRe.FindStringSubmatch(loc); m != nil {
		lv, _ = strconv.Atoi(m[1])
		if m := chatLocLvlRe.FindStringSubmatch(s.Location); m != nil {
			n, _ := strconv.Atoi(m[1])
			return n == lv
		}
		return false
	}
	if m := chatLocBLRe.FindStringSubmatch(loc); m != nil {
		b = strings.ToUpper(m[1])
		lv, _ = strconv.Atoi(m[2])
	} else if m := chatLocLBRe.FindStringSubmatch(loc); m != nil {
		b = strings.ToUpper(m[2])
		lv, _ = strconv.Atoi(m[1])
	} else {
		return false
	}
	if strings.ToUpper(building) != b && !strings.Contains(strings.ToUpper(s.Node), b) {
		return false
	}
	if m := chatLocLvlRe.FindStringSubmatch(s.Location); m != nil {
		n, _ := strconv.Atoi(m[1])
		return n == lv
	}
	if m := chatNodeLvRe.FindStringSubmatch(strings.ToUpper(s.Node)); m != nil {
		n, _ := strconv.Atoi(m[1])
		return n == lv
	}
	return false
}

// ---------------------------------------------------------------- 3. sensors not sending data

var (
	chatNotSendRe = regexp.MustCompile(`(?i)\b(not|no\s+longer|stopped|isn'?t|aren'?t|stop|never)\s+(sending|reporting|responding|transmitting|giving|updating|publishing)\b|` +
		`\b(silent|stale|offline|dead|missing)\s+(sensors?|data|feeds?)\b|\bsensors?\b[^.?!]*\b(offline|silent|stale|no\s+data|not\s+(sending|reporting|responding))\b|` +
		`\bno\s+(new\s+)?data\b|\bwhich\b[^.?!]*\bsensors?\b[^.?!]*\b(silent|stale|offline)\b`)
	chatWhichRe = regexp.MustCompile(`(?i)\b(which|what|list|any|how\s+many|are\s+there|show)\b`)
)

type chatHealthRow struct {
	Node, Metric, Location string
	State                  string // fresh | stale | missing
	AgeS                   int64
}

// chatHealthRows: the data-health states of the /api/health/data panel (phase1.go dataHealth): a sensor is stale when
// its newest reading is older than staleS, missing when it never reported (engine "stale" data quality counts as stale).
func chatHealthRows(states []SensorState, seen map[string]int64, now, staleS int64, hasCampus bool) []chatHealthRow {
	var out []chatHealthRow
	for _, st := range states {
		if st.Injected {
			continue
		}
		row := chatHealthRow{Node: st.Node, Metric: st.Metric, Location: st.Location, State: "missing"}
		ts := seen[key(st.Node, st.Metric)]
		if ts > 0 {
			row.AgeS = now - ts
			row.State = "fresh"
			if now-ts > staleS {
				row.State = "stale"
			}
		} else if st.Updated > 0 { // MQTT / ingest / sliders, also while a configured campus API is down
			row.State, row.AgeS = "fresh", now-st.Updated
			if now-st.Updated > staleS {
				row.State = "stale"
			}
		}
		if row.State == "fresh" && st.Quality == "stale" {
			row.State = "stale"
			if st.Updated > 0 {
				row.AgeS = now - st.Updated
			}
		}
		out = append(out, row)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Node+out[i].Metric < out[j].Node+out[j].Metric })
	return out
}

func chatAgeS(s int64) string {
	switch {
	case s < 3600:
		return fmt.Sprintf("%d min", max(1, int(s/60)))
	case s < 48*3600:
		return fmt.Sprintf("%.1f h", float64(s)/3600)
	}
	return fmt.Sprintf("%.1f days", float64(s)/86400)
}

// chatNotSending: "which sensors are not sending data right now?" from the data-health source.
func (t chatTools) chatNotSending(place chatPlace, metrics []string, nodes map[string]NodeInfo) chatV25 {
	_, states, _ := t.r.eng.Snapshot()
	var seen map[string]int64
	if campus != nil {
		seen = campus.SensorAt()
	}
	staleS := int64(profInt("health_stale_min", 30, 5, 1440)) * 60
	rows := chatHealthRows(states, seen, nowTime().Unix(), staleS, campus != nil)
	if place.Words || len(metrics) > 0 {
		picks, _ := chatPickSensors(place, metrics, "", nodes)
		keep := map[string]bool{}
		for _, p := range picks {
			keep[p.Node+"|"+p.Metric] = true
		}
		if len(picks) > 0 {
			var f []chatHealthRow
			for _, r := range rows {
				if keep[r.Node+"|"+r.Metric] {
					f = append(f, r)
				}
			}
			rows = f
		}
	}
	return t.chatSayNotSending(rows, staleS)
}

func (t chatTools) chatSayNotSending(rows []chatHealthRow, staleS int64) chatV25 {
	var stale, missing []string
	for _, r := range rows {
		name := fmt.Sprintf("%s %s", chatMetricName(r.Metric), r.Node)
		switch r.State {
		case "stale":
			stale = append(stale, fmt.Sprintf("%s (last data %s ago)", name, chatAgeS(r.AgeS)))
		case "missing":
			missing = append(missing, name)
		}
	}
	list := func(xs []string) string {
		if len(xs) > 6 {
			return strings.Join(xs[:6], ", ") + fmt.Sprintf(" and %d more", len(xs)-6)
		}
		return strings.Join(xs, ", ")
	}
	var parts []string
	if len(stale) > 0 {
		// the per-sensor "last data N min ago" uses the reading time, which can be under the stale limit
		// (2026-11-20 hands-on: "over 30 minutes ... 27 min ago"), so no fixed number in the lead
		parts = append(parts, fmt.Sprintf("%s stopped sending new data: %s",
			plural(len(stale), "sensor has", "sensors have"), list(stale)))
	}
	if len(missing) > 0 {
		parts = append(parts, fmt.Sprintf("%s never reported since this device started: %s", plural(len(missing), "sensor has", "sensors have"), list(missing)))
	}
	text := ""
	if len(parts) == 0 {
		text = fmt.Sprintf("Every one of the %d sensors checked has sent data within the last %d minutes.", len(rows), staleS/60)
	} else {
		text = strings.ToUpper(parts[0][:1]) + parts[0][1:] + "."
		for _, p := range parts[1:] {
			text += " " + strings.ToUpper(p[:1]) + p[1:] + "."
		}
		text += " Their last values may be out of date."
	}
	res := map[string]any{"stale": len(stale), "missing": len(missing), "checked": len(rows), "stale_after_min": staleS / 60}
	return chatV25{text, []ChatTool{chatToolRec("data_health", map[string]any{}, res)}}
}

// ---------------------------------------------------------------- 4. forecast: when will a reading cross a value

var (
	chatForecastRe = regexp.MustCompile(`(?i)\bwhen\s+(will|would|does|do|is)\b[^.?!]*\b(cross|reach|hit|exceed|pass|go\s+(above|over|below|under)|drop\s+below|fall\s+below|get\s+to|touch)\b|` +
		`\b(keeps?|continues?)\s+(rising|increasing|climbing|falling|dropping|going\s+up|going\s+down)\b|\bhow\s+(long|soon)\s+(until|before|till)\b|\bat\s+this\s+rate\b`)
	chatFallWordRe = regexp.MustCompile(`(?i)\b(below|under|drop|dropping|fall|falling|fell|less|lower|decreas\w*)\b`)
	chatTargetRe   = regexp.MustCompile(`(?i)(?:cross|reach|hit|exceed|pass|above|over|below|under|to|until|till|before)\s+(\d+(?:\.\d+)?)\s*(ppm|µg/m³|ug/m3|%|°\s*c|c\b|kw|ph|m3|kl|l\b)?|(\d+(?:\.\d+)?)\s*(ppm|µg/m³|ug/m3|%|°\s*c|kw)`)
)

// chatForecast: a straight-line estimate from the last 2 hours (chatFit, the least-squares fit of the what_if tool).
func (t chatTools) chatForecast(q string, ref *chatRef, place chatPlace, metrics []string, nodes map[string]NodeInfo) (chatV25, bool) {
	m := chatTargetRe.FindStringSubmatch(q)
	if m == nil {
		return chatV25{}, false
	}
	ts := m[1]
	if ts == "" {
		ts = m[3]
	}
	target, err := strconv.ParseFloat(ts, 64)
	if err != nil {
		return chatV25{}, false
	}
	picks, _ := chatPickSensors(place, metrics, "", nodes)
	if !place.Words && ref != nil && ref.Kind == "sensors" && len(ref.Picks) > 0 {
		var rp []chatSensorPick
		for _, p := range ref.Picks {
			if len(metrics) == 0 || len(chatResolveMetric(metrics[0], []string{p.Metric})) > 0 {
				rp = append(rp, p)
			}
		}
		if len(rp) > 0 {
			picks = rp
		}
	}
	if len(picks) == 0 {
		return chatV25{}, false
	}
	type est struct {
		pick       chatSensorPick
		last, perH float64
		at         time.Time
		state      string // eta | already | steady | wrong_way | no_data
		unit, loc  string
	}
	var ests []est
	end, n := t.chatWindow(t.now.Add(-2*time.Hour), t.now.Add(time.Second))
	for _, p := range picks {
		s := t.chatState(p.Node, p.Metric)
		if s == nil {
			continue
		}
		var xs []float64
		if n > 0 {
			xs = t.r.eng.HistoryAt(p.Node, p.Metric, end, n)
		}
		e := est{pick: p, unit: s.Unit, loc: s.Location, state: "no_data"}
		if len(xs) >= 6 {
			xm, ym := map[int64]float64{}, map[int64]float64{}
			for i, x := range xs {
				k := end - int64(len(xs)-1-i)*bucketSec
				xm[k], ym[k] = float64(k)/60, x // x in minutes
			}
			slope, r2, _ := chatFit(xm, ym)
			e.last, e.perH = xs[len(xs)-1], slope*60
			rise := !chatFallWordRe.MatchString(q)
			switch {
			case (rise && e.last >= target) || (!rise && e.last <= target):
				e.state = "already"
			case r2 < 0.2 || math.Abs(e.perH) < 1e-6 || (rise && e.perH <= 0) || (!rise && e.perH >= 0):
				e.state = "steady"
				if r2 >= 0.2 && math.Abs(e.perH) > 1e-6 {
					e.state = "wrong_way"
				}
			default:
				hours := (target - e.last) / e.perH
				if hours > 72 {
					e.state = "steady"
				} else {
					e.state, e.at = "eta", t.now.Add(time.Duration(hours*float64(time.Hour)))
				}
			}
		}
		ests = append(ests, e)
	}
	if len(ests) == 0 {
		return chatV25{}, false
	}
	sort.SliceStable(ests, func(i, j int) bool {
		a, b := ests[i], ests[j]
		if (a.state == "eta") != (b.state == "eta") {
			return a.state == "eta"
		}
		return a.at.Before(b.at)
	})
	name := chatMetricName(ests[0].pick.Metric)
	tgt := chatNum(target, ests[0].unit)
	var lines []string
	tools := []ChatTool{}
	for i, e := range ests {
		if i >= 3 {
			break
		}
		who := fmt.Sprintf("%s (%s)", e.loc, e.pick.Node)
		switch e.state {
		case "eta":
			in := e.at.Sub(t.now)
			lines = append(lines, fmt.Sprintf("%s: %s now, rising about %s per hour, so it would reach %s around %s (in %s)", who,
				chatNum(chatRound(e.pick.Metric, e.last), e.unit), chatNum(chatRound(e.pick.Metric, math.Abs(e.perH)), e.unit), tgt, e.at.In(IST).Format("15:04"), chatAge(in)))
		case "already":
			lines = append(lines, fmt.Sprintf("%s: already at %s, past %s", who, chatNum(chatRound(e.pick.Metric, e.last), e.unit), tgt))
		case "wrong_way":
			lines = append(lines, fmt.Sprintf("%s: %s now and moving away from %s", who, chatNum(chatRound(e.pick.Metric, e.last), e.unit), tgt))
		case "steady":
			lines = append(lines, fmt.Sprintf("%s: %s now and not rising (no clear trend in the last 2 hours)", who, chatNum(chatRound(e.pick.Metric, e.last), e.unit)))
		default:
			lines = append(lines, fmt.Sprintf("%s: not enough readings in the last 2 hours", who))
		}
		tools = append(tools, chatToolRec("forecast_crossing", map[string]any{"node": e.pick.Node, "metric": e.pick.Metric, "target": target,
			"_picks": []any{e.pick.Node + "|" + e.pick.Metric}}, map[string]any{"state": e.state, "last": e.last, "slope_per_h": e.perH}))
	}
	text := fmt.Sprintf("%s: %s.", "Estimate for "+name+" crossing "+tgt, strings.Join(lines, "; "))
	if len(ests) > 3 {
		text += fmt.Sprintf(" (%d more sensors not shown.)", len(ests)-3)
	}
	text += " This is a straight line through the last 2 hours of readings, not a forecast: a change in occupancy, ventilation or weather changes it."
	return chatV25{text, tools}, true
}

// ---------------------------------------------------------------- 5. false alarms

var chatFalseAlarmRe = regexp.MustCompile(`(?i)\bfalse\s+(alarms?|alerts?|positives?)\b`)

// chatFalseAlarms: incidents an operator dismissed or closed as a false alarm in the period (workflow outcome).
func (t chatTools) chatFalseAlarms(q string, span chatSpan, dom string, place chatPlace) (chatV25, bool) {
	f := map[string]any{}
	when := "on this device"
	if span.Found() {
		f["time"] = span.Args()
		when = span.Describe()
	} else if span.Unparsed != "" {
		return chatV25{}, false
	}
	if dom != "" {
		f["domain"] = dom
	}
	if place.Node != "" {
		f["node"] = place.Node
	}
	incs, _, _, err := t.filter(f, false)
	if err != nil {
		return chatV25{}, false
	}
	var hit []chatInc
	for _, ci := range incs {
		if ci.inc.Outcome == "false_alarm" || (ci.inc.Approval == "dismissed" && ci.inc.Outcome == "") {
			hit = append(hit, ci)
		}
	}
	sort.SliceStable(hit, func(i, j int) bool { return hit[i].at.After(hit[j].at) })
	ids := []string{}
	var ps []string
	for _, ci := range hit {
		ids = append(ids, ci.inc.ID)
		if len(ps) < 5 {
			ps = append(ps, fmt.Sprintf("[%s] %s (%s)", ci.inc.ID, ci.inc.Title, ci.at.In(IST).Format("2006-01-02 15:04")))
		}
	}
	var text string
	if len(hit) == 0 {
		text = fmt.Sprintf("No incident was dismissed or closed as a false alarm %s (out of %s).", when, plural(len(incs), "incident", "incidents"))
	} else {
		text = fmt.Sprintf("%s dismissed or closed as a false alarm %s (out of %s): %s.", plural(len(hit), "incident was", "incidents were"), when,
			plural(len(incs), "incident", "incidents"), strings.Join(ps, "; "))
		if len(hit) > 5 {
			text += fmt.Sprintf(" (%d more not shown.)", len(hit)-5)
		}
	}
	args := chatCopyArgs(f)
	args["outcome"] = "false_alarm"
	return chatV25{text, []ChatTool{chatToolRec("count_incidents", args, map[string]any{"total": len(incs), "false_alarms": len(hit), "ids": ids})}}, true
}

// ---------------------------------------------------------------- 6. which one first

var chatFirstRe = regexp.MustCompile(`(?i)\bwhich\b[^.?!]*\bfirst\b|\bwhat\b[^.?!]*\b(first|priority|most\s+urgent)\b|\bprioriti[sz]e\b|\bwhere\s+(do|should)\s+(i|we)\s+start\b|\bwhat\s+to\s+(do|handle|look\s+at)\s+first\b`)

// chatPriority: the open incident to handle first: severity, then a sensor still flagged now, then the newest; several
// incidents on the same sensor count once (the newest stands for them).
func (t chatTools) chatPriority(q string, dom string, place chatPlace, nodes map[string]NodeInfo) (chatV25, bool) {
	wantCrit := regexp.MustCompile(`(?i)\bcritical\b`).MatchString(q)
	args := map[string]any{"workflow": wfNeeds}
	if dom != "" {
		args["domain"] = dom
	}
	incs, _, _, err := t.filter(args, false)
	if err != nil {
		return chatV25{}, false
	}
	var open []chatInc
	for _, ci := range incs {
		if wfOf(ci.inc) == wfNeeds && chatIncAt(ci, place, nodes) {
			open = append(open, ci)
		}
	}
	if wantCrit {
		var c []chatInc
		for _, ci := range open {
			if normSeverity(ci.inc.Severity) == "critical" {
				c = append(c, ci)
			}
		}
		if len(c) == 0 {
			text := "No critical incident is waiting for a decision."
			if len(open) > 0 {
				text += fmt.Sprintf(" %s open at a lower level.", plural(len(open), "incident is", "incidents are"))
			}
			return chatV25{text, []ChatTool{chatToolRec("open_incidents", args, map[string]any{"total": len(open)})}}, true
		}
		open = c
	}
	if len(open) == 0 {
		if place.Words {
			return chatV25{fmt.Sprintf("No incident %s is waiting for a decision right now.", chatPlaceWords(place)), []ChatTool{chatToolRec("open_incidents", args, map[string]any{"total": 0})}}, true
		}
		return chatV25{"No incident is waiting for a decision right now.", []ChatTool{chatToolRec("open_incidents", args, map[string]any{"total": 0})}}, true
	}
	live := func(ci chatInc) bool {
		for _, s := range ci.sensors {
			if st := t.chatState(s.Node, s.Metric); st != nil && st.Status != "" && st.Status != "normal" && st.Quality != "stale" {
				return true
			}
		}
		return false
	}
	sensorKey := func(ci chatInc) string {
		if len(ci.sensors) == 0 {
			return ci.inc.ID
		}
		return ci.sensors[0].Node + "|" + ci.sensors[0].Metric
	}
	better := func(a, b chatInc) bool {
		sa, sb := chatSevOrder[normSeverity(a.inc.Severity)], chatSevOrder[normSeverity(b.inc.Severity)]
		if sa != sb {
			return sa < sb
		}
		la, lb := live(a), live(b)
		if la != lb {
			return la
		}
		return a.at.After(b.at)
	}
	groups := map[string][]chatInc{}
	var order []string
	for _, ci := range open {
		k := sensorKey(ci)
		if groups[k] == nil {
			order = append(order, k)
		}
		groups[k] = append(groups[k], ci)
	}
	var tops []chatInc
	folded := map[string][]string{}
	for _, k := range order {
		g := groups[k]
		best := g[0]
		for _, ci := range g[1:] {
			if better(ci, best) {
				best = ci
			}
		}
		for _, ci := range g {
			if ci.inc.ID != best.inc.ID {
				folded[best.inc.ID] = append(folded[best.inc.ID], ci.inc.ID)
			}
		}
		tops = append(tops, best)
	}
	sort.SliceStable(tops, func(i, j int) bool { return better(tops[i], tops[j]) })
	first := tops[0]
	desc := func(ci chatInc) string {
		return fmt.Sprintf("[%s] %s (%s, %s)", ci.inc.ID, ci.inc.Title, chatSevName(normSeverity(ci.inc.Severity)), ci.at.In(IST).Format("2006-01-02 15:04"))
	}
	text := "Start with " + desc(first) + "."
	if live(first) {
		text += " Its sensor is still flagged right now."
	}
	note := func(ci chatInc) string {
		if f := folded[ci.inc.ID]; len(f) > 0 {
			return fmt.Sprintf(" (%s on the same sensor, counted once: %s)", plural(len(f), "earlier alert", "earlier alerts"), strings.Join(f, ", "))
		}
		return ""
	}
	text += note(first)
	// night sweep 2026-11-27 #68: "what should the team check first for the KH level 3 issue": that incident's open steps
	if place.Words && regexp.MustCompile(`(?i)\b(check|do|fix|inspect|steps?)\b`).MatchString(q) {
		rt := chatRoute{Tool: "get_incident", Args: map[string]any{"id": first.inc.ID}, Act: "do"}
		if res, err := t.run("get_incident", rt.Args); err == nil {
			t.chatAugment(rt, res)
			if steps, _ := res["_open_steps"].([]string); len(steps) > 0 {
				text += " First checks: " + strings.Join(steps[:min(3, len(steps))], "; ") + "."
			}
		}
	}
	if len(tops) > 1 {
		var ps []string
		for _, ci := range tops[1:min(4, len(tops))] {
			ps = append(ps, desc(ci)+note(ci))
		}
		text += " Next: " + strings.Join(ps, "; ") + "."
		if len(tops) > 4 {
			text += fmt.Sprintf(" (%d more waiting.)", len(tops)-4)
		}
	}
	ids := []string{}
	for _, ci := range tops {
		ids = append(ids, ci.inc.ID)
	}
	return chatV25{text, []ChatTool{chatToolRec("open_incidents", args, map[string]any{"total": len(open), "first": first.inc.ID, "ranked": ids})}}, true
}

// ---------------------------------------------------------------- peak with its time

// chatPeakTime: "highest CO2 in KH level 03 in the last 4 hours and when": each sensor's extreme and its time.
func (t chatTools) chatPeakTime(q string, picks []chatSensorPick, sp chatSpan) chatV25 {
	low := regexp.MustCompile(`(?i)\b(lowest|min(imum)?|coldest)\b`).MatchString(q)
	hist := t.chatHistory(picks, sp)
	end, n := t.chatWindow(sp.From, sp.To)
	var lines []string
	for _, p := range picks[:min(4, len(picks))] {
		s := t.chatState(p.Node, p.Metric)
		if s == nil || n <= 0 {
			continue
		}
		xs := t.r.eng.HistoryAt(p.Node, p.Metric, end, n)
		if len(xs) == 0 {
			continue
		}
		k := 0
		for i, x := range xs {
			if (low && x < xs[k]) || (!low && x > xs[k]) {
				k = i
			}
		}
		at := time.Unix(end-int64(len(xs)-1-k)*bucketSec, 0)
		word := map[bool]string{true: "lowest", false: "highest"}[low]
		lines = append(lines, fmt.Sprintf("The %s %s at %s (%s) %s was %s, at %s", word, chatMetricName(p.Metric), s.Location, p.Node, sp.Describe(),
			chatNum(chatRound(p.Metric, xs[k]), s.Unit), chatTS(at)))
	}
	if len(lines) == 0 {
		return hist
	}
	return chatV25{strings.Join(lines, ". ") + ".", hist.Tools}
}

// ---------------------------------------------------------------- 10. knowledge about an on-board incident

var chatKnowRe = regexp.MustCompile(`(?i)\bwhy\b|\bsafe\b|\bdanger\w*|\bharm\w*|\bhealth\w*|\bwhat\s+does\b[^?]*\bmean\b|\bcauses?\b|\bshould\s+(i|we)\b|\bis\s+(it|that)\s+(bad|ok|okay|normal)\b`)

// chatKnowledge: a why / is-it-safe question about a metric or place that has an incident on this device: answer from
// the incident and the alert limits first; the fog lookup is only said to be unavailable (once) when it is down.
func (t chatTools) chatKnowledge(q string, place chatPlace, metrics []string, nodes map[string]NodeInfo) (chatV25, bool) {
	if len(metrics) == 0 && !place.Words {
		return chatV25{}, false
	}
	var cands []chatInc
	for _, ci := range t.incidents() {
		if ci.inc.Injected || ci.archived || normSeverity(ci.inc.Severity) == "normal" {
			continue
		}
		for _, s := range ci.sensors {
			ok := len(metrics) > 0 && func() bool {
				for _, w := range metrics {
					if len(chatResolveMetric(w, []string{s.Metric})) > 0 {
						return true
					}
				}
				return false
			}()
			if len(metrics) == 0 {
				ok = true
			}
			if ok && place.Words && !chatNodeMatch(s.Node, nodes[s.Node], place) {
				ok = false
			}
			if ok {
				cands = append(cands, ci)
				break
			}
		}
	}
	if len(cands) == 0 {
		return chatV25{}, false
	}
	sort.SliceStable(cands, func(i, j int) bool {
		wi, wj := wfOf(cands[i].inc) == wfNeeds, wfOf(cands[j].inc) == wfNeeds
		if wi != wj {
			return wi
		}
		return cands[i].at.After(cands[j].at)
	})
	ci := cands[0]
	res, err := t.run("get_incident", map[string]any{"id": ci.inc.ID})
	if err != nil {
		return chatV25{}, false
	}
	sev, _ := res["severity"].(string)
	text := fmt.Sprintf("On this device: [%s] %s (%s, %s).", ci.inc.ID, ci.inc.Title, chatSevName(sev), ci.at.In(IST).Format("2006-01-02 15:04"))
	if root, _ := res["root_cause"].(string); root != "" {
		text += " Root cause: " + strings.TrimRight(root, ".") + "."
	}
	picks := []chatSensorPick{}
	for _, s := range ci.sensors {
		if len(metrics) == 0 || len(chatResolveMetric(metrics[0], []string{s.Metric})) > 0 || metrics[0] == "aq" || metrics[0] == "wq" {
			picks = append(picks, chatSensorPick{s.Node, s.Metric})
		}
	}
	tools := []ChatTool{chatToolRec("get_incident", map[string]any{"id": ci.inc.ID}, res)}
	if len(picks) > 0 {
		if line := t.chatReadingLine(picks[0]); line != "" {
			text += " " + line + "."
		}
	}
	// night sweep 2026-11-27 #118: no "fog server" note on every answer; the facts above are the answer
	return chatV25{text, tools}, true
}

// ---------------------------------------------------------------- the router hook

// chatPolishRoutes: the 2026-11-20 routes, tried before the older v25 intents. ok false = none applies.
func (t chatTools) chatPolishRoutes(q string, history []ChatMsg, place chatPlace, metrics []string, span chatSpan, dom string, nodes map[string]NodeInfo, picks []chatSensorPick) (chatV25, bool) {
	if chatInjectRe.MatchString(q) || chatIsAction(q) || len(chatIDs(q)) > 0 {
		return chatV25{}, false
	}
	incWords := chatIncQRe.MatchString(q)
	switch {
	case chatFalseAlarmRe.MatchString(q):
		return t.chatFalseAlarms(q, span, dom, place)
	case chatNotSendRe.MatchString(q) && chatWhichRe.MatchString(q) && place.Node == "":
		return t.chatNotSending(place, metrics, nodes), true
	case chatFirstRe.MatchString(q) && !chatCountQRe.MatchString(q) && (incWords || regexp.MustCompile(`(?i)\b(critical|serious|urgent|alerts?|incidents?)\b`).MatchString(q)):
		return t.chatPriority(q, dom, place, nodes)
	case chatForecastRe.MatchString(q) && len(metrics) > 0:
		return t.chatForecast(q, chatRefOf(history), place, metrics, nodes)
	case chatPeakRe.MatchString(q) && len(metrics) > 0 && len(picks) > 0 && place.Words && span.Found() && !incWords && !chatCountQRe.MatchString(q):
		return t.chatPeakTime(q, picks, span), true
	case chatKnowRe.MatchString(q) && len(metrics) > 0 && !incWords:
		return t.chatKnowledge(q, place, metrics, nodes)
	}
	return chatV25{}, false
}

// ---------------------------------------------------------------- 7. asked format and length

var (
	chatLinesRe = regexp.MustCompile(`(?i)\b(?:in|within|using|just)\s+(one|1|two|2|three|3)\s+(?:short\s+)?(?:lines?|sentences?)\b|\b(one|two|three)[- ](?:line|sentence)\b|\bone[- ]liner\b|\bin\s+a\s+(?:single\s+)?(?:line|sentence)\b`)
	chatShortRe = regexp.MustCompile(`(?i)\b(short(ly|er)?|brief(ly)?|concise(ly)?|tl;?dr|in\s+short|quick(ly)?)\b`)
	chatMgrRe   = regexp.MustCompile(`(?i)\bfor\s+(my|the|our)\s+(manager|boss|supervisor|principal|director|dean|head|chief)\b|\bnon[- ]technical\b|\bfor\s+management\b`)
	chatSimpRe  = regexp.MustCompile(`(?i)\b(simple|plain|easy|layman'?s?|everyday)\s+(words|terms|language|english)\b|\beli5\b|\bsimple\s+(mein|me|main|bhasha)\b|\blike\s+i'?m\s+(five|new|a\s+beginner)\b|\bnot\s+an?\s+\w+\s+(guy|person|expert)\b`)
	// text the plain-words pass drops: rule thresholds and reading stamps in brackets, the "ask why" hint
	chatParenRe = regexp.MustCompile(`\s*\([^()]{18,}\)`)
	chatHintRe  = regexp.MustCompile(`\s*Ask why, or what to do, for its details\.`)
)

type chatFormat struct {
	Lines  int // sentences to keep, 0 = no limit
	Plain  bool
	Manage bool
}

func chatFormatOf(q string) chatFormat {
	var f chatFormat
	if m := chatLinesRe.FindStringSubmatch(q); m != nil {
		w := strings.ToLower(m[1] + m[2])
		f.Lines = map[string]int{"one": 1, "1": 1, "two": 2, "2": 2, "three": 3, "3": 3}[w]
		if f.Lines == 0 {
			f.Lines = 1
		}
	} else if regexp.MustCompile(`(?i)\bin\s+a\s+(single\s+)?(line|sentence)\b|\bone[- ]liner\b`).MatchString(q) {
		f.Lines = 1
	}
	if chatMgrRe.MatchString(q) {
		f.Manage, f.Plain = true, true
		if f.Lines == 0 {
			f.Lines = 3
		}
	}
	if chatSimpRe.MatchString(q) {
		f.Plain = true
		if f.Lines == 0 {
			f.Lines = 4
		}
	}
	if chatShortRe.MatchString(q) && f.Lines == 0 {
		f.Lines = 2
	}
	return f
}

// chatSentences: the sentences of s (a stop followed by a space and a capital, "[", "(" or a digit; decimals stay whole).
func chatSentences(s string) []string {
	rs := []rune(strings.TrimSpace(s))
	var out []string
	start := 0
	for i := 0; i < len(rs); i++ {
		if (rs[i] == '.' || rs[i] == '!' || rs[i] == '?') && i+2 < len(rs) && rs[i+1] == ' ' {
			nx := rs[i+2]
			if nx >= 'A' && nx <= 'Z' || nx == '[' || nx == '(' || nx >= '0' && nx <= '9' {
				out = append(out, strings.TrimSpace(string(rs[start:i+1])))
				start = i + 2
			}
		}
	}
	if start < len(rs) {
		out = append(out, strings.TrimSpace(string(rs[start:])))
	}
	return out
}

// chatTrimLong: one sentence cut at a "; " item boundary near 200 characters.
func chatTrimLong(s string, limit int) string {
	r := []rune(s)
	if len(r) <= limit {
		return s
	}
	cut := strings.LastIndex(string(r[:limit]), "; ")
	if cut < limit/3 {
		cut = strings.LastIndex(string(r[:limit]), ", ")
	}
	if cut < limit/3 {
		return s
	}
	return strings.TrimRight(string(r[:limit])[:cut], ",;: ") + " and more."
}

// chatFormatAnswer: the answer in the asked shape ("in two lines", "for my manager", "in simple words", "short").
func chatFormatAnswer(q, text string) string {
	f := chatFormatOf(q)
	if f.Lines == 0 && !f.Plain {
		return text
	}
	if f.Plain {
		text = chatHintRe.ReplaceAllString(text, "")
		text = chatParenRe.ReplaceAllString(text, "")
	}
	ss := chatSentences(text)
	if f.Lines > 0 && len(ss) > f.Lines {
		ss = ss[:f.Lines]
	}
	limit := 230
	if f.Lines == 1 {
		limit = 260
	}
	for i := range ss {
		ss[i] = chatTrimLong(ss[i], limit)
	}
	sep := " "
	if f.Lines > 0 && f.Lines <= 3 && !f.Manage {
		sep = "\n"
	}
	return strings.Join(ss, sep)
}

// ---------------------------------------------------------------- 9. plain words

var (
	chatPlainRe = []struct {
		re  *regexp.Regexp
		rep string
	}{
		{regexp.MustCompile(`(?i)\bapprove\s*(?:or|and|/)\s*dismiss(?:ed)?\b`), "tap I'm on it or Dismiss"},
		{regexp.MustCompile(`(?i)\bapproved\s*(?:or|and|/)\s*dismissed\b`), "tapped I'm on it or Dismiss on"},
		{regexp.MustCompile(`\s*[\[(]\s*S\d+\.E\d+(?:\s*[,;]\s*S\d+\.E\d+)*\s*[\])]`), ""},
		{regexp.MustCompile(`\s*\bS\d+\.E\d+\b`), ""},
		{regexp.MustCompile(`\s*\[E\d\]`), ""},
		// night sweep 2026-11-27 #118: no infrastructure jargon in an operator answer
		{regexp.MustCompile(`(?i)\bthe\s+fog\s+(server\s+)?(is\s+)?(offline|unreachable|down|not\s+reachable)\b`), "the campus server is not reachable"},
		{regexp.MustCompile(`(?i)\bfog\s+server\b`), "campus server"},
		{regexp.MustCompile(`(?i)\bfrom\s+the\s+fog\b`), "from the campus server"},
	}
	chatIDWords = strings.NewReplacer("air_quality", "air quality", "sensor_fault", "sensor fault", "room_temp", "room temperature", "power_kw", "power",
		"ac_units_on", "AC units on", "ac_on", "AC on", "no_action_needed", "no action needed", "false_alarm", "false alarm",
		"fixed_by_action", "fixed by action", "sensor_replaced", "sensor replaced", "sensor_repaired", "sensor repaired",
		"resolved_on_its_own", "resolved on its own")
	chatSpaceFixRe = regexp.MustCompile(`[ \t]{2,}| +([,.;:])`)
)

// chatPlain: the app's own words (its buttons are "I'm on it" and "Dismiss") and no internal ids (domain names with
// underscores, rule references such as S1.E4).
func chatPlain(text string) string {
	for _, p := range chatPlainRe {
		text = p.re.ReplaceAllString(text, p.rep)
	}
	text = chatIDWords.Replace(text)
	text = chatSpaceFixRe.ReplaceAllStringFunc(text, func(m string) string {
		if strings.TrimSpace(m) == "" {
			return " "
		}
		return strings.TrimSpace(m)
	})
	return text
}

// chatFinish: the plain-words pass and the asked format, applied to every answer.
func chatFinish(q, text string) string {
	return chatFormatAnswer(q, chatPlain(text))
}

// outdoor stations: a step about the building's own air handling does not apply to them
var chatIndoorStepRe = regexp.MustCompile(`(?i)\b(ahu|air[- ]handling|dampers?|fresh[- ]air|ventilation|hvac|ac\s+units?|supply\s+fan|exhaust\s+fan|windows?|doors?)\b`)

func chatOutdoorNode(n NodeInfo) bool {
	l := strings.ToLower(n.Location)
	return n.Role == "weather" || strings.Contains(l, "outdoor") || strings.Contains(l, "weather station") || strings.Contains(l, "rooftop")
}

// chatOutdoorSteps: the open checklist steps without the indoor ones when every flagged sensor is outdoors.
func chatOutdoorSteps(steps []string, flagged []string, nodes map[string]NodeInfo) ([]string, bool) {
	if len(flagged) == 0 {
		return steps, false
	}
	for _, id := range flagged {
		if !chatOutdoorNode(nodes[id]) {
			return steps, false
		}
	}
	var out []string
	for _, s := range steps {
		if !chatIndoorStepRe.MatchString(s) {
			out = append(out, s)
		}
	}
	return out, len(out) != len(steps)
}

// ---------------------------------------------------------------- 8. open questions go to the reasoner

var chatOpenQRe = regexp.MustCompile(`(?i)\b(why|how\s+come|should\s+(i|we)|what\s+should|explain|summari[sz]e|compare|comparison|is\s+(it|the\s+water|the\s+air)\s+safe|do\s+(i|we)\s+need|recommend\w*|what\s+do\s+you\s+think)\b`)

// chatSendToReasoner: an open question whose template answer is data (it has tools) is written by the reasoner from
// those facts, unless the user asked for a format the template trims exactly, or the answer is a refusal.
func chatSendToReasoner(q string, m ChatMsg) bool {
	if len(m.Tools) == 0 || strings.HasPrefix(m.Text, "There is no incident ") {
		return false
	}
	// night sweep 2026-11-27 #24 / #66: a multi-part question ("explain X in one sentence, then give the value, then say
	// whether it needs action") and "explain ... in simple words" are written by the model from the template's facts
	// (the template answered one part / only the title)
	if chatMultiPart(q) || chatExplainAskRe.MatchString(q) && chatFormatOf(q).Plain {
		return !strings.HasPrefix(m.Text, "I can't do that") && !strings.HasPrefix(m.Text, "Sorry, that's outside") && !strings.HasPrefix(m.Text, "That's outside")
	}
	if !chatOpenQRe.MatchString(q) || chatFormatOf(q).Lines > 0 || chatFormatOf(q).Plain {
		return false
	}
	return !strings.HasPrefix(m.Text, "I can't do that") && !strings.HasPrefix(m.Text, "Sorry, that's outside") && !strings.HasPrefix(m.Text, "That's outside")
}

// chatFactsHint: the template answer as facts for the model (it still answers in its own words and may call tools).
func chatFactsHint(text string) string {
	r := []rune(text)
	if len(r) > 1500 {
		text = string(r[:1500])
	}
	return "\n[Facts already read from the device: " + text + " Answer from these facts in plain words; say what they mean and what to do next.]"
}

// ---------------------------------------------------------------- 11. session archive and clear

const chatArchiveDays = 30

// archiveOldLocked: sessions not touched for 30 days move to state/chats_archive.json (still on disk, out of the list).
func (c *chatStore) archiveOldLocked(now time.Time) int {
	cut := now.Unix() - chatArchiveDays*86400
	var old []*ChatSession
	for id, s := range c.S {
		if s.Updated > 0 && s.Updated < cut {
			old = append(old, s)
			delete(c.S, id)
		}
	}
	if len(old) == 0 {
		return 0
	}
	c.appendArchiveLocked(old, now)
	return len(old)
}

// night sweep 2026-11-27 #52b: chats_archive.json is local only (never uploaded to Supabase or the fog); entries older
// than 90 days drop out and the file stays under 5 MB (oldest first out).
const (
	chatArchiveKeepDays = 90
	chatArchiveMaxBytes = 5 << 20
	chatKeepSessions    = 100
)

// appendArchiveLocked adds sessions to state/chats_archive.json and rotates it (90 days / 5 MB).
func (c *chatStore) appendArchiveLocked(add []*ChatSession, now time.Time) {
	p := filepath.Join(filepath.Dir(c.path), "chats_archive.json")
	var have []*ChatSession
	if b, err := os.ReadFile(p); err == nil {
		_ = json.Unmarshal(b, &have)
	}
	have = append(have, add...)
	cut := now.Unix() - chatArchiveKeepDays*86400
	keep := have[:0]
	for _, s := range have {
		if s != nil && (s.Updated == 0 || s.Updated >= cut) {
			keep = append(keep, s)
		}
	}
	sort.SliceStable(keep, func(i, j int) bool { return keep[i].Updated < keep[j].Updated })
	b, err := json.Marshal(keep)
	for err == nil && len(b) > chatArchiveMaxBytes && len(keep) > 0 {
		drop := len(keep)/10 + 1
		keep = keep[drop:]
		b, err = json.Marshal(keep)
	}
	if err == nil {
		if werr := atomicWrite(p, b, 0o644); werr != nil {
			log.Printf("chat: archive not saved: %v", werr)
		}
	}
}

// archiveOverflowLocked: sessions beyond the newest 100 move to the archive (they were dropped at the next restart).
func (c *chatStore) archiveOverflowLocked(now time.Time) int {
	if len(c.S) <= chatKeepSessions {
		return 0
	}
	list := make([]*ChatSession, 0, len(c.S))
	for _, s := range c.S {
		list = append(list, s)
	}
	sort.Slice(list, func(i, j int) bool { return list[i].Updated > list[j].Updated })
	old := list[chatKeepSessions:]
	for _, s := range old {
		delete(c.S, s.ID)
	}
	c.appendArchiveLocked(old, now)
	return len(old)
}

// clearLocked: every session is removed from the list and the file (the "Clear history" button); returns how many.
func (c *chatStore) clearLocked() int {
	n := len(c.S)
	c.S = map[string]*ChatSession{}
	c.saveLocked()
	return n
}
