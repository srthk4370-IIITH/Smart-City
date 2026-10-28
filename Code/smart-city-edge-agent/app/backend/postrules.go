package main

// Track B post-rules (proofs/2026-10-24_trackB/RESULTS.md): deterministic corrections applied to a v2 agent
// finding after the model and before the policy gate, from the window the prompt was built from. Off by
// default; switched on by the htpd_profile key
//
//	post_rules=all                      (every kept rule, in postRuleOrder)
//	post_rules=limit,rel_power,chatter  (a subset)
//
// Each rule is mirrored 1:1 by proofs/2026-10-24_trackB/scripts/trackb_lib.py, which scored it on the stored
// v2 outputs (1,148-row test, rw5 test) with the training scorer; TestPostRulesParity replays that fixture.
// Several rules re-apply the teacher's own label functions (StatusOf, the v2 routines) to the MODEL's pattern:
// they make status consistent with the pattern and the numbers, they do not add new knowledge (see RESULTS.md).

import (
	"math"
	"strings"
	"time"
)

var postRuleOrder = []string{"erratic", "limit", "quality_cause", "rel_power", "rel_level", "water_cause", "glitch", "floor", "chatter", "cause", "fkind", "hvac_rule"}

// P1 (proofs/2026-10-25_domain_plan): label-definition change for water level. A gradual decrease is a
// possible leak off-hours (teacher_v2) AND in the daytime when the tank has drained steadily for 3 h with no
// refill (postLongDrain); a model "possible_leak" warning is not downgraded while E9 shows a falling slow drift.
const postDrainPts = 36 // 3 h of 5-min readings

// postRules: the enabled rule set (nil = off). v2 agent only.
func postRules() map[string]bool {
	v := strings.TrimSpace(htpdProfile()["post_rules"])
	if v == "" || v == "off" || v == "0" || !agentV2() {
		return nil
	}
	on := map[string]bool{}
	for _, r := range strings.Split(v, ",") {
		r = strings.TrimSpace(r)
		if r == "all" || r == "1" {
			for _, k := range postRuleOrder {
				on[k] = true
			}
		} else if r != "" {
			on[r] = true
		}
	}
	return on
}

var postNormalCause = map[string]string{"air_quality": "normal_conditions", "water": "normal_usage", "power": "normal_load",
	"weather": "normal_weather", "occupancy": "normal_occupancy"}

type postCtx struct {
	role, metric, node string
	end                int64
	xs                 []float64
	m                  Metric
	st                 Stats
	base               float64
	e9Fall             bool // the prompt's E9 line reports a falling slow drift (level only)
}

type postChange struct{ rule, field, from, to string }

// applyPostRules corrects f in place with the enabled rules; xs = the prompt's window (oldest first).
func applyPostRules(on map[string]bool, role, metric, node string, end int64, xs []float64, f *Finding, prompt ...string) []postChange {
	m, ok := Metrics[role+"/"+metric]
	if len(on) == 0 || !ok || len(xs) < 12 || role == "hvac" || role == "occupancy" {
		return nil
	}
	c := &postCtx{role: role, metric: metric, node: node, end: end, xs: xs, m: m, st: ComputeStats(xs, m.Dec), base: mean(xs[:12])}
	if len(prompt) > 0 {
		c.e9Fall = postE9Falling(prompt[0])
	}
	var ch []postChange
	set := func(rule, field, to string) {
		var from string
		switch field {
		case "pattern":
			from, f.Pattern = f.Pattern, to
		case "status":
			from, f.Status = f.Status, to
		case "likely_cause":
			from, f.LikelyCause = f.LikelyCause, to
		case "fault_kind":
			from, f.FaultKind = f.FaultKind, to
		case "event_active":
			if f.EventActive != nil {
				from = boolStr(*f.EventActive)
			}
			b := to == "true"
			f.EventActive = &b
		}
		if from == to {
			return
		}
		ch = append(ch, postChange{rule, field, from, to})
		if field == "status" && to == "sensor_fault" && f.LikelyCause != "sensor_fault" {
			ch = append(ch, postChange{rule, "likely_cause", f.LikelyCause, "sensor_fault"})
			f.LikelyCause = "sensor_fault"
		}
	}
	for _, r := range postRuleOrder {
		if !on[r] {
			continue
		}
		for _, kv := range postRule(r, c, f) {
			set(r, kv[0], kv[1])
		}
	}
	if len(ch) > 0 && f.Status != "sensor_fault" {
		f.FaultKind = "" // policy: fault_kind only with sensor_fault
	}
	return ch
}

