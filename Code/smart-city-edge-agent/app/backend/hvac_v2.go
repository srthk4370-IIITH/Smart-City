package main

// v2 HVAC agent, one per AC indoor unit (D1): line-by-line port of training/v2/hvac.py (statistics,
// evidence E1..E8, prompt, teacher rule) plus the v2 history lines from features_v2.go. Prompts are
// byte-identical to training (features_v2_test.go). Used only when the v2 agent is on (agentversion.go);
// the floor-level AC aggregate (AC-KH03, ac_units_on) stays a CPU context signal in both versions.

import (
	"fmt"
	"math"
	"strings"
	"time"
)

const (
	hvBandHi      = 2.0
	hvBandLo      = 3.0
	hvColdAbs     = 24.0
	hvColdHard    = 20.0
	hvHotOcc      = 30.0
	hvCritT       = 34.0
	hvMinPts      = 3
	hvWarnPts     = 6
	hvWarnExcess  = 1.0
	hvRunPts      = 12
	hvNoCoolSlope = -0.3
	hvFastSlope   = -1.2
	hvSCStarts    = 4
	hvSCRun       = 3
	hvSCCrit      = 8
	hvFlatPts     = 24
	hvFlatEps     = 0.05
	hvErrNoise    = 0.8
	hvJumpC       = 2.0
	hvStuckOffUse = 0.5
	hvDriftSlope  = -0.8
	hvDriftDrop   = 2.0
	hvDriftPts    = 30
	hvDriftR2     = 0.85
	hvBiasHot     = 36.0
	hvGridPts     = 12
	hvDropFrac    = 0.25
	hvSatPts      = 6
	hvVacantPts   = 12
	hvSetbackSl   = 0.25
	hvSetbackRise = 0.6
	hvStuckOnSP   = 0.5
	hvTempLo      = 10.0
	hvTempHi      = 45.0
)

// HVACRoomTemp is the v2 HVAC metric spec (hvac.METRICS[("hvac","room_temp")]); its floor (0.3 C) drives E9/E10.
var HVACRoomTemp = lim("C", 1, "30", "34", "both", 0.3, hvTempLo, hvTempHi)

var HVACNormalPatterns = []string{"stable", "normal_cycling", "pull_down", "setback_drift"}
var HVACEventPatterns = []string{"too_hot", "too_cold", "slow_recovery", "no_cooling_effect", "short_cycling",
	"stuck_on", "stuck_off", "running_empty_room", "unit_alarm"}
var HVACFaultPatterns = []string{"flatline", "erratic", "bias_jump", "biased_reading", "calibration_drift", "dropout", "saturation",
	"quantised"}
var HVACPatterns = append(append(append([]string(nil), HVACNormalPatterns...), HVACEventPatterns...), HVACFaultPatterns...)

var HVACFaultKind = map[string]string{"flatline": "stuck", "erratic": "noise", "bias_jump": "bias", "biased_reading": "bias",
	"calibration_drift": "drift", "dropout": "dropout", "saturation": "saturation", "quantised": "quantised"}

var HVACCauses = []string{"normal_operation", "scheduled_off", "high_heat_load", "ac_not_cooling", "overcooling",
	"ac_off_heat_gain", "short_cycling_control", "schedule_or_control_fault", "unit_not_starting",
	"unoccupied_running", "unit_alarm", "sensor_fault"}

var hvacActionOf = map[string]string{
	"normal_operation": "none", "scheduled_off": "none", "high_heat_load": "monitor",
	"ac_not_cooling": "inspect_hvac", "overcooling": "review_schedule", "ac_off_heat_gain": "review_schedule",
	"short_cycling_control": "inspect_hvac", "schedule_or_control_fault": "review_schedule",
	"unit_not_starting": "inspect_hvac", "unoccupied_running": "switch_off_ac", "unit_alarm": "inspect_hvac",
	"sensor_fault": "check_sensor",
}

// HVACActionOf mirrors hvac.action_of. switch_off_ac is a recommendation the operator approves.
func HVACActionOf(cause, status string) string {
	a := hvacActionOf[cause]
	if a == "" {
		a = "monitor"
	}
	if a == "none" && (status == "warning" || status == "critical") {
		return "monitor"
	}
	if a == "monitor" && status == "critical" {
		return "inspect_hvac"
	}
	return a
}

const HVACSystemPrompt = "You are the HVAC agent of a smart-campus edge monitor (IIIT Hyderabad)."

