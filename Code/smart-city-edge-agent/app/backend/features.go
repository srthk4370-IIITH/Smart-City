package main

// Line-by-line port of training/features.py. Prompt text MUST stay byte-identical to training.

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"time"
)

const (
	Window     = 48
	StepMin    = 5
	Downsample = 24
)

var IST = time.FixedZone("IST", 5*3600+1800)

var Roles = []string{"air_quality", "water", "power", "occupancy", "weather"}

type Metric struct {
	Unit       string
	Dec        int
	Warn, Crit float64
	WarnS      string // exactly as Python prints the threshold
	CritS      string
	HasLimits  bool
	Dir        string
	Floor      float64
	Lo, Hi     float64
}

func lim(unit string, dec int, warn, crit string, dir string, floor, lo, hi float64) Metric {
	m := Metric{Unit: unit, Dec: dec, Dir: dir, Floor: floor, Lo: lo, Hi: hi}
	if warn != "" {
		m.HasLimits = true
		m.WarnS, m.CritS = warn, crit
		m.Warn, _ = strconv.ParseFloat(warn, 64)
		m.Crit, _ = strconv.ParseFloat(crit, 64)
	}
	return m
}

var Metrics = map[string]Metric{
	"air_quality/co2":  lim("ppm", 0, "1000", "1500", "high", 40, 250, 5000),
	"air_quality/pm25": lim("ug/m3", 1, "60", "120", "high", 6, 0, 1000),
	"air_quality/pm10": lim("ug/m3", 1, "100", "250", "high", 10, 0, 1000),
	"air_quality/temp": lim("C", 1, "30", "34", "high", 0.6, 5, 55),
	"air_quality/rh":   lim("%", 1, "70", "85", "high", 3, 1, 100),
	"water/level":      lim("level", 1, "", "", "low", 4, 0, 500),
	"water/flow":       lim("m3/h", 2, "", "", "both", 0.4, 0, 40),
	"water/tds":        lim("ppm", 0, "500", "1000", "high", 15, 0, 1000),
	"water/ph":         lim("pH", 2, "8.5", "9.0", "both", 0.25, 0, 14),
	"power/power_kw":   lim("kW", 2, "", "", "both", 0, 0, 2000),
	"power/pf":         lim("", 3, "0.85", "0.7", "low", 0.03, 0, 1),
	"weather/temp":     lim("C", 1, "38", "42", "high", 0.8, 5, 50),
	"weather/rh":       lim("%", 1, "90", "97", "high", 4, 1, 100),
	"weather/wind":     lim("m/s", 2, "10", "15", "high", 0.6, 0, 44),
	"occupancy/occ":    lim("0/1", 0, "", "", "high", 0, 0, 1),
}

var ContPatterns = []string{"stable", "spike", "dip", "gradual_increase", "gradual_decrease", "step_increase",
	"step_decrease", "exponential_increase", "oscillation", "throttling", "flatline", "erratic"}
var OccPatterns = []string{"vacant", "occupied", "arrival", "departure", "intermittent", "off_hours_presence"}

var Causes = map[string][]string{
	"air_quality": {"normal_conditions", "occupancy_load", "ventilation_insufficient", "outdoor_pollution_ingress",
		"indoor_emission_source", "hvac_cooling_issue", "humidity_control_issue", "sensor_fault"},
	"water": {"normal_usage", "high_demand", "possible_leak", "tank_filling", "tank_draining", "supply_interruption",
		"pump_cycling", "water_quality_issue", "sensor_fault"},
	"power": {"normal_load", "load_surge", "equipment_startup", "load_drop_or_outage", "capacity_limit_throttling",
		"gradual_load_growth", "cyclic_equipment", "power_quality_issue", "sensor_fault"},
	"weather": {"normal_weather", "heat_buildup", "cooling_trend", "weather_front", "gusty_wind", "diurnal_cycle",
		"sensor_fault"},
	"occupancy": {"vacant", "normal_occupancy", "arrival", "departure", "intermittent_presence",
		"off_hours_presence", "sensor_fault"},
}
var Actions = []string{"none", "monitor", "inspect_ventilation", "inspect_hvac", "check_sensor", "inspect_water_system",
	"inspect_electrical", "review_schedule", "request_facility_review"}

