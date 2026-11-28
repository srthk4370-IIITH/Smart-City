package main

// Report wording guards from live facts (sweep 2026-11-27; owner: "try a local fix, no new top-up unless the errors
// vary"). Each guard only rewrites the reasoner's free text when the incident's own readings contradict it, and
// records a repair line, so the report stays the model's report.
//   1. AC off: an AC-units sensor in the incident reads 0, but the text says "stop/turn off the AC" or "AC running".
//   2. Outdoor dust: every flagged sensor is an outdoor PM sensor, but the text says "ventilate"/"open windows"/
//      "increase fresh air" (outdoor dust: keep windows closed, cut fresh-air intake).
//   3. Corroborated rise: the report calls a temperature rise a sensor jump / sensor fault while a second temperature
//      sensor in the incident rose by >= 1 C over the same 30 min: treated as a real change.

import (
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
)

var (
	acStopRe     = regexp.MustCompile(`(?i)\b(stop|turn off|switch off|shut (?:down|off))\s+(the\s+)?(ac|a/c|air[- ]?conditioning|ac units?)\b`)
	acRunningRe  = regexp.MustCompile(`(?i)\b(ac|a/c|ac units?)\s+(is |are |still )*running\b`)
	ventilateRe  = regexp.MustCompile(`(?i)\b(ventilate( the (room|area|space))?|open (the )?windows|increase (the )?(fresh[- ]air|ventilation)( intake)?)\b`)
	jumpClaimRe  = regexp.MustCompile(`(?i)\b(sensor (jump|glitch|spike|error|fault|malfunction|problem|issue)|not (a )?real (heat|rise|event|change)|not a hot room|faulty sensor|suspect(ed)? (\w+ ){0,2}(readings?|sensors?|values?)|sensor (is )?heating itself)\b`)
	tempMetricRe = regexp.MustCompile(`(?i)^(temp|temperature|room_temp|air_temp)$`)
)

func lastVal(s SensorRef) (float64, bool) {
	if len(s.Xs) == 0 {
		return 0, false
	}
	return s.Xs[len(s.Xs)-1], true
}

// rise over the last n readings (0 when the window is shorter)
func riseOver(s SensorRef, n int) float64 {
	if len(s.Xs) <= n {
		return 0
	}
	return s.Xs[len(s.Xs)-1] - s.Xs[len(s.Xs)-1-n]
}

func acOff(inc *Incident) bool {
	for _, s := range inc.Sensors {
		if s.Metric == "ac_units_on" || s.Metric == "ac_on" {
			if v, ok := lastVal(s); ok && v == 0 {
				return true
			}
		}
	}
	return false
}

func outdoorPMOnly(inc *Incident) bool {
	n := 0
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		n++
		m := strings.ToLower(s.Metric)
		loc := strings.ToLower(s.Location)
		if !strings.HasPrefix(m, "pm") || !(s.Role == "weather" || strings.Contains(loc, "outdoor") || strings.Contains(loc, "weather")) {
			return false
		}
	}
	return n > 0
}

// corroboratedRise: two different temperature sensors both rose >= 1 C over the last 6 readings (30 min).
func corroboratedRise(inc *Incident) (a, b string, ok bool) {
	var up []SensorRef
	for _, s := range inc.Sensors {
		if tempMetricRe.MatchString(s.Metric) && riseOver(s, 6) >= 1.0 {
			up = append(up, s)
		}
	}
	for i := range up {
		for j := i + 1; j < len(up); j++ {
			if up[i].Node != up[j].Node || up[i].Metric != up[j].Metric {
				return up[i].Node + " " + up[i].Metric, up[j].Node + " " + up[j].Metric, true
			}
		}
	}
	return "", "", false
}

// reportTexts: every free-text field a guard may rewrite.
func reportTexts(rep *Report) []*string {
	out := []*string{&rep.Title, &rep.RootCause, &rep.Explanation, &rep.Action, &rep.CausalChain, &rep.MonitorNext}
	for i := range rep.Checklist {
		out = append(out, &rep.Checklist[i].Target, &rep.Checklist[i].Why)
	}
	return out
}