// HVACCtx is one window's context (hvac.py ctx): per-reading setpoint, run state, optional thermostat
// demand, alarm flags, missing-temperature flags and room occupancy; the unit's mode, malfunction code,
// usual schedule (duty, on-fraction per IST hour, TRAIN months) and the window end.
type HVACCtx struct {
	SP      []float64 `json:"sp"`
	On      []int     `json:"on"`
	Thermo  []float64 `json:"thermo"` // nil = n/a
	Mode    int       `json:"mode"`
	Alarm   []int     `json:"alarm"`
	Malf    int       `json:"malf"`
	Missing []bool    `json:"missing"`
	Occ     []int     `json:"occ"` // nil = no occupancy feed ("occupancy n/a", D9)
	Duty    string    `json:"duty"`
	HourOn  []float64 `json:"hour_on"` // nil = schedule n/a
	End     int64     `json:"end"`
}

type hvRun struct{ v, s, l int }

type hvStats struct {
	n                                        int
	last, mx, mn                             float64
	mxI, mnI                                 int
	spLast                                   float64
	trailAbove, trailBelow, aboveTot, belTot int
	onFrac                                   float64
	onNow                                    int
	starts, stops, onRuns                    []int
	runMed                                   float64
	shortest, trailOn, runStart, since       int
	slope, r2, slope12, slopeRun             float64
	spChanges                                [][3]float64
	flatBest, flatStart                      int
	flatOn, noise, jump                      float64
	jumpI                                    int
	jumpQuiet                                bool
	jumpShift                                float64
	thermoFrac                               *float64
	thermoChanges                            int
	missing, firstMissing, sat, satI         int
	alarm                                    bool
	alarmI, malf, mode                       int
	occ                                      []int
	trailVacant, trailOccupied               int
	offHours, working                        bool
	hour                                     int
	duty                                     string
	usualOn                                  *float64
	zc                                       int
	gridK, gridLev, gridCh                   int
}

func hvMean(v []float64) float64 {
	s := 0.0
	for _, x := range v {
		s += x
	}
	return s / float64(len(v))
}

func hvMeanI(v []int) float64 {
	s := 0
	for _, x := range v {
		s += x
	}
	return float64(s) / float64(len(v))
}

func hvMedian(v []float64) float64 { return lrMedian(v) }

// hvSlopeH: OLS slope in C/h of 5-min samples, and r2 (hvac._slope_h).
func hvSlopeH(v []float64) (float64, float64) {
	k := len(v)
	if k < 2 {
		return 0, 0
	}
	tm := float64(k-1) / 2
	ym := hvMean(v)
	var sxx, sxy, sst, sse float64
	for t := range v {
		sxx += (float64(t) - tm) * (float64(t) - tm)
	}
	for t, y := range v {
		sxy += (float64(t) - tm) * (y - ym)
	}
	b := sxy / sxx
	for _, y := range v {
		sst += (y - ym) * (y - ym)
	}
	for t, y := range v {
		e := y - (ym + b*(float64(t)-tm))
		sse += e * e
	}
	r2 := 0.0
	if sst > 1e-12 {
		r2 = 1 - sse/sst
	}
	return b * 12.0, r2
}

func hvRobustNoise(xs []float64) float64 {
	d := make([]float64, 0, len(xs))
	for i := 1; i < len(xs); i++ {
		d = append(d, xs[i]-xs[i-1])
	}
	md := hvMedian(d)
	ad := make([]float64, len(d))
	for i, x := range d {
		ad[i] = math.Abs(x - md)
	}
	return 1.4826 * hvMedian(ad) / math.Sqrt2
}

func hvRuns(bits []int) []hvRun {
	var out []hvRun
	for i := 0; i < len(bits); {
		j := i
		for j < len(bits) && bits[j] == bits[i] {
			j++
		}
		out = append(out, hvRun{bits[i], i, j - i})
		i = j
	}
	return out
}

func hvTrailing(mask []bool) int {
	k := 0
	for i := len(mask) - 1; i >= 0 && mask[i]; i-- {
		k++
	}
	return k
}

func hvLocal(end int64) time.Time { return time.Unix(end, 0).In(IST) }

// hvOffHours: night (22:00-06:00) or Sunday (Saturday is a working day on this campus).
func hvOffHours(end int64) bool {
	t := hvLocal(end)
	return t.Hour() >= 22 || t.Hour() < 6 || t.Weekday() == time.Sunday
}