// ---------------------------------------------------------------- statistics
func mean(xs []float64) float64 {
	s := 0.0
	for _, x := range xs {
		s += x
	}
	return s / float64(len(xs))
}

func stdev(xs []float64) float64 {
	m := mean(xs)
	s := 0.0
	for _, x := range xs {
		s += (x - m) * (x - m)
	}
	return math.Sqrt(s / float64(len(xs)))
}

func sma(xs []float64, n int) float64 { return mean(xs[len(xs)-n:]) }

func ema(xs []float64, n int) float64 {
	a := 2.0 / float64(n+1)
	e := xs[0]
	for _, x := range xs[1:] {
		e = a*x + (1-a)*e
	}
	return e
}

func linfit(xs []float64) (float64, float64, float64) {
	n := len(xs)
	tm := float64(n-1) / 2.0
	ym := mean(xs)
	sxx, sxy := 0.0, 0.0
	for t := 0; t < n; t++ {
		sxx += (float64(t) - tm) * (float64(t) - tm)
		sxy += (float64(t) - tm) * (xs[t] - ym)
	}
	b := sxy / sxx
	a := ym - b*tm
	sst, sse := 0.0, 0.0
	for t, y := range xs {
		sst += (y - ym) * (y - ym)
		r := y - (a + b*float64(t))
		sse += r * r
	}
	r2 := 0.0
	if sst > 1e-12 {
		r2 = 1.0 - sse/sst
	}
	return a, b, r2
}

func quadCurvature(xs []float64) float64 {
	n := len(xs)
	k := n / 3
	s1 := (xs[k-1] - xs[0]) / float64(k-1)
	s3 := (xs[n-1] - xs[n-k]) / float64(k-1)
	return s3 - s1
}

func zeroCrossings(xs []float64) int {
	a, b, _ := linfit(xs)
	r := make([]float64, len(xs))
	for t, y := range xs {
		r[t] = y - (a + b*float64(t))
	}
	s := stdev(r)
	if s < 1e-9 {
		return 0
	}
	c, prev := 0, 0
	for _, v := range r {
		sg := 0
		if v > 0.3*s {
			sg = 1
		} else if v < -0.3*s {
			sg = -1
		}
		if sg != 0 {
			if prev != 0 && sg != prev {
				c++
			}
			prev = sg
		}
	}
	return c
}

func longestFlatRun(xs []float64, eps float64) int {
	best, cur := 1, 1
	for i := 1; i < len(xs); i++ {
		if math.Abs(xs[i]-xs[i-1]) <= eps {
			cur++
			if cur > best {
				best = cur
			}
		} else {
			cur = 1
		}
	}
	return best
}

func topPlateauRun(xs []float64, tol float64) int {
	mx := maxf(xs)
	run := 0
	for i := len(xs) - 1; i >= 0; i-- {
		if mx-xs[i] <= tol {
			run++
		} else {
			break
		}
	}
	return run
}

func maxf(xs []float64) float64 {
	m := xs[0]
	for _, x := range xs {
		if x > m {
			m = x
		}
	}
	return m
}

func minf(xs []float64) float64 {
	m := xs[0]
	for _, x := range xs {
		if x < m {
			m = x
		}
	}
	return m
}

func downsample(xs []float64) []float64 {
	step := len(xs) / Downsample
	out := make([]float64, Downsample)
	for i := 0; i < Downsample; i++ {
		out[i] = mean(xs[i*step : (i+1)*step])
	}
	return out
}

// Fmt mirrors Python: dec==0 -> str(int(round(v))) (banker's rounding), else f"{v:.{dec}f}"
func Fmt(v float64, dec int) string {
	if dec == 0 {
		return strconv.FormatInt(int64(math.RoundToEven(v)), 10)
	}
	return strconv.FormatFloat(v, 'f', dec, 64)
}

func sgn(v float64, dec int) string { return fmt.Sprintf("%+.*f", dec, v) }

func imax(a, b int) int {
	if a > b {
		return a
	}
	return b
}

type Stats struct {
	Last, Mean, Min, Max, Std, SMA1h, EMA1h, SlopePerH, R2, FirstHalf, SecondHalf, Curvature float64
	MaxJump, MaxJumpSigned, Noise, Range                                                     float64
	MaxJumpIdx, MaxIdx, MinIdx, ZeroCross, FlatRun, PlateauRun                               int
}