func boolStr(b bool) string {
	if b {
		return "true"
	}
	return "false"
}

func isEventStatus(s string) bool { return s == "normal" || s == "warning" || s == "critical" }

// postRule returns the (field, value) changes one rule makes; empty = none.
func postRule(name string, c *postCtx, f *Finding) [][2]string {
	switch name {
	case "erratic":
		return ruleErratic(c, f)
	case "limit":
		// status from the value vs the warning/critical limits (StatusOf, limit branch) with the model's pattern
		if !inSet(c.role, "air_quality", "weather", "power", "water") || !c.m.HasLimits {
			return nil
		}
		if !isEventStatus(f.Status) || f.Pattern == "flatline" || f.Pattern == "erratic" {
			return nil
		}
		if s := StatusOf(c.role, c.metric, f.Pattern, c.st, c.base); s != f.Status && isEventStatus(s) {
			return [][2]string{{"status", s}}
		}
	case "quality_cause":
		// water pH / TDS beyond a limit -> water_quality_issue (CauseOf for these metrics; the board's off-label
		// "acidic_condition" meant the same)
		if c.role != "water" || (c.metric != "ph" && c.metric != "tds") || (f.Status != "warning" && f.Status != "critical") {
			return nil
		}
		if f.Pattern != "stable" && f.LikelyCause != "water_quality_issue" {
			return [][2]string{{"likely_cause", "water_quality_issue"}}
		}
	case "rel_power", "rel_level":
		// no fixed limits: StatusOf relative branch (range / first-hour mean) + the v2 routines
		if name == "rel_power" && (c.role != "power" || c.metric != "power_kw") {
			return nil
		}
		if name == "rel_level" && (c.role != "water" || c.metric != "level") {
			return nil
		}
		if !isEventStatus(f.Status) || f.Pattern == "flatline" || postKeepLeak(c, f) {
			return nil
		}
		s := StatusOf(c.role, c.metric, f.Pattern, c.st, c.base)
		if rs, _, ok := routineV2(c, f.Pattern); ok {
			s = rs
		}
		if s != f.Status && isEventStatus(s) {
			return [][2]string{{"status", s}}
		}
	case "water_cause":
		// water level/flow: the cause the v2 routine gives for the model's pattern (filling, draining, leak,
		// overflow, valve, pump cycling); unchanged when no routine applies
		if c.role != "water" || (c.metric != "flow" && c.metric != "level") || f.Status == "sensor_fault" || postKeepLeak(c, f) {
			return nil
		}
		if _, cause, ok := routineV2(c, f.Pattern); ok && cause != f.LikelyCause {
			return [][2]string{{"likely_cause", cause}}
		}
	case "glitch":
		return ruleGlitch(c, f)
	case "floor":
		// indoor CO2 whose latest reading is below the sensor's valid range (250 ppm) -> sensor_fault (REALWORLD 5.6)
		if c.role != "air_quality" || c.metric != "co2" || c.st.Last >= postCO2Floor {
			return nil
		}
		var out [][2]string
		if f.Status != "sensor_fault" {
			out = append(out, [2]string{"status", "sensor_fault"})
		}
		if f.LikelyCause != "sensor_fault" {
			out = append(out, [2]string{"likely_cause", "sensor_fault"})
		}
		if f.Status != "sensor_fault" || !contains(FaultKinds, f.FaultKind) {
			fk := "bias"
			if f.Pattern == "flatline" {
				fk = "stuck"
			}
			out = append(out, [2]string{"fault_kind", fk})
		}
		return out
	case "chatter":
		return ruleChatter(c, f)
	case "cause":
		return ruleCause(c, f)
	case "fkind":
		if f.Status != "sensor_fault" || contains(FaultKinds, f.FaultKind) {
			return nil
		}
		fk := "drift"
		switch {
		case f.Pattern == "flatline":
			fk = "stuck"
		case f.Pattern == "erratic":
			fk = "noise"
		case c.st.Min == 0:
			fk = "dropout"
		case strings.HasPrefix(f.Pattern, "step"):
			fk = "bias"
		case f.Pattern == "throttling":
			fk = "saturation"
		}
		return [][2]string{{"fault_kind", fk}}
	}
	return nil
}

const postCO2Floor = 250.0