func hvWorking(end int64) bool {
	t := hvLocal(end)
	return t.Weekday() != time.Sunday && t.Hour() >= 9 && t.Hour() < 19
}

func fmt1(v float64) string { return fmt.Sprintf("%.1f", v) }

func hvGrid(xs []float64) (int, int, int) {
	mask := make([]bool, len(xs))
	for i, v := range xs {
		mask[i] = math.Abs(v-math.RoundToEven(v)) < 0.01
	}
	k := hvTrailing(mask)
	if k == 0 {
		return 0, 0, 0
	}
	tail := make([]float64, k)
	lev := map[float64]bool{}
	for i := range tail {
		tail[i] = math.RoundToEven(xs[len(xs)-k+i])
		lev[tail[i]] = true
	}
	ch := 0
	for i := 1; i < len(tail); i++ {
		if tail[i] != tail[i-1] {
			ch++
		}
	}
	return k, len(lev), ch
}

func hvZeroCross(xs []float64) int {
	m := hvMean(xs)
	c, prev := 0, 0
	for _, v := range xs {
		s := 0
		if v > m+0.1 {
			s = 1
		} else if v < m-0.1 {
			s = -1
		}
		if s != 0 && prev != 0 && s != prev {
			c++
		}
		if s != 0 {
			prev = s
		}
	}
	return c
}

func argmaxF(xs []float64) int {
	k := 0
	for i := range xs {
		if xs[i] > xs[k] {
			k = i
		}
	}
	return k
}

func argminF(xs []float64) int {
	k := 0
	for i := range xs {
		if xs[i] < xs[k] {
			k = i
		}
	}
	return k
}