func rewriteAll(rep *Report, re *regexp.Regexp, repl string) bool {
	hit := false
	for _, p := range reportTexts(rep) {
		if re.MatchString(*p) {
			*p = re.ReplaceAllString(*p, repl)
			hit = true
		}
	}
	return hit
}

// contextFixReport applies the guards; returns the repair lines.
func contextFixReport(rep *Report, inc *Incident) []string {
	var rs []string
	// night sweep 2026-11-27 #98: "stepped up -2.40" copied from an agent observation
	stepHit := false
	for _, p := range reportTexts(rep) {
		if n := stepSignFix(*p); n != *p {
			*p, stepHit = n, true
		}
	}
	for i := range rep.Observations {
		if n := stepSignFix(rep.Observations[i].Text); n != rep.Observations[i].Text {
			rep.Observations[i].Text, stepHit = n, true
		}
	}
	if stepHit {
		rs = append(rs, "step direction set from the sign of the change")
	}
	if acOff(inc) {
		a := rewriteAll(rep, acStopRe, "check why the AC is off (power, breaker, controller) and restore cooling")
		b := rewriteAll(rep, acRunningRe, "AC is off")
		if a || b {
			rs = append(rs, "AC wording set to the readings: the AC units read 0 (off)")
		}
	}
	if outdoorPMOnly(inc) && rewriteAll(rep, ventilateRe, "keep windows closed and reduce fresh-air intake") {
		rs = append(rs, "outdoor dust: 'ventilate' replaced by 'keep windows closed, reduce fresh-air intake'")
	}
	if a, b, ok := corroboratedRise(inc); ok {
		// night sweep 2026-11-27 #94: only a claim about the temperature / room sensors counts; "pH sensor fault" in the
		// title of a heat incident is about another sensor and must not blank a good title
		tc := tempClaimer(inc)
		claim := rep.Severity == "sensor_fault" || rep.Label == "sensor_fault"
		strong := claim // the reasoner's verdict itself is "sensor fault": its whole story is built on it
		for _, p := range []*string{&rep.Title, &rep.RootCause, &rep.Explanation} {
			claim = claim || tc(*p)
		}
		if claim {
			if rep.Severity == "sensor_fault" {
				rep.Severity = ruleSeverity(inc.Sensors)
				if reportRank[rep.Severity] < reportRank["warning"] || rep.Severity == "sensor_fault" {
					rep.Severity = "warning"
				}
			}
			if rep.Label == "sensor_fault" {
				rep.Label = "unknown"
			}
			if tc(rep.Title) {
				rep.Title = "" // the findings title is used instead
			}
			note := "Two sensors (" + a + ", " + b + ") rose together, so this is a real temperature rise, not a sensor jump."
			if strong {
				// 2026-11-28 re-run (board INC-0016): the reasoner said "Point sensor reading not credible ... the AC's
				// own sensor reads normal" while both sensors were rising past 30 C. When the verdict itself was
				// sensor_fault, nothing in its story can be kept: replace title, root cause and explanation.
				rep.Title = ""
				cause := "cooling is not keeping up with the heat load"
				if acOff(inc) {
					cause = "the AC units are off"
				}
				rep.RootCause = "Real room temperature rise: " + a + " and " + b + " rose together; most likely " + cause + "."
				keep := dropClaimSentences(rep.Explanation, func(x string) bool { return tc(x) || faultStoryRe.MatchString(x) })
				rep.Explanation = strings.TrimSpace(note + " " + keep + " Check the AC units and the room.")
				if rep.Label == "unknown" || rep.Label == "" {
					rep.Label = "hvac_or_thermal_issue"
				}
				rs = append(rs, "corroborated rise: "+a+" and "+b+" rose together; the reasoner's sensor-fault verdict replaced (title, root cause, explanation)")
				return rs
			}
			rep.Explanation = dropClaimSentences(rep.Explanation, tc)
			rep.RootCause = dropClaimSentences(rep.RootCause, tc)
			if !strings.Contains(rep.Explanation, note) {
				rep.Explanation = strings.TrimSpace(note + " " + rep.Explanation)
			}
			rs = append(rs, "corroborated rise: "+a+" and "+b+" rose together; sensor-jump wording overruled")
		}
	}
	return rs
}