// the model's own pattern implies a sensor fault (v1 teacher rule): erratic outside power -> noise,
// non-zero flatline -> stuck
func ruleErratic(c *postCtx, f *Finding) [][2]string {
	fk := ""
	if f.Pattern == "erratic" && c.role != "power" {
		fk = "noise"
	} else if f.Pattern == "flatline" && math.Abs(c.st.Last) > 1e-6 {
		fk = "stuck"
	} else {
		return nil
	}
	var out [][2]string
	if f.Status != "sensor_fault" {
		out = append(out, [2]string{"status", "sensor_fault"})
	}
	if f.LikelyCause != "sensor_fault" {
		out = append(out, [2]string{"likely_cause", "sensor_fault"})
	}
	if f.FaultKind == "" {
		out = append(out, [2]string{"fault_kind", fk})
	}
	return out
}

// where each glitch kind is non-physical (REALWORLD 5.2, gen_rw5 ZERO_OK / RAIL_OK): a 0 reading, a reading at
// the range rail, or a one-reading excursion that returns. RH 100 % is physical (no rail); single-reading tank
// level jumps are v2 events, so level is rail-only.
var (
	glitchZero  = map[string]bool{"air_quality/co2": true, "air_quality/temp": true, "air_quality/rh": true, "water/ph": true, "water/tds": true}
	glitchRail  = map[string]bool{"air_quality/co2": true, "air_quality/temp": true, "water/tds": true, "water/ph": true, "water/level": true}
	glitchValue = map[string]bool{"air_quality/co2": true, "air_quality/temp": true, "air_quality/rh": true, "water/tds": true, "water/ph": true}
)

// one isolated single-reading glitch (glitchFree) that IS the window's spike/dip the model reports, in an
// otherwise normal window: a 0 / rail value -> sensor_fault dropout; any other value -> normal, no active event
func ruleGlitch(c *postCtx, f *Finding) [][2]string {
	if f.Pattern != "spike" && f.Pattern != "dip" {
		return nil
	}
	ys, i := glitchFree(c.role, c.metric, c.xs)
	if i < 0 {
		return nil
	}
	if (f.Pattern == "spike" && c.st.MaxIdx != i) || (f.Pattern == "dip" && c.st.MinIdx != i) {
		return nil
	}
	if StatusOf(c.role, c.metric, "stable", ComputeStats(ys, c.m.Dec), mean(ys[:12])) != "normal" {
		return nil
	}
	key, v := c.role+"/"+c.metric, c.xs[i]
	sentinel := (math.Abs(v) < 1e-9 && glitchZero[key]) || (glitchRail[key] && v >= c.m.Hi)
	if !sentinel && !glitchValue[key] {
		return nil
	}
	var out [][2]string
	if sentinel {
		if f.Status != "sensor_fault" {
			out = append(out, [2]string{"status", "sensor_fault"})
		}
		if f.LikelyCause != "sensor_fault" {
			out = append(out, [2]string{"likely_cause", "sensor_fault"})
		}
		if f.FaultKind != "dropout" {
			out = append(out, [2]string{"fault_kind", "dropout"})
		}
		return out
	}
	if f.Status != "normal" {
		out = append(out, [2]string{"status", "normal"})
		if nc := postNormalCause[c.role]; nc != "" && nc != f.LikelyCause {
			out = append(out, [2]string{"likely_cause", nc})
		}
	}
	if f.EventActive == nil || *f.EventActive {
		out = append(out, [2]string{"event_active", "false"})
	}
	return out
}

// the value hovers at the warning limit (every reading within the 5 % deadband, >= 3 crossings) -> warning,
// event active (REALWORLD 5.11). A "flatline" sensor_fault read is overridden only when the data contradicts
// it (it crosses the limit; no flat run of half the window): a stuck sensor at the limit never crosses it.
func ruleChatter(c *postCtx, f *Finding) [][2]string {
	if !inSet(c.role, "air_quality", "weather", "power", "water") || !c.m.HasLimits {
		return nil
	}
	warn := c.m.Warn
	band := deadbandFrac * math.Abs(warn)
	for _, v := range c.xs {
		if math.Abs(v-warn) > band {
			return nil
		}
	}
	up := func(v float64) bool { return v >= warn }
	if c.m.Dir == "low" {
		up = func(v float64) bool { return v <= warn }
	}
	cross := 0
	for i := 1; i < len(c.xs); i++ {
		if up(c.xs[i]) != up(c.xs[i-1]) {
			cross++
		}
	}
	if cross < 3 {
		return nil
	}
	var out [][2]string
	if f.Status == "sensor_fault" {
		if f.Pattern != "flatline" || c.st.FlatRun >= len(c.xs)/2 {
			return nil
		}
		cause := CauseOf(c.role, c.metric, "stable", "warning", IsOffHours(c.end), strings.HasPrefix(c.node, "SR-"), false)
		out = append(out, [2]string{"pattern", "stable"}, [2]string{"likely_cause", cause}, [2]string{"fault_kind", ""})
	}
	if f.Status != "warning" {
		out = append(out, [2]string{"status", "warning"})
	}
	if f.EventActive == nil || !*f.EventActive {
		out = append(out, [2]string{"event_active", "true"})
	}
	return out
}