func hvacStats(xs []float64, c HVACCtx) hvStats {
	n := len(xs)
	sp, on := c.SP, c.On
	above, below := make([]bool, n), make([]bool, n)
	st := hvStats{n: n, last: xs[n-1], mx: maxf(xs), mn: minf(xs), mxI: argmaxF(xs), mnI: argminF(xs), spLast: sp[n-1]}
	for i := 0; i < n; i++ {
		above[i] = xs[i] > sp[i]+hvBandHi && xs[i] >= hvColdAbs
		below[i] = (xs[i] < sp[i]-hvBandLo && xs[i] < hvColdAbs) || xs[i] < hvColdHard
		if above[i] {
			st.aboveTot++
		}
		if below[i] {
			st.belTot++
		}
	}
	st.trailAbove, st.trailBelow = hvTrailing(above), hvTrailing(below)
	var inner []float64
	for _, r := range hvRuns(on) {
		if r.v == 1 && r.s > 0 {
			st.starts = append(st.starts, r.s)
		}
		if r.v == 0 && r.s > 0 {
			st.stops = append(st.stops, r.s)
		}
		if r.v == 1 {
			st.onRuns = append(st.onRuns, r.l)
			if r.s > 0 && r.s+r.l < n {
				inner = append(inner, float64(r.l))
			}
		}
	}
	for i := 1; i < n; i++ {
		if math.Abs(sp[i]-sp[i-1]) >= 0.5 {
			st.spChanges = append(st.spChanges, [3]float64{float64(i), sp[i-1], sp[i]})
		}
	}
	for i := 1; i < n; i++ {
		if on[i] != 0 && on[i-1] == 0 {
			st.runStart = i
		} else if on[i] != 0 && on[i-1] != 0 && sp[i] <= sp[i-1]-1.0 {
			st.runStart = i
		}
	}
	onMask := make([]bool, n)
	for i, v := range on {
		onMask[i] = v == 1
	}
	st.trailOn = hvTrailing(onMask)
	if st.trailOn > 0 {
		st.since = n - st.runStart
	}
	k12 := hvRunPts
	if n < k12 {
		k12 = n
	}
	st.slope12, _ = hvSlopeH(xs[n-k12:])
	st.slope, st.r2 = hvSlopeH(xs)
	seg := xs[n-2:]
	if st.since >= 2 {
		seg = xs[st.runStart:]
	}
	if len(seg) > hvRunPts {
		seg = seg[:hvRunPts]
	}
	st.slopeRun, _ = hvSlopeH(seg)
	st.flatBest, st.flatStart = 1, 0
	cur := 1
	for i := 1; i < n; i++ {
		if math.Abs(xs[i]-xs[i-1]) <= hvFlatEps {
			cur++
			if cur > st.flatBest {
				st.flatBest, st.flatStart = cur, i-cur+1
			}
		} else {
			cur = 1
		}
	}
	if st.flatBest > 1 {
		st.flatOn = hvMeanI(on[st.flatStart : st.flatStart+st.flatBest])
	}
	diffs := make([]float64, n-1)
	for i := 1; i < n; i++ {
		diffs[i-1] = xs[i] - xs[i-1]
	}
	j := 0
	for i := range diffs {
		if math.Abs(diffs[i]) > math.Abs(diffs[j]) {
			j = i
		}
	}
	j++
	st.jumpQuiet = true
	for k := imax(0, j-2); k < n && k < j+3; k++ {
		if !(on[k] == 1 && math.Abs(sp[k]-sp[j]) < 0.5) {
			st.jumpQuiet = false
			break
		}
	}
	pre, post := xs[imax(0, j-6):j], xs[j:imin(n, j+6)]
	st.jump, st.jumpI = diffs[j-1], j
	if len(pre) > 0 && len(post) > 0 {
		st.jumpShift = hvMean(post) - hvMean(pre)
	}
	if len(inner) > 0 {
		st.runMed = hvMedian(inner)
	} else if len(st.onRuns) > 0 {
		mx := 0
		for _, l := range st.onRuns {
			mx = imax(mx, l)
		}
		st.runMed = float64(mx)
	}
	if len(st.onRuns) > 0 {
		st.shortest = st.onRuns[0]
		for _, l := range st.onRuns {
			st.shortest = imin(st.shortest, l)
		}
	}
	st.onFrac = hvMeanI(on)
	st.onNow = on[n-1]
	st.noise = math.Max(hvRobustNoise(xs), hvRobustNoise(xs[n-imin(hvRunPts, n):]))
	if len(c.Thermo) > 0 {
		f := hvMean(c.Thermo)
		st.thermoFrac = &f
		for i := 1; i < n; i++ {
			if (c.Thermo[i] >= 0.5) != (c.Thermo[i-1] >= 0.5) {
				st.thermoChanges++
			}
		}
	}
	st.firstMissing, st.satI, st.alarmI = -1, -1, -1
	for i, m := range c.Missing {
		if m {
			st.missing++
			if st.firstMissing < 0 {
				st.firstMissing = i
			}
		}
	}
	for i, v := range xs {
		if v <= hvTempLo+1e-6 || v >= hvTempHi-1e-6 {
			st.sat++
			if st.satI < 0 {
				st.satI = i
			}
		}
	}
	for i, a := range c.Alarm {
		if a != 0 {
			st.alarm = true
			if st.alarmI < 0 {
				st.alarmI = i
			}
		}
	}
	st.malf, st.mode = c.Malf, c.Mode
	if len(c.Occ) > 0 {
		st.occ = c.Occ
		vac, occ := make([]bool, len(c.Occ)), make([]bool, len(c.Occ))
		for i, v := range c.Occ {
			vac[i], occ[i] = v == 0, v == 1
		}
		st.trailVacant, st.trailOccupied = hvTrailing(vac), hvTrailing(occ)
	}
	st.offHours, st.working, st.hour = hvOffHours(c.End), hvWorking(c.End), hvLocal(c.End).Hour()
	st.duty = c.Duty
	if st.duty == "" {
		st.duty = "office"
	}
	if len(c.HourOn) == 24 {
		u := c.HourOn[st.hour]
		st.usualOn = &u
	}
	st.zc = hvZeroCross(xs)
	st.gridK, st.gridLev, st.gridCh = hvGrid(xs)
	return st
}