// dropClaimSentences removes the sentences that make the sensor-fault claim (and a following "Check the sensor.").
// isClaim nil = any jump / fault claim.
func dropClaimSentences(t string, isClaim func(string) bool) string {
	if isClaim == nil {
		isClaim = jumpClaimRe.MatchString
	}
	var keep []string
	drop := false
	for _, sen := range splitSentences(t) {
		if isClaim(sen) {
			drop = true
			continue
		}
		if drop && checkSensorRe.MatchString(sen) {
			continue
		}
		drop = false
		keep = append(keep, sen)
	}
	return strings.Join(keep, " ")
}

var checkSensorRe = regexp.MustCompile(`(?i)^\s*(please )?(check|inspect|recalibrate) the sensor\b`)

func splitSentences(t string) []string {
	var out []string
	start := 0
	for i := 0; i < len(t); i++ {
		if (t[i] == '.' || t[i] == '!' || t[i] == '?') && (i+1 == len(t) || t[i+1] == ' ') {
			if s := strings.TrimSpace(t[start : i+1]); s != "" {
				out = append(out, s)
			}
			start = i + 1
		}
	}
	if s := strings.TrimSpace(t[start:]); s != "" {
		out = append(out, s)
	}
	return out
}

// agreeLines (owner 2026-11-27, "do something about the reasoner on heat"): a fact line for the reasoner when two
// independent indoor temperature sensors in the same area both rose (>= 1 C over the last 6 readings). Without it
// the reasoner sometimes called a real AC-failure heat-up a "sensor jump" (board feature runs 2 and 3); on those
// board prompts the line took the reasoner from 27/32 to 31/31 correct (critical) on the laptop GPU
// (proofs/2026-11-27_features/heat_ab). The reportfix guard stays as the backstop.
func agreeLines(ss []SensorRef) []string {
	type up struct {
		s      SensorRef
		lo, hi float64
	}
	var ups []up
	for _, s := range ss {
		if s.Role == "weather" || !tempMetricRe.MatchString(s.Metric) || riseOver(s, 6) < 1.0 {
			continue
		}
		lo, ok := math.Inf(1), false
		for _, x := range s.Xs {
			if !math.IsNaN(x) && !math.IsInf(x, 0) && x < lo {
				lo, ok = x, true
			}
		}
		if ok {
			ups = append(ups, up{s, lo, s.Xs[len(s.Xs)-1]})
		}
	}
	var out []string
	for i := 0; i < len(ups) && len(out) < 2; i++ {
		for j := i + 1; j < len(ups) && len(out) < 2; j++ {
			a, b := ups[i], ups[j]
			if a.s.Node == b.s.Node || placeOf(a.s.Location) == "" || placeOf(a.s.Location) != placeOf(b.s.Location) {
				continue
			}
			out = append(out, fmt.Sprintf("AGREE: %s %s and %s %s are two independent temperature sensors in the same area (%s); "+
				"both rose over the window: %s %.1f -> %.1f C, %s %.1f -> %.1f C (now %.1f C apart).",
				a.s.Ref, a.s.Metric, b.s.Ref, b.s.Metric, placeOf(a.s.Location),
				a.s.Ref, a.lo, a.hi, b.s.Ref, b.lo, b.hi, math.Abs(a.hi-b.hi)))
		}
	}
	return out
}

// ---------------------------------------------------------------- night sweep 2026-11-27 (workstream B)

var (
	// #94: a claim clause is about temperature when it names a temperature word or a temperature sensor's ref, or names
	// no other metric at all ("a sensor jump"); "pH sensor fault" is about the pH sensor.
	clauseSepRe   = regexp.MustCompile(`\s*[;,:]\s*|\s+(?:and|but|while|whereas)\s+`)
	tempWordRe    = regexp.MustCompile(`(?i)\b(temp\w*|room|heat\w*|hot|warm\w*|thermal|cool\w*|ac|a/c|hvac)\b|\d\s?°?\s?C\b`)
	otherMetricRe = regexp.MustCompile(`(?i)\b(ph|co2|pm\s?2\.?5|pm\s?10|dust|flow|power|pf|load|tds|turbidity|tank|humidity|rh|occupancy|wind|voltage|current|chlorine)\b`)
	sensorRefRe   = regexp.MustCompile(`\bS\d+\b`)
)