func ComputeStats(xs []float64, dec int) Stats {
	n := len(xs)
	_, b, r2 := linfit(xs)
	diffs := make([]float64, n-1)
	for i := 1; i < n; i++ {
		diffs[i-1] = xs[i] - xs[i-1]
	}
	ji := 0
	for i := range diffs {
		if math.Abs(diffs[i]) > math.Abs(diffs[ji]) {
			ji = i
		}
	}
	mxI, mnI := 0, 0
	for i := range xs {
		if xs[i] > xs[mxI] {
			mxI = i
		}
		if xs[i] < xs[mnI] {
			mnI = i
		}
	}
	eps := math.Max(1e-9, math.Pow(10, float64(-dec))*0.5)
	noise := 0.0
	if n > 2 {
		noise = stdev(diffs) / math.Sqrt(2)
	}
	mx := maxf(xs)
	tol := eps
	if mx != 0 {
		tol = 0.01 * math.Abs(mx)
	}
	tol = math.Max(eps, tol)
	return Stats{
		Last: xs[n-1], Mean: mean(xs), Min: minf(xs), Max: mx, Std: stdev(xs),
		SMA1h: sma(xs, 12), EMA1h: ema(xs, 12), SlopePerH: b * 12.0, R2: r2,
		FirstHalf: mean(xs[:n/2]), SecondHalf: mean(xs[n/2:]), Curvature: quadCurvature(xs) * 12.0,
		MaxJump: math.Abs(diffs[ji]), MaxJumpIdx: ji + 1, MaxJumpSigned: diffs[ji],
		MaxIdx: mxI, MinIdx: mnI, Noise: noise, Range: mx - minf(xs),
		ZeroCross: zeroCrossings(xs), FlatRun: longestFlatRun(xs, eps), PlateauRun: topPlateauRun(xs, tol),
	}
}

type OccStats struct {
	OccupiedFrac             float64
	Toggles, FirstOn, LastOn int
	Last, First              float64
}

func ComputeOccStats(xs []float64) OccStats {
	t := 0
	for i := 1; i < len(xs); i++ {
		if xs[i] != xs[i-1] {
			t++
		}
	}
	first, last := -1, -1
	for i, v := range xs {
		if v >= 0.5 {
			if first < 0 {
				first = i
			}
			last = i
		}
	}
	return OccStats{OccupiedFrac: mean(xs), Toggles: t, FirstOn: first, LastOn: last, Last: xs[len(xs)-1], First: xs[0]}
}

func IdxTime(end int64, idx int) string {
	t := end - int64(Window-1-idx)*StepMin*60
	return time.Unix(t, 0).In(IST).Format("15:04")
}

func IsOffHours(end int64) bool {
	h := time.Unix(end, 0).In(IST).Hour()
	return h >= 22 || h < 6
}

// ---------------------------------------------------------------- prompt
var SystemPrompts = map[string]string{
	"air_quality": "You are the Air Quality agent of a smart-campus edge monitor (IIIT Hyderabad).",
	"water":       "You are the Water agent of a smart-campus edge monitor (IIIT Hyderabad).",
	"power":       "You are the Power agent of a smart-campus edge monitor (IIIT Hyderabad).",
	"occupancy":   "You are the Occupancy agent of a smart-campus edge monitor (IIIT Hyderabad).",
	"weather":     "You are the Weather agent of a smart-campus edge monitor (IIIT Hyderabad).",
}

const SystemRules = " You receive a 4-hour window of one sensor metric (5-minute samples) with precomputed statistics." +
	" Identify the pattern, judge severity, explain what you notice using only the given numbers, and cite" +
	" evidence ids (E1..E8) that support each observation. Never invent values. Never order physical" +
	" actuation; recommend at most an inspection action. Reply with one JSON object only."

type Evidence struct {
	ID, Stat, Text string
}