func imin(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// hvacEvidence: E1..E8 (hvac.evidence_items).
func hvacEvidence(xs []float64, c HVACCtx, st hvStats) []Evidence {
	n := st.n
	T := func(i int) string { return idxTimeN(c.End, n, i) }
	sp := st.spLast
	ev := []Evidence{
		{"E1", "last", fmt.Sprintf("room now %s C, setpoint %s C (band %s-%s)", fmt1(st.last), fmt1(sp), fmt1(sp-hvBandLo), fmt1(sp+hvBandHi))},
		{"E2", "range", fmt.Sprintf("max %s C at %s, min %s C at %s", fmt1(st.mx), T(st.mxI), fmt1(st.mn), T(st.mnI))},
	}
	var e3 string
	switch {
	case st.trailAbove > 0:
		e3 = fmt.Sprintf("above band for last %d min (since %s)", 5*st.trailAbove, T(n-st.trailAbove))
	case st.trailBelow > 0:
		e3 = fmt.Sprintf("below band for last %d min (since %s)", 5*st.trailBelow, T(n-st.trailBelow))
	default:
		e3 = fmt.Sprintf("inside band now; above band %d min, below %d min in window", 5*st.aboveTot, 5*st.belTot)
	}
	ev = append(ev, Evidence{"E3", "band", e3})
	e4 := fmt.Sprintf("trend %+.1f C/h (r2 %.2f), last hour %+.1f C/h", st.slope, st.r2, st.slope12)
	if st.runStart > 0 && st.trailOn > 0 {
		e4 += fmt.Sprintf(", since start %s (from %s C) %+.1f C/h", T(st.runStart), fmt1(xs[st.runStart]), st.slopeRun)
	}
	ev = append(ev, Evidence{"E4", "trend", e4})
	mode := map[int]string{1: "cool", 3: "fan", 5: "dry"}[st.mode]
	if mode == "" {
		mode = "cool"
	}
	onPts := 0
	for _, v := range c.On {
		onPts += v
	}
	e5 := fmt.Sprintf("AC on %d/%d samples, mode %s, starts %d, stops %d", onPts, n, mode, len(st.starts), len(st.stops))
	if len(st.starts) > 0 {
		e5 += ", last start " + T(st.starts[len(st.starts)-1])
	}
	if st.trailOn > 0 {
		e5 += fmt.Sprintf(", running %d min", 5*st.since)
	}
	ev = append(ev, Evidence{"E5", "run", e5})
	var e6 string
	if len(st.onRuns) > 0 && onPts > 0 {
		e6 = fmt.Sprintf("on-runs shortest %d min, median %d min", 5*st.shortest, int(5*st.runMed))
	} else {
		e6 = "no on-runs"
	}
	if st.thermoFrac != nil {
		e6 += fmt.Sprintf("; thermo on %.0f%%, %d changes", *st.thermoFrac*100, st.thermoChanges)
	} else {
		e6 += "; thermo n/a"
	}
	ev = append(ev, Evidence{"E6", "cycles", e6})
	var e7 string
	if len(st.spChanges) > 0 {
		l := st.spChanges[len(st.spChanges)-1]
		e7 = fmt.Sprintf("setpoint changes %d, last %s -> %s C at %s", len(st.spChanges), fmt1(l[1]), fmt1(l[2]), T(int(l[0])))
	} else {
		e7 = fmt.Sprintf("setpoint unchanged at %s C", fmt1(sp))
	}
	e7 += fmt.Sprintf("; temp flat %d min max, largest 5-min step %+.1f C at %s", 5*st.flatBest, st.jump, T(st.jumpI))
	if st.gridK >= hvGridPts {
		e7 += fmt.Sprintf("; whole-degree readings for last %d min", 5*st.gridK)
	}
	ev = append(ev, Evidence{"E7", "setpoint", e7})
	var occ string
	switch {
	case st.occ == nil:
		occ = "occupancy n/a"
	case st.trailVacant > 0:
		occ = fmt.Sprintf("room vacant for last %d min", 5*st.trailVacant)
	default:
		s := 0
		for _, v := range st.occ {
			s += v
		}
		occ = fmt.Sprintf("room occupied %.0f%% of window", float64(s)/float64(n)*100)
	}
	usual := "schedule n/a"
	if st.usualOn != nil {
		usual = fmt.Sprintf("usually on %.0f%% at this hour", *st.usualOn*100)
	}
	e8 := fmt.Sprintf("%s; %s (%s unit); end %s %s", occ, usual, st.duty, hvLocal(c.End).Format("Mon"), T(n-1))
	if st.offHours {
		e8 += " off-hours"
	}
	e8 += fmt.Sprintf("; missing %d/%d; alarm ", st.missing, n)
	if st.alarm {
		e8 += fmt.Sprintf("code %d", st.malf)
	} else {
		e8 += "none"
	}
	ev = append(ev, Evidence{"E8", "context", e8})
	return ev
}

// BuildHVACPromptV2 is the HVAC agent prompt (hvac.user_prompt + features_v2.history_items + the v2
// system rules and schema hint, as hvac_adapter.make_examples builds it). xs is the room-temperature
// window (N = len(xs)), c its context (aligned with xs), hist the room-temperature history ending at the
// same reading (<= 144 points; nil = xs).
func BuildHVACPromptV2(node, location string, xs []float64, c HVACCtx, hist []float64) AgentInputV2 {
	n := len(xs)
	if len(hist) < n {
		hist = xs
	}
	endT := hvLocal(c.End)
	startT := endT.Add(-time.Duration(5*(n-1)) * time.Minute)
	st := hvacStats(xs, c)
	lines := []string{"NODE: " + node + " (" + location + ")", "METRIC: room_temp [C] with AC state and setpoint",
		fmt.Sprintf("LIMITS: comfort band setpoint -%g/+%g C; warning above 30, critical above 34", hvBandLo, hvBandHi),
		fmt.Sprintf("WINDOW: %s -> %s IST, %d x 5 min", startT.Format("Mon 02 Jan 15:04"), endT.Format("15:04"), n)}
	k := n / 2
	ds := make([]string, k)
	var state strings.Builder
	for i := 0; i < k; i++ {
		ds[i] = fmt1(hvMean(xs[i*2 : (i+1)*2]))
		if hvMeanI(c.On[i*2:(i+1)*2]) >= 0.5 {
			state.WriteByte('1')
		} else {
			state.WriteByte('0')
		}
	}
	lines = append(lines, "ROOM TEMP (10-min means): "+strings.Join(ds, " "), "AC STATE (10-min, 1=on): "+state.String(), "EVIDENCE:")
	ev := hvacEvidence(xs, c, st)
	hv, info := HistoryItemsV2("hvac", "room_temp", HVACRoomTemp, hist, c.End)
	ev = append(ev, hv...)
	for _, e := range ev {
		lines = append(lines, e.ID+" "+e.Text)
	}
	system := HVACSystemPrompt + SystemRulesV2(n) + " " + OutputSchemaHintV2("hvac")
	return AgentInputV2{AgentInput: AgentInput{Prompt: Llama3Prompt(system, strings.Join(lines, "\n")), Evidence: ev}, N: n, Hist: info}
}

// HVACDescribe mirrors hvac.describe: SR-AC-KH02-12 -> "KH building, level 02, AC indoor unit 12".
func HVACDescribe(node string) string {
	p := strings.Split(node, "-")
	if len(p) < 4 || len(p[2]) < 2 {
		return node
	}
	return fmt.Sprintf("%s building, level %s, AC indoor unit %s", p[2][:2], p[2][2:], p[3])
}

// isHVACUnit: a per-unit HVAC node (SR-AC-<building><level>-<unit>), not the floor aggregate.
func isHVACUnit(node string) bool { return strings.HasPrefix(node, "SR-AC-") }

// ---------------------------------------------------------------- teacher rule (Mode 1 for HVAC units)

func hvContains(list []string, s string) bool { return contains(list, s) }

// ClassifyHVAC mirrors hvac.classify_hvac: (pattern, onset index, event active).
func ClassifyHVAC(xs []float64, c HVACCtx, st hvStats) (string, int, bool) {
	n := st.n
	if st.sat >= hvSatPts {
		return "saturation", st.satI, xs[n-1] <= hvTempLo+1e-6 || xs[n-1] >= hvTempHi-1e-6
	}
	if float64(st.missing) >= hvDropFrac*float64(n) {
		return "dropout", st.firstMissing, c.Missing[n-1]
	}
	if st.alarm {
		return "unit_alarm", st.alarmI, c.Alarm[n-1] != 0
	}
	fb, fs := st.flatBest, st.flatStart
	if fb >= hvFlatPts && st.flatOn >= 0.5 && st.mode == 1 {
		return "flatline", fs, fs+fb == n
	}
	if st.gridK >= hvGridPts && st.gridLev >= 2 && st.gridCh >= 3 {
		return "quantised", n - st.gridK, true
	}
	if st.noise >= hvErrNoise {
		return "erratic", 0, true
	}
	if math.Abs(st.jump) >= hvJumpC && st.jumpQuiet && st.mode == 1 && math.Abs(st.jumpShift) >= 0.75*hvJumpC && n-st.jumpI >= hvMinPts {
		return "bias_jump", st.jumpI, true
	}
	if st.mode == 1 && st.trailOn >= hvRunPts && hvMedian(xs[n-st.trailOn:]) >= hvBiasHot {
		return "biased_reading", n - st.trailOn, true
	}
	t := st.hour
	if st.onFrac == 0 && t >= 11 && t < 18 && !st.offHours {
		k := hvDriftPts
		for k < n {
			s, r2 := hvSlopeH(xs[n-(k+1):])
			if s > hvDriftSlope || r2 < hvDriftR2 {
				break
			}
			k++
		}
		if k <= n {
			s, r2 := hvSlopeH(xs[n-k:])
			if s <= hvDriftSlope && r2 >= hvDriftR2 && xs[n-k]-xs[n-1] >= hvDriftDrop {
				return "calibration_drift", n - k, true
			}
		}
	}
	per4h := float64(len(st.starts)) * 48.0 / float64(n)
	if per4h >= hvSCStarts && st.runMed <= hvSCRun {
		return "short_cycling", st.starts[0], true
	}
	if st.occ != nil && st.onNow != 0 && st.trailVacant >= hvVacantPts && st.trailOn >= hvVacantPts {
		return "running_empty_room", n - imin(st.trailVacant, st.trailOn), true
	}
	if st.trailOn == n && st.offHours && st.duty == "office" && st.last <= st.spLast+hvStuckOnSP &&
		(st.usualOn == nil || *st.usualOn < 0.2 || hvLocal(c.End).Weekday() == time.Sunday) {
		return "stuck_on", 0, true
	}
	usual := 0.0
	if st.usualOn != nil {
		usual = *st.usualOn
	}
	if st.onFrac == 0 && st.working && st.duty != "idle" && usual >= hvStuckOffUse && st.trailAbove >= hvMinPts {
		return "stuck_off", n - st.trailAbove, true
	}
	cooling := st.onNow != 0 && st.mode == 1
	if cooling && st.trailBelow >= hvMinPts {
		return "too_cold", n - st.trailBelow, true
	}
	if cooling && st.trailAbove >= hvMinPts {
		ta := st.trailAbove
		if imin(st.since, ta) >= hvRunPts {
			if st.slope12 >= hvNoCoolSlope {
				return "no_cooling_effect", n - imin(st.since, ta), true
			}
			if st.slope12 > hvFastSlope {
				return "slow_recovery", st.runStart, true
			}
			return "pull_down", st.runStart, true
		}
		if st.runStart > 0 && st.since >= hvMinPts && st.slopeRun <= hvFastSlope {
			return "pull_down", st.runStart, true
		}
		return "too_hot", n - ta, true
	}
	if cooling && st.runStart > 0 && st.since >= hvMinPts && xs[st.runStart] > c.SP[st.runStart]+hvBandHi {
		return "pull_down", st.runStart, false
	}
	if st.onNow == 0 {
		if st.occ != nil && st.trailOccupied >= hvWarnPts {
			hot := make([]bool, n)
			for i, v := range xs {
				hot[i] = v >= hvHotOcc
			}
			if h := hvTrailing(hot); h >= hvMinPts {
				return "too_hot", n - h, true
			}
		}
		k := n
		if len(st.stops) > 0 && st.trailOn == 0 {
			k = n - st.stops[len(st.stops)-1]
		}
		s := 0.0
		if k >= hvRunPts {
			s, _ = hvSlopeH(xs[n-k:])
		}
		if k >= hvRunPts && s >= hvSetbackSl && xs[n-1]-minf(xs[n-k:]) >= hvSetbackRise && (k < n || st.offHours || !st.working) {
			return "setback_drift", n - k, true
		}
	}
	if cooling && st.onFrac >= 0.9 && st.trailAbove == 0 {
		if st.thermoChanges >= 4 || (st.zc >= 6 && st.mx-st.mn >= 0.4) {
			return "normal_cycling", 0, true
		}
	}
	return "stable", 0, false
}

// HVACStatusOf mirrors hvac.status_of.
func HVACStatusOf(pattern string, xs []float64, c HVACCtx, st hvStats, onset int) string {
	n := st.n
	age := n - onset
	if hvContains(HVACFaultPatterns, pattern) {
		return "sensor_fault"
	}
	if hvContains(HVACNormalPatterns, pattern) {
		return "normal"
	}
	switch pattern {
	case "too_hot":
		var excess float64
		if st.onNow != 0 {
			excess = math.Inf(-1)
			for i := onset; i < n; i++ {
				excess = math.Max(excess, xs[i]-c.SP[i]-hvBandHi)
			}
		} else {
			excess = maxf(xs[onset:]) - hvHotOcc + hvWarnExcess
		}
		if age >= hvRunPts && (maxf(xs[onset:]) >= hvCritT+1 || excess >= 4.0) {
			return "critical"
		}
		if age >= hvWarnPts && excess >= hvWarnExcess {
			return "warning"
		}
		return "normal"
	case "too_cold":
		if age >= hvWarnPts && minf(xs[onset:]) <= 18.0 {
			return "critical"
		}
		def := math.Inf(-1)
		for i := onset; i < n; i++ {
			def = math.Max(def, math.Min(c.SP[i]-hvBandLo, hvColdAbs)-xs[i])
		}
		if age >= hvWarnPts && (def >= hvWarnExcess || minf(xs[onset:]) < hvColdHard) {
			return "warning"
		}
		return "normal"
	case "no_cooling_effect":
		if st.last >= 32.0 || st.slope12 >= 0.5 {
			return "critical"
		}
		return "warning"
	case "short_cycling":
		if float64(len(st.starts))*48.0/float64(n) >= hvSCCrit {
			return "critical"
		}
		return "warning"
	case "stuck_off":
		if st.last >= hvCritT {
			return "critical"
		}
		return "warning"
	}
	return "warning"
}

// HVACCauseOf mirrors hvac.cause_of.
func HVACCauseOf(pattern string, st hvStats) string {
	if hvContains(HVACFaultPatterns, pattern) {
		return "sensor_fault"
	}
	switch pattern {
	case "stable":
		if st.onFrac > 0 {
			return "normal_operation"
		}
		return "scheduled_off"
	case "too_hot":
		if st.onNow != 0 {
			return "high_heat_load"
		}
		return "ac_off_heat_gain"
	}
	return map[string]string{"normal_cycling": "normal_operation", "pull_down": "normal_operation", "setback_drift": "scheduled_off",
		"too_cold": "overcooling", "slow_recovery": "high_heat_load", "no_cooling_effect": "ac_not_cooling",
		"short_cycling": "short_cycling_control", "stuck_on": "schedule_or_control_fault",
		"stuck_off": "unit_not_starting", "running_empty_room": "unoccupied_running", "unit_alarm": "unit_alarm"}[pattern]
}

var hvBaseConf = map[string]float64{"stable": 0.92, "normal_cycling": 0.85, "pull_down": 0.85, "setback_drift": 0.8, "too_hot": 0.8,
	"too_cold": 0.8, "slow_recovery": 0.75, "no_cooling_effect": 0.82, "short_cycling": 0.85,
	"stuck_on": 0.7, "stuck_off": 0.7, "running_empty_room": 0.75, "unit_alarm": 0.95,
	"flatline": 0.85, "erratic": 0.85, "bias_jump": 0.8, "biased_reading": 0.85, "calibration_drift": 0.65,
	"dropout": 0.9, "saturation": 0.92, "quantised": 0.8}

// HVACRuleFinding is the deterministic HVAC finding (Mode 1 / event gate / fallback) for one unit window.
func HVACRuleFinding(xs []float64, c HVACCtx) Finding {
	st := hvacStats(xs, c)
	pattern, onset, active := ClassifyHVAC(xs, c, st)
	status := HVACStatusOf(pattern, xs, c, st, onset)
	cause := HVACCauseOf(pattern, st)
	n := st.n
	conf := hvBaseConf[pattern]
	if pattern != "stable" && pattern != "unit_alarm" && pattern != "dropout" {
		conf -= 0.25 * math.Max(0, 1-float64(n-onset)/12.0)
	}
	conf = math.Round(math.Min(0.97, math.Max(0.4, conf))*100) / 100
	ev := hvacEvidence(xs, c, st)
	obs := []string{fmt.Sprintf("Room %s C against setpoint %s C; %s [E1,E3]", fmt1(st.last), fmt1(st.spLast), ev[2].Text)}
	if pattern != "stable" {
		obs = append(obs, fmt.Sprintf("%s since %s [E4,E5]", strings.ReplaceAll(pattern, "_", " "), idxTimeN(c.End, n, onset)))
	}
	f := mkFinding(pattern, status, obs, cause, conf, HVACActionOf(cause, status))
	f.EventActive = &active
	f.Onset = idxTimeN(c.End, n, onset)
	if status == "sensor_fault" {
		f.FaultKind = HVACFaultKind[pattern]
	}
	return f
}