// tempClaimer: true when a text makes a jump / fault claim about the incident's temperature or room sensors.
func tempClaimer(inc *Incident) func(string) bool {
	tempRef, otherRef := map[string]bool{}, map[string]bool{}
	for _, s := range inc.Sensors {
		if tempMetricRe.MatchString(s.Metric) {
			tempRef[s.Ref] = true
		} else if s.Ref != "" {
			otherRef[s.Ref] = true
		}
	}
	return func(t string) bool {
		for _, c := range clauseSepRe.Split(t, -1) {
			if !jumpClaimRe.MatchString(c) {
				continue
			}
			temp, other := tempWordRe.MatchString(c), otherMetricRe.MatchString(c)
			for _, ref := range sensorRefRe.FindAllString(c, -1) {
				temp, other = temp || tempRef[ref], other || otherRef[ref]
			}
			if temp || !other {
				return true
			}
		}
		return false
	}
}

// #98: "stepped up -2.40 pH" (the agent's words for a step_increase on a falling reading): up/down from the sign.
var stepSignRe = regexp.MustCompile(`(?i)\b(stepped|shifted|jumped|moved|steps?|stepping)\s+(up|down)(\s+(?:abruptly\s+)?(?:by\s+)?)([+\-−])(\d)`)

func stepSignFix(t string) string {
	return stepSignRe.ReplaceAllStringFunc(t, func(m string) string {
		g := stepSignRe.FindStringSubmatch(m)
		want := "down"
		if g[4] == "+" {
			want = "up"
		}
		if strings.EqualFold(g[2], want) {
			return m
		}
		if g[2] == strings.ToUpper(g[2]) {
			want = strings.ToUpper(want)
		}
		return g[1] + " " + want + g[3] + g[5]
	})
}

func stepSignFixAll(xs []string) []string {
	for i := range xs {
		xs[i] = stepSignFix(xs[i])
	}
	return xs
}

// #70: event claims about a sensor whose rule AND agent both read normal ("the flow event is real" while flow was
// steady) are removed, clause by clause. A word shared with an abnormal sensor (two temperature sensors) is left alone.
var (
	metricAlias = map[string]string{"flow": `flow`, "ph": `ph`, "co2": `co2`, "pm25": `pm\s?2\.?5`, "pm10": `pm\s?10`,
		"temp": `temperature`, "room_temp": `room temperature`, "rh": `humidity`, "level": `(?:tank|water) level`, "tds": `tds`,
		"power_kw": `power|load`, "pf": `power factor`, "occ": `occupancy`, "wind": `wind`}
	eventWordRe = regexp.MustCompile(`(?i)\b(event|surge|spike|leak\w*|burst|drop|rise|jump|anomal\w*|abnormal\w*|alarm\w*|problem|failure|excursion)\b`)
	calmWordRe  = regexp.MustCompile(`(?i)\b(no|not|never|steady|stable|normal|unchanged|flat|fine|ok|within|context)\b`)
	clauseDelRe = regexp.MustCompile(`\s*;\s*|,\s+|\s+and\s+`)
)

func aliasRe(metric string) *regexp.Regexp {
	a := metricAlias[metric]
	if a == "" {
		return nil
	}
	return regexp.MustCompile(`(?i)\b(?:` + a + `)\b`)
}