// off-label cause -> a known synonym, else the first keyword match, else the status-consistent default
var postCauseMap = map[string]string{
	"acidic_condition": "water_quality_issue", "alkaline_condition": "water_quality_issue",
	"contamination": "water_quality_issue", "water_contamination": "water_quality_issue",
	"high_tds": "water_quality_issue", "low_ph": "water_quality_issue", "high_ph": "water_quality_issue",
	"leak": "possible_leak", "pump_short_cycling": "pump_cycling", "overflow": "tank_overflow_risk",
	"power_outage": "load_drop_or_outage", "outage": "load_drop_or_outage", "overload": "capacity_limit_throttling",
	"poor_ventilation": "ventilation_insufficient", "occupancy": "occupancy_load",
}

var postCauseKeys = map[string][][2]string{
	"water": {{"acid", "water_quality_issue"}, {"alkal", "water_quality_issue"}, {"ph", "water_quality_issue"},
		{"tds", "water_quality_issue"}, {"contamin", "water_quality_issue"}, {"quality", "water_quality_issue"},
		{"turbid", "water_quality_issue"}, {"leak", "possible_leak"}, {"overflow", "tank_overflow_risk"},
		{"valve", "fill_valve_stuck"}, {"cycl", "pump_cycling"}, {"fill", "tank_filling"}, {"drain", "tank_draining"},
		{"supply", "supply_interruption"}, {"demand", "high_demand"}},
	"power": {{"outage", "load_drop_or_outage"}, {"drop", "load_drop_or_outage"}, {"surge", "load_surge"},
		{"overload", "capacity_limit_throttling"}, {"throttl", "capacity_limit_throttling"},
		{"startup", "equipment_startup"}, {"quality", "power_quality_issue"}, {"harmonic", "power_quality_issue"},
		{"cycl", "cyclic_equipment"}, {"growth", "gradual_load_growth"}},
	"air_quality": {{"ventilat", "ventilation_insufficient"}, {"occupan", "occupancy_load"}, {"outdoor", "outdoor_pollution_ingress"},
		{"emission", "indoor_emission_source"}, {"humid", "humidity_control_issue"}, {"cooling", "hvac_cooling_issue"}},
	"weather": {{"diurnal", "diurnal_cycle"}, {"front", "weather_front"}, {"gust", "gusty_wind"}, {"heat", "heat_buildup"},
		{"cool", "cooling_trend"}},
}

func ruleCause(c *postCtx, f *Finding) [][2]string {
	allowed := agentCauses(c.role)
	if len(allowed) == 0 || contains(allowed, f.LikelyCause) {
		return nil
	}
	if v, ok := postCauseMap[f.LikelyCause]; ok && contains(allowed, v) {
		return [][2]string{{"likely_cause", v}}
	}
	for _, kv := range postCauseKeys[c.role] {
		if strings.Contains(f.LikelyCause, kv[0]) && contains(allowed, kv[1]) {
			return [][2]string{{"likely_cause", kv[1]}}
		}
	}
	if f.Status == "sensor_fault" {
		return [][2]string{{"likely_cause", "sensor_fault"}}
	}
	if nc := postNormalCause[c.role]; f.Status == "normal" && nc != "" {
		return [][2]string{{"likely_cause", nc}}
	}
	return nil
}