func EvidenceItems(role string, st Stats, os OccStats, end int64, dec int, unit string) []Evidence {
	u := ""
	if unit != "" {
		u = " " + unit
	}
	if role == "occupancy" {
		fo, lo := "never", "never"
		if os.FirstOn >= 0 {
			fo = IdxTime(end, os.FirstOn)
		}
		if os.LastOn >= 0 {
			lo = IdxTime(end, os.LastOn)
		}
		off := ""
		if IsOffHours(end) {
			off = " (off-hours)"
		}
		return []Evidence{
			{"E1", "last", fmt.Sprintf("current state = %d", int(os.Last))},
			{"E2", "occupied_frac", fmt.Sprintf("occupied fraction = %.2f", os.OccupiedFrac)},
			{"E3", "toggles", fmt.Sprintf("state changes = %d", os.Toggles)},
			{"E4", "first_on", "first occupied at " + fo},
			{"E5", "last_on", "last occupied at " + lo},
			{"E6", "time", "window end " + IdxTime(end, Window-1) + off},
		}
	}
	d1 := imax(dec, 1)
	return []Evidence{
		{"E1", "last", fmt.Sprintf("last = %s%s", Fmt(st.Last, dec), u)},
		{"E2", "max", fmt.Sprintf("max = %s%s at %s", Fmt(st.Max, dec), u, IdxTime(end, st.MaxIdx))},
		{"E3", "min", fmt.Sprintf("min = %s%s at %s", Fmt(st.Min, dec), u, IdxTime(end, st.MinIdx))},
		{"E4", "slope", fmt.Sprintf("trend = %s%s/h (r2 %.2f)", sgn(st.SlopePerH, d1), u, st.R2)},
		{"E5", "max_jump", fmt.Sprintf("largest 5-min change = %s%s at %s", sgn(st.MaxJumpSigned, d1), u, IdxTime(end, st.MaxJumpIdx))},
		{"E6", "sma", fmt.Sprintf("SMA 1h = %s, EMA 1h = %s, mean 4h = %s%s", Fmt(st.SMA1h, dec), Fmt(st.EMA1h, dec), Fmt(st.Mean, dec), u)},
		{"E7", "shape", fmt.Sprintf("halves %s -> %s, curvature %s/h, oscillation crossings %d", Fmt(st.FirstHalf, dec), Fmt(st.SecondHalf, dec), sgn(st.Curvature, d1), st.ZeroCross)},
		{"E8", "flat", fmt.Sprintf("noise %.*f, longest flat run %d pts, plateau at max %d pts", d1+1, st.Noise, st.FlatRun, st.PlateauRun)},
	}
}

func OutputSchemaHint(role string) string {
	pats := ContPatterns
	if role == "occupancy" {
		pats = OccPatterns
	}
	return "JSON keys: pattern (" + strings.Join(pats, "|") + "), status (normal|warning|critical|sensor_fault), " +
		"observations (1-3 short strings, each ending with cited ids like [E1,E4]), " +
		"likely_cause (" + strings.Join(Causes[role], "|") + "), confidence (0-1), action (" + strings.Join(Actions, "|") + ")."
}

func Llama3Prompt(system, user string) string {
	return "<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n" + system +
		"<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n" + user +
		"<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"
}

type AgentInput struct {
	Prompt   string
	Stats    Stats
	Occ      OccStats
	Evidence []Evidence
}

func BuildAgentPrompt(role, node, location, metric string, xs []float64, end int64) AgentInput {
	m := Metrics[role+"/"+metric]
	unitShown := m.Unit
	if unitShown == "" {
		unitShown = "ratio"
	}
	endT := time.Unix(end, 0).In(IST)
	startT := endT.Add(-time.Duration(StepMin*(Window-1)) * time.Minute)
	lines := []string{"NODE: " + node + " (" + location + ")", "METRIC: " + metric + " [" + unitShown + "]"}
	if m.HasLimits {
		rel := "above"
		if m.Dir == "low" {
			rel = "below"
		}
		lines = append(lines, fmt.Sprintf("LIMITS: warning %s %s, critical %s %s", rel, m.WarnS, rel, m.CritS))
	}
	lines = append(lines, fmt.Sprintf("WINDOW: %s -> %s IST, 48 x 5 min", startT.Format("Mon 02 Jan 15:04"), endT.Format("15:04")))
	var st Stats
	var os OccStats
	if role == "occupancy" {
		os = ComputeOccStats(xs)
		var sb strings.Builder
		for _, v := range xs {
			sb.WriteString(strconv.Itoa(int(v)))
		}
		lines = append(lines, "STATES (1=occupied): "+sb.String())
	} else {
		st = ComputeStats(xs, m.Dec)
		ds := downsample(xs)
		parts := make([]string, len(ds))
		for i, v := range ds {
			parts[i] = Fmt(v, m.Dec)
		}
		lines = append(lines, "SERIES (10-min means): "+strings.Join(parts, " "))
	}
	lines = append(lines, "EVIDENCE:")
	ev := EvidenceItems(role, st, os, end, m.Dec, m.Unit)
	for _, e := range ev {
		lines = append(lines, e.ID+" "+e.Text)
	}
	system := SystemPrompts[role] + SystemRules + " " + OutputSchemaHint(role)
	return AgentInput{Prompt: Llama3Prompt(system, strings.Join(lines, "\n")), Stats: st, Occ: os, Evidence: ev}
}