// normalEventFix: returns the repair line ("" = nothing changed).
func normalEventFix(rep *Report, inc *Incident, calls []AgentCall) string {
	agent := map[string]string{}
	for _, c := range calls {
		if c.Valid && c.Parsed != nil {
			agent[c.Ref] = normSeverity(c.Parsed.Status)
		}
	}
	var calm, busy []*regexp.Regexp
	var names []string
	for _, s := range inc.Sensors {
		re := aliasRe(s.Metric)
		if re == nil {
			continue
		}
		a, ok := agent[s.Ref]
		if normSeverity(s.Rule.Status) == "normal" && (!ok || a == "normal") {
			calm = append(calm, re)
			names = append(names, metricWord(s.Metric))
		} else {
			busy = append(busy, re)
		}
	}
	if len(calm) == 0 {
		return ""
	}
	bad := func(c string) bool {
		if !eventWordRe.MatchString(c) || calmWordRe.MatchString(c) {
			return false
		}
		for _, re := range busy {
			if re.MatchString(c) {
				return false
			}
		}
		for _, re := range calm {
			if re.MatchString(c) {
				return true
			}
		}
		return false
	}
	hit := false
	fix := func(p *string) {
		if n, ch := dropClauses(*p, bad); ch {
			*p, hit = n, true
		}
	}
	fix(&rep.Title)
	fix(&rep.RootCause)
	fix(&rep.Explanation)
	fix(&rep.CausalChain)
	for i := range rep.Observations {
		fix(&rep.Observations[i].Text)
	}
	if !hit {
		return ""
	}
	return "event claim removed: " + strings.Join(names, ", ") + " read normal (rule and agent)"
}

// dropClauses removes the clauses (split at ";", ", ", " and ") of each sentence that bad() flags; a sentence
// with nothing left goes. Terminal punctuation and the first capital are kept.
func dropClauses(t string, bad func(string) bool) (string, bool) {
	changed := false
	var out []string
	for _, sen := range splitSentences(t) {
		end := ""
		if n := len(sen); n > 0 && strings.ContainsAny(sen[n-1:], ".!?") {
			sen, end = sen[:n-1], sen[n-1:]
		}
		idx := clauseDelRe.FindAllStringIndex(sen, -1)
		var segs, dels []string
		prev := 0
		for _, d := range idx {
			segs, dels = append(segs, sen[prev:d[0]]), append(dels, sen[d[0]:d[1]])
			prev = d[1]
		}
		segs = append(segs, sen[prev:])
		var b strings.Builder
		kept := 0
		for i, sg := range segs {
			if bad(sg) {
				changed = true
				continue
			}
			if kept > 0 {
				b.WriteString(dels[i-1])
			}
			b.WriteString(sg)
			kept++
		}
		if kept == 0 {
			continue
		}
		s := strings.TrimSpace(b.String())
		if s != "" {
			s = strings.ToUpper(s[:1]) + s[1:]
		}
		out = append(out, s+end)
	}
	if !changed {
		return t, false
	}
	return strings.Join(out, " "), true
}

// #95: a fact line for the reasoner when a flagged sensor's episode is already over at the window end, so a late
// reading does not read the finished event as a step / sensor fault (INC-0016: pH 9.6 -> 7.2 called a sensor fault).
// The wording comes from stream A's returnedToNormalFact (engine.go) on the sensor's window.
func recoveredLines(ss []SensorRef) []string {
	var out []string
	for _, s := range ss {
		n := len(s.Xs)
		if s.Context || n < 2 || math.IsNaN(s.Xs[n-1]) {
			continue
		}
		fact := returnedToNormalFact(s.Role, s.Metric, s.Node, s.Xs, s.End)
		if fact == "" {
			continue
		}
		m, _ := effectiveMetricOK(s.Role, s.Metric, s.Node)
		u := ""
		if m.Unit != "" {
			u = " " + m.Unit
		}
		out = append(out, fmt.Sprintf("RECOVERED: %s %s %s; now %s%s, inside the card limits.",
			s.Ref, s.Metric, fact, strconv.FormatFloat(s.Xs[n-1], 'f', m.Dec, 64), u))
	}
	return out
}

// faultStoryRe: sentences of a "one sensor is wrong" story that no longer hold once two sensors agree (board INC-0016).
var faultStoryRe = regexp.MustCompile(`(?i)(not (read|treat) the room as (heated|hot)|disagrees? with|reads? normal|not credible|unreliable|point sensor|one (small )?sensor)`)