// routineV2: training/v2/teacher_v2.routine_rule, water and power branches (the only roles the post-rules
// call it for): (status, cause, true) when the evidence matches a routine.
func routineV2(c *postCtx, p string) (string, string, bool) {
	st, n, end := c.st, len(c.xs), c.end
	t := time.Unix(end, 0).In(IST)
	hr := float64(t.Hour()) + float64(t.Minute())/60
	wd := (int(t.Weekday()) + 6) % 7 // Monday = 0, as Python's weekday()
	if c.role == "water" && c.metric == "level" {
		tl, ok := NodeLimitsV2[c.node]
		if ok && st.Last >= tl.Overflow {
			return "critical", "tank_overflow_risk", true
		}
		if inSet(p, "step_increase", "gradual_increase", "exponential_increase", "throttling") {
			if ok && st.Max >= tl.High {
				return "warning", "tank_overflow_risk", true
			}
			if ok && postFillMinutes(st, n) >= 2*tl.FillMin {
				return "warning", "fill_valve_stuck", true
			}
			return "normal", "tank_filling", true
		}
		if p == "oscillation" && IsOffHours(end) {
			return "warning", "possible_leak", true
		}
		if p == "gradual_decrease" {
			if IsOffHours(end) || postLongDrain(c.xs, st.Noise) {
				return "warning", "possible_leak", true
			}
			return "normal", "tank_draining", true
		}
	}
	if c.role == "water" && (c.metric == "level" || c.metric == "flow") && p == "oscillation" {
		period := 1e9
		if st.ZeroCross > 0 {
			period = float64(2*n*5) / float64(st.ZeroCross)
		}
		if period >= 50 {
			return "normal", "pump_cycling", true
		}
		return "warning", "pump_cycling", true
	}
	if c.role == "power" && c.metric == "power_kw" {
		if !strings.HasPrefix(c.node, "SL-") {
			if p == "oscillation" {
				return "normal", "cyclic_equipment", true
			}
			hm := idxTimeN(end, n, st.MaxJumpIdx)
			tj := float64(int(hm[0]-'0')*10+int(hm[1]-'0')) + float64(int(hm[3]-'0')*10+int(hm[4]-'0'))/60
			half := st.SecondHalf - st.FirstHalf
			step := math.Abs(half) > 0 && math.Abs(st.MaxJump) >= 0.45*math.Abs(half) && (st.MaxJumpSigned > 0) == (half > 0)
			if wd < 5 && step {
				if p == "step_increase" && tj >= 7.0 && tj <= 10.5 {
					return "normal", "equipment_startup", true
				}
				if p == "step_decrease" && tj >= 17.0 && tj <= 21.0 && st.Last >= 0.1*math.Max(st.FirstHalf, 1e-9) {
					return "normal", "normal_load", true
				}
			}
		} else if (p == "gradual_increase" && hr >= 6 && hr < 12) || (p == "gradual_decrease" && hr >= 12 && hr < 19) {
			return "normal", "normal_load", true
		}
	}
	return "", "", false
}

// postFillMinutes: teacher_v2.fill_minutes - the current fill from the window minimum to the end, counted only
// when the maximum is the last reading and the minimum precedes it
func postFillMinutes(st Stats, n int) float64 {
	if st.MaxIdx < n-1 || st.MinIdx >= st.MaxIdx {
		return 0
	}
	return float64((n - 1 - st.MinIdx) * 5)
}

// postLongDrain: the last 3 h fall steadily with no refill - a drop of at least 10x the noise and 5% of the
// level, and no rebound above max(3x noise, 10% of the drop). Mirrored by proofs/2026-10-25_domain_plan/scripts/
// p1_rules.long_drain and training/v2/teacher_v2.long_drain.
func postLongDrain(xs []float64, noise float64) bool {
	n := len(xs)
	if n < postDrainPts {
		return false
	}
	seg := xs[n-postDrainPts:]
	drop := seg[0] - seg[len(seg)-1]
	if drop < math.Max(10*noise, 0.05*math.Abs(seg[0])) || drop <= 0 {
		return false
	}
	lo, rise := seg[0], 0.0
	for _, v := range seg {
		lo = math.Min(lo, v)
		rise = math.Max(rise, v-lo)
	}
	return rise <= math.Max(3*noise, 0.1*drop)
}

// postKeepLeak: a model warning / possible_leak on tank level stays when E9 reports a falling slow drift or
// the window is a long drain (the routine would agree); the relative/routine rules must not downgrade it.
func postKeepLeak(c *postCtx, f *Finding) bool {
	return c.role == "water" && c.metric == "level" && f.LikelyCause == "possible_leak" &&
		(f.Status == "warning" || f.Status == "critical") && (c.e9Fall || postLongDrain(c.xs, c.st.Noise))
}

// postE9Falling: the v2 prompt's "E9 12 h view: ... slow drift -X ..." line has a negative drift.
func postE9Falling(prompt string) bool {
	i := strings.Index(prompt, "\nE9 ")
	if i < 0 {
		return false
	}
	line := prompt[i+1:]
	if j := strings.IndexByte(line, '\n'); j >= 0 {
		line = line[:j]
	}
	return strings.Contains(line, "slow drift -")
}