// ---------------------------------------------------------------- Mode-1 rule classifier
func windowScale(role, metric string, st Stats) float64 {
	m := Metrics[role+"/"+metric]
	floor := m.Floor
	if floor <= 0 {
		floor = math.Max(0.03*math.Abs(st.Mean), 0.05)
	}
	return math.Max(math.Max(floor, 1.5*math.Min(st.Noise, floor*1.5)), 1e-3)
}

// robustNoise mirrors features.robust_noise: MAD of 5-min differences, insensitive to a single spike.
func robustNoise(xs []float64) float64 {
	d := make([]float64, len(xs)-1)
	for i := 1; i < len(xs); i++ {
		d[i-1] = xs[i] - xs[i-1]
	}
	sortFloats(d)
	med := d[len(d)/2]
	dev := make([]float64, len(d))
	for i, v := range d {
		dev[i] = math.Abs(v - med)
	}
	sortFloats(dev)
	return 1.4826 * dev[len(dev)/2] / math.Sqrt(2)
}

func RulePattern(role, metric string, xs []float64, end int64) string {
	if role == "occupancy" {
		s := ComputeOccStats(xs)
		switch {
		case s.OccupiedFrac == 0:
			return "vacant"
		case IsOffHours(end):
			return "off_hours_presence"
		case s.Toggles >= 3:
			return "intermittent"
		case s.First == 0 && s.Last == 1:
			return "arrival"
		case s.First == 1 && s.Last == 0:
			return "departure"
		case s.OccupiedFrac >= 0.9:
			return "occupied"
		}
		return "intermittent"
	}
	m := Metrics[role+"/"+metric]
	st := ComputeStats(xs, m.Dec)
	s := windowScale(role, metric, st)
	if st.FlatRun >= 16 {
		return "flatline"
	}
	srt := append([]float64(nil), xs...)
	sortFloats(srt)
	med := srt[len(srt)/2]
	if robustNoise(xs) > 2.0*s && st.R2 < 0.35 && st.ZeroCross < 14 {
		return "erratic"
	}
	up, dn := st.Max-med, med-st.Min
	if up > 4*s && math.Abs(st.Last-med) < 2.5*s && st.MaxIdx < Window-1 && up > 2*dn {
		return "spike"
	}
	if dn > 4*s && math.Abs(st.Last-med) < 2.5*s && st.MinIdx < Window-1 && dn > 2*up {
		return "dip"
	}
	if st.PlateauRun >= 10 && st.SlopePerH > 0 && st.SecondHalf-st.FirstHalf > 2*s {
		return "throttling"
	}
	if st.ZeroCross >= 6 && st.Range > 4*s && st.R2 < 0.5 {
		return "oscillation"
	}
	half := st.SecondHalf - st.FirstHalf
	if st.Curvature > 0 && st.SlopePerH > 0 && xs[Window-1]-xs[Window*2/3] > 0.6*st.Range && st.Range > 3*s {
		return "exponential_increase"
	}
	if math.Abs(half) > 3*s && st.MaxJump > 0.45*math.Abs(half) {
		if half > 0 {
			return "step_increase"
		}
		return "step_decrease"
	}
	if math.Abs(st.SlopePerH)*4 > 3*s && st.R2 > 0.55 {
		if st.SlopePerH > 0 {
			return "gradual_increase"
		}
		return "gradual_decrease"
	}
	return "stable"
}

func sortFloats(a []float64) {
	// insertion sort is fine for 48 points and avoids importing sort for float64 keys
	for i := 1; i < len(a); i++ {
		v := a[i]
		j := i - 1
		for j >= 0 && a[j] > v {
			a[j+1] = a[j]
			j--
		}
		a[j+1] = v
	}
}
