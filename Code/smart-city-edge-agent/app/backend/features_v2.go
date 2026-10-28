package main

// v2 domain-agent prompt (training/v2/features_v2.py, RETRAIN_V2_SPEC.md). Line-by-line port: the prompt
// text MUST stay byte-identical to training; features_v2_test.go checks ~300 Python-built prompts
// (testdata/v2_prompt_fixtures.json, written by training/v2/make_go_fixtures.py).
//
// Differences from the v1 prompt (features.go, unchanged and still used by the deployed v1 model):
//   any window length N (24..144, step 6) instead of 48; SERIES has N/2 10-min means; E6 "mean {H}h";
//   E9 = 12 h view (level shift / slow drift, the longrange.go detectors); E10 = recent episodes
//   (excursions beyond 3x normal noise in the history); system rules "a {H}-hour window", "(E1..E10)";
//   the frozen v2 schema hint; a TANK line for water level nodes (node_limits_v2.json); the HVAC role
//   (hvac_v2.go). Everything here is used only when the v2 agent is switched on (agentversion.go).

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const (
	v2MinN   = 24
	v2MaxN   = 144
	v2StepN  = 6
	v2Hist   = 144 // history points behind E9/E10
	v2ExcK   = 3.0 // E10: excursion threshold in units of normal noise
	v2ExcHW  = 6   // E10: rolling-median half width (13-point median)
	v2ExcGap = 2   // E10: points within this gap belong to one excursion
)

// v2 role registry: v1 roles + HVAC. Water gains two causes for abnormal fills (D2).
var CausesV2 = func() map[string][]string {
	m := map[string][]string{}
	for r, c := range Causes {
		m[r] = append([]string(nil), c...)
	}
	m["water"] = append(m["water"], "tank_overflow_risk", "fill_valve_stuck")
	m["hvac"] = HVACCauses
	return m
}()

// PatternsV2 is the pattern whitelist of a v2 agent.
func PatternsV2(role string) []string {
	switch role {
	case "occupancy":
		return OccPatterns
	case "hvac":
		return HVACPatterns
	}
	return ContPatterns
}

// RoleActionsV2: actions printed in the v2 schema hint (HVAC adds switch_off_ac, D9).
func RoleActionsV2(role string) []string {
	if role == "hvac" {
		return append(append([]string(nil), Actions...), ActionsV2...)
	}
	return Actions
}

// waterExtraAction: v2 teacher EXTRA_ACTION (teacher_v2.py).
var waterExtraAction = map[string]string{"tank_overflow_risk": "inspect_water_system", "fill_valve_stuck": "inspect_water_system"}

// ActionOfRole derives the action from (cause, status) as the v2 teacher does: HVAC has its own table,
// the two new water causes map to inspect_water_system, everything else is the v1 ActionOf. For every
// v1 cause it returns exactly ActionOf, so it is safe in v1 mode too.
func ActionOfRole(role, cause, status string) string {
	if role == "hvac" {
		if _, ok := hvacActionOf[cause]; ok {
			return HVACActionOf(cause, status)
		}
	}
	if a, ok := waterExtraAction[cause]; ok {
		return a
	}
	return ActionOf(cause, status)
}

// TankLimit is one water level node's limits (training/v2/generate_v2.tank_limits, TRAIN months).
type TankLimit struct {
	High     float64 `json:"high"`
	Overflow float64 `json:"overflow"`
	FillMin  float64 `json:"fill_min"`
}

// NodeLimitsV2: per-node tank limits shown on the TANK line; loaded from data/node_limits_v2.json.
var NodeLimitsV2 = map[string]TankLimit{}

// E10CountThresholds: per role/metric, the number of E10 excursions above the 95th percentile of calm
// TRAIN windows (data/sft_v2/kthr.json, manifest "e10_thresholds"). The teacher calls a history with at
// least this many excursions "recurring small spikes"; the backend uses it only to tag that evidence.
var E10CountThresholds = map[string]int{}

// loadV2Assets reads the v2 tables shipped in the app's data/ (no-op when absent).
func loadV2Assets(dir string) {
	if b, err := os.ReadFile(filepath.Join(dir, "data", "node_limits_v2.json")); err == nil {
		m := map[string]TankLimit{}
		if json.Unmarshal(b, &m) == nil {
			NodeLimitsV2 = m
		}
	}
	if b, err := os.ReadFile(filepath.Join(dir, "data", "e10_thresholds_v2.json")); err == nil {
		var m map[string]struct {
			Thr int `json:"thr"`
		}
		if json.Unmarshal(b, &m) == nil {
			for k, v := range m {
				E10CountThresholds[k] = v.Thr
			}
		}
	}
}

// hoursStr: window length in hours as Python "%g" prints it (48 -> "4", 30 -> "2.5").
func hoursStr(n int) string { return strconv.FormatFloat(float64(n*StepMin)/60, 'g', -1, 64) }

// idxTimeN: wall time (IST, HH:MM) of point idx in a series of n points whose last point is at end.
func idxTimeN(end int64, n, idx int) string {
	t := end - int64(n-1-idx)*StepMin*60
	return time.Unix(t, 0).In(IST).Format("15:04")
}

func downsampleK(xs []float64, k int) []float64 {
	step := len(xs) / k
	out := make([]float64, k)
	for i := 0; i < k; i++ {
		out[i] = mean(xs[i*step : (i+1)*step])
	}
	return out
}

// EvidenceItemsV2: E1..E8 with v1 text for any window length n.
func EvidenceItemsV2(role string, st Stats, os OccStats, end int64, dec int, unit string, n int) []Evidence {
	u := ""
	if unit != "" {
		u = " " + unit
	}
	T := func(i int) string { return idxTimeN(end, n, i) }
	if role == "occupancy" {
		fo, lo := "never", "never"
		if os.FirstOn >= 0 {
			fo = T(os.FirstOn)
		}
		if os.LastOn >= 0 {
			lo = T(os.LastOn)
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
			{"E6", "time", "window end " + T(n-1) + off},
		}
	}
	d1 := imax(dec, 1)
	return []Evidence{
		{"E1", "last", fmt.Sprintf("last = %s%s", Fmt(st.Last, dec), u)},
		{"E2", "max", fmt.Sprintf("max = %s%s at %s", Fmt(st.Max, dec), u, T(st.MaxIdx))},
		{"E3", "min", fmt.Sprintf("min = %s%s at %s", Fmt(st.Min, dec), u, T(st.MinIdx))},
		{"E4", "slope", fmt.Sprintf("trend = %s%s/h (r2 %.2f)", sgn(st.SlopePerH, d1), u, st.R2)},
		{"E5", "max_jump", fmt.Sprintf("largest 5-min change = %s%s at %s", sgn(st.MaxJumpSigned, d1), u, T(st.MaxJumpIdx))},
		{"E6", "sma", fmt.Sprintf("SMA 1h = %s, EMA 1h = %s, mean %sh = %s%s", Fmt(st.SMA1h, dec), Fmt(st.EMA1h, dec), hoursStr(n), Fmt(st.Mean, dec), u)},
		{"E7", "shape", fmt.Sprintf("halves %s -> %s, curvature %s/h, oscillation crossings %d", Fmt(st.FirstHalf, dec), Fmt(st.SecondHalf, dec), sgn(st.Curvature, d1), st.ZeroCross)},
		{"E8", "flat", fmt.Sprintf("noise %.*f, longest flat run %d pts, plateau at max %d pts", d1+1, st.Noise, st.FlatRun, st.PlateauRun)},
	}
}

// ---------------------------------------------------------------- E9 / E10 (history lines)

// lrNoiseScale mirrors longrange.noise_scale: max(robust 5-min noise, 1/2 metric floor, 1e-6).
func lrNoiseScale(m Metric, h []float64) float64 {
	d := make([]float64, 0, len(h)-1)
	for i := 1; i < len(h); i++ {
		d = append(d, h[i]-h[i-1])
	}
	md := lrMedian(d)
	ad := make([]float64, len(d))
	for i, v := range d {
		ad[i] = math.Abs(v - md)
	}
	noise := 1.4826 * lrMedian(ad) / math.Sqrt2
	floor := m.Floor
	if floor <= 0 {
		floor = math.Max(0.03*math.Abs(lrMedian(h)), 0.05)
	}
	return math.Max(math.Max(noise, 0.5*floor), 1e-6)
}

// excScale: E10 "normal noise" = max(noise_scale, kQ x IQR of the first 36 points (or fewer)).
func excScale(m Metric, h []float64) float64 {
	L := len(h)
	if L > 36 {
		L = 36
	}
	ref := append([]float64(nil), h[:L]...)
	sortFloats(ref)
	iqr := ref[(3*L)/4] - ref[L/4]
	return math.Max(lrNoiseScale(m, h), lrKQ*iqr)
}

// excursions: E10 (count, peak in noise units).
func excursions(m Metric, h []float64) (int, float64) {
	s := excScale(m, h)
	n := len(h)
	thr := v2ExcK * s
	c, last, peak := 0, -10, 0.0
	for i := 0; i < n; i++ {
		lo, hi := i-v2ExcHW, i+v2ExcHW+1
		if lo < 0 {
			lo = 0
		}
		if hi > n {
			hi = n
		}
		r := math.Abs(h[i] - lrMedian(h[lo:hi]))
		if r >= thr {
			if i-last > v2ExcGap {
				c++
			}
			last = i
			peak = math.Max(peak, r/s)
		}
	}
	return c, peak
}

func occPeriods(h []float64) (int, int) {
	c, cur, best := 0, 0, 0
	for _, v := range h {
		if v >= 0.5 {
			if cur == 0 {
				c++
			}
			cur++
			if cur > best {
				best = cur
			}
		} else {
			cur = 0
		}
	}
	return c, best
}

// HistInfo is what the history lines found (for the backend's own use, e.g. tagging recurring spikes).
type HistInfo struct {
	HistLen   int         `json:"hist_len"`
	LongView  []LongRange `json:"long_view,omitempty"`
	ExcCount  int         `json:"exc_count"`
	ExcPeak   float64     `json:"exc_peak"`
	Recurring bool        `json:"recurring,omitempty"` // ExcCount >= the role/metric's E10 count threshold
}

// HistoryItemsV2: the E9 and E10 evidence lines on h (oldest first, last = window end, <= 144 points).
func HistoryItemsV2(role, metric string, m Metric, h []float64, end int64) ([]Evidence, HistInfo) {
	if len(h) > v2Hist {
		h = h[len(h)-v2Hist:]
	}
	u := ""
	if m.Unit != "" {
		u = " " + m.Unit
	}
	hh := fmt.Sprintf("%.0f", float64(len(h)*StepMin)/60)
	info := HistInfo{HistLen: len(h)}
	if role == "occupancy" {
		frac := 0.0
		for _, v := range h {
			frac += v
		}
		frac /= float64(len(h))
		k, best := occPeriods(h)
		e9 := fmt.Sprintf("12 h view: occupied fraction %.2f over the last %s h", frac, hh)
		var e10 string
		if k == 0 {
			e10 = fmt.Sprintf("recent episodes: no occupied periods in the last %s h", hh)
		} else {
			pl := "s"
			if k == 1 {
				pl = ""
			}
			e10 = fmt.Sprintf("recent episodes: %d occupied period%s in the last %s h (longest %.1f h)", k, pl, hh, float64(best*StepMin)/60)
		}
		info.ExcCount = k
		return []Evidence{{"E9", "long_view", e9}, {"E10", "episodes", e10}}, info
	}
	sd := imax(m.Dec, 1)
	var e9 string
	if len(h) < lrMinPoints {
		e9 = "12 h view: under 8 h of history"
	} else {
		lv := longRangeM(m, h)
		info.LongView = lv
		if len(lv) == 0 {
			e9 = "12 h view: no level shift or drift"
		} else {
			parts := make([]string, 0, len(lv))
			for _, f := range lv {
				if f.Kind == "level_shift" {
					t := idxTimeN(end, len(h), len(h)-1-f.AgoPts)
					parts = append(parts, fmt.Sprintf("level shift %+.*f%s at %s (%.1fx normal variation)", sd, f.Delta, u, t, f.Sigma))
				} else {
					t := idxTimeN(end, len(h), 0)
					parts = append(parts, fmt.Sprintf("slow drift %+.*f%s since %s (r2 %.2f, %.1fx normal variation)", sd, f.Delta, u, t, f.R2, f.Sigma))
				}
			}
			e9 = "12 h view: " + strings.Join(parts, "; ")
		}
	}
	k, peak := excursions(m, h)
	info.ExcCount, info.ExcPeak = k, peak
	if thr, ok := E10CountThresholds[role+"/"+metric]; ok && k >= thr {
		info.Recurring = true
	}
	var e10 string
	if k == 0 {
		e10 = fmt.Sprintf("recent episodes: no excursions beyond 3x normal noise in the last %s h", hh)
	} else {
		pl := "s"
		if k == 1 {
			pl = ""
		}
		e10 = fmt.Sprintf("recent episodes: %d excursion%s beyond 3x normal noise in the last %s h (largest %.1fx)", k, pl, hh, peak)
	}
	return []Evidence{{"E9", "long_view", e9}, {"E10", "episodes", e10}}, info
}

// ---------------------------------------------------------------- prompt

func SystemRulesV2(n int) string {
	return strings.Replace(strings.Replace(SystemRules, "a 4-hour window", "a "+hoursStr(n)+"-hour window", 1), "(E1..E8)", "(E1..E10)", 1)
}

func OutputSchemaHintV2(role string) string {
	return "JSON keys: pattern (" + strings.Join(PatternsV2(role), "|") + "), status (normal|warning|critical|sensor_fault), " +
		"observations (1-2 short strings, each ending with cited ids like [E1,E4]), " +
		"likely_cause (" + strings.Join(CausesV2[role], "|") + "), confidence (0-1), event_active (true|false), onset (HH:MM), " +
		"fault_kind (" + strings.Join(FaultKinds, "|") + ", only if sensor_fault), action (" + strings.Join(RoleActionsV2(role), "|") + ")."
}

// AgentInputV2 is a v2 prompt plus what the history lines found and the window length used.
type AgentInputV2 struct {
	AgentInput
	N    int
	Hist HistInfo
}

// v2Window: the window (last n points) and history (last <= 144 points) behind a v2 prompt. hist must
// end at the window end; a hist shorter than n is replaced by xs. n is clamped to a valid v2 length.
func v2Window(xs, hist []float64, n int) ([]float64, []float64, int) {
	if len(hist) < len(xs) {
		hist = xs
	}
	n = ValidV2N(n, len(hist))
	if len(hist) > v2Hist {
		hist = hist[len(hist)-v2Hist:]
	}
	return hist[len(hist)-n:], hist, n
}

// ValidV2N clamps a requested window length to a trained one (24..144 step 6) that fits in have points.
func ValidV2N(n, have int) int {
	if n > have {
		n = have
	}
	if n > v2MaxN {
		n = v2MaxN
	}
	n -= n % v2StepN
	if n < v2MinN {
		n = v2MinN
	}
	return n
}

// BuildAgentPromptV2 builds the v2 prompt for a v1 role (air_quality, water, power, occupancy, weather):
// features_v2.agent_prompt(role, node, location, metric, hist, len(xs), end). xs is the window (its
// length is N), hist the history ending at the same reading (<= 144 points, oldest first; nil = xs).
func BuildAgentPromptV2(role, node, location, metric string, xs []float64, end int64, hist []float64) AgentInputV2 {
	xs, hist, n := v2Window(xs, hist, len(xs))
	m := Metrics[role+"/"+metric]
	unitShown := m.Unit
	if unitShown == "" {
		unitShown = "ratio"
	}
	endT := time.Unix(end, 0).In(IST)
	startT := endT.Add(-time.Duration(StepMin*(n-1)) * time.Minute)
	lines := []string{"NODE: " + node + " (" + location + ")", "METRIC: " + metric + " [" + unitShown + "]"}
	if m.HasLimits {
		rel := "above"
		if m.Dir == "low" {
			rel = "below"
		}
		lines = append(lines, fmt.Sprintf("LIMITS: warning %s %s, critical %s %s", rel, m.WarnS, rel, m.CritS))
	}
	if tl, ok := NodeLimitsV2[node]; ok && role == "water" && metric == "level" {
		lines = append(lines, fmt.Sprintf("TANK: high level above %s, overflow risk above %s; usual fill up to %s min",
			Fmt(tl.High, m.Dec), Fmt(tl.Overflow, m.Dec), strconv.FormatFloat(tl.FillMin, 'f', -1, 64)))
	}
	lines = append(lines, fmt.Sprintf("WINDOW: %s -> %s IST, %d x 5 min", startT.Format("Mon 02 Jan 15:04"), endT.Format("15:04"), n))
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
		ds := downsampleK(xs, n/2)
		parts := make([]string, len(ds))
		for i, v := range ds {
			parts[i] = Fmt(v, m.Dec)
		}
		lines = append(lines, "SERIES (10-min means): "+strings.Join(parts, " "))
	}
	lines = append(lines, "EVIDENCE:")
	ev := EvidenceItemsV2(role, st, os, end, m.Dec, m.Unit, n)
	hv, info := HistoryItemsV2(role, metric, m, hist, end)
	ev = append(ev, hv...)
	for _, e := range ev {
		lines = append(lines, e.ID+" "+e.Text)
	}
	system := SystemPrompts[role] + SystemRulesV2(n) + " " + OutputSchemaHintV2(role)
	return AgentInputV2{AgentInput: AgentInput{Prompt: Llama3Prompt(system, strings.Join(lines, "\n")), Stats: st, Occ: os, Evidence: ev, Xs: xs}, N: n, Hist: info}
}

// ---------------------------------------------------------------- window policy (spec Q3/5, revised)

// Run-time window lengths. The early alert reads 4 h for every sensor (the alert path is unchanged).
// The 1.5 h and 3 h refinements pick the window by the shape the EARLY call saw, not by severity: the
// v2 device window study (proofs/2026-10-21_v2_research/accuracy/window_study.md, 183 placed events x
// 4/8/12 h) found trends read best at 4 h (3 h: 90/80/72%), a 3 h-old spike or dip at 8 h (80/93/89%),
// flatlines and sensor faults at 12 h (90/95/100%), and severity alone no help (critical 76/79/82%, ns).
// Through the app chain this lifts 3 h pattern accuracy 85.8% -> 91.8% over the old severity ladder.
const (
	LadderAlert = 48
	winShort    = 48  // 4 h
	winMid      = 96  // 8 h
	winLong     = 144 // 12 h
	winBaseline = 12  // readings of pre-onset baseline the window must keep (training: onset always inside)
)

// windowFamily groups the v2 patterns the way the window study does.
func windowFamily(pattern string) string {
	switch normEnum(pattern) {
	case "flatline":
		return "flat"
	case "spike", "dip":
		return "transient"
	case "erratic", "oscillation":
		return "noisy"
	case "stable":
		return "stable"
	case "gradual_increase", "gradual_decrease", "exponential_increase":
		return "trend"
	case "step_increase", "step_decrease", "throttling":
		return "step"
	}
	for _, ps := range [][]string{OccPatterns, HVACPatterns} {
		for _, q := range ps {
			if normEnum(pattern) == q {
				return "other" // occupancy / HVAC: not in the window study, kept at the trained 4 h
			}
		}
	}
	return "invalid"
}

// WindowN is the window length for a stage ("early", "1.5h", "3h"), the early call's pattern, the
// sensor's latest status and the event age (readings from onset to the stage end; < 0 = unknown).
// The window always holds the onset plus 1 h of baseline (training never showed an older onset),
// up to the 12 h maximum; ValidV2N later fits it to the history that exists.
func WindowN(stage, earlyPattern, status string, age int) int {
	if stage == "early" || stage == "" {
		return LadderAlert
	}
	fam := windowFamily(earlyPattern)
	if fam == "stable" && reportRank[normSeverity(status)] >= 2 {
		// "stable" yet warning/critical: the early call did not see the shape, so it is treated like an
		// unrecognised call (8 h). On the device this is pump cycling; neither 8 h nor 12 h reads it
		// reliably as oscillation (one run each way), so the shorter window is kept
		fam = "invalid"
	}
	n := winShort
	switch {
	case normSeverity(status) == "sensor_fault":
		n = winMid
		if fam == "flat" || fam == "noisy" {
			n = winLong
		}
	case fam == "flat":
		n = winLong
	case fam == "transient", fam == "invalid":
		n = winMid
	case fam == "step" && stage == "3h":
		n = winMid
	case fam == "noisy" && stage == "3h":
		n = winLong
	}
	if age >= 0 {
		need := age + winBaseline
		need += (v2StepN - need%v2StepN) % v2StepN
		n = imax(n, imin(need, v2MaxN))
	}
	return n
}

// eventAge is the readings from a sensor's event onset to end. f (ok = found) is its latest finding,
// whose window ended at prevEnd. Without an onset
// (a rule finding, or the model left it out) the alert time stands in, plus 1 h: alerts fire 20-60
// min after onset in the placement study, so this errs towards a longer window.
func eventAge(f Finding, ok bool, prevEnd, created, end int64) int {
	step := int64(StepMin * 60)
	if ok && f.Onset != "" {
		// searched over the whole 12 h history, not just prevN: the model may date an onset from the
		// E9/E10 12 h lines, older than its own window (a slow tank leak), and the next window must
		// then reach back to it
		if a := onsetAge(f.Onset, v2MaxN, prevEnd); a >= 0 {
			return a + int((end-prevEnd)/step)
		}
	}
	return int((end-created)/step) + winBaseline
}

// ---------------------------------------------------------------- confidence (D4)

// ConfidenceRecalV2 is the backend recalibration of v2 confidences (D4): the device accuracy of the v2
// agent's pattern per (predicted pattern, readings since the model's own onset), shrunk towards the
// pattern's and then the global rate for thin cells. The model's own number carries almost no signal
// (held-out AUC 0.59; the trained targets were per-pattern constants), so the table replaces it rather
// than remapping it; a raw-confidence split and a window-length split were tried and did not help on the
// held-out set. Method, CV and held-out metrics, reliability diagram:
// proofs/2026-10-21_v2_research/calibration/ (calibration.md, calibration_metrics.json, reliability.svg).
// Regenerate with c0_rows.py + c1_fit.py --apply; the block between the markers is generated.
type ConfRecalRow struct {
	MinAge, MaxAge int // onsetAge range; -1..-1 = no onset (or one outside the window)
	Conf           float64
}

// BEGIN generated D4 table (proofs/2026-10-21_v2_research/calibration/c1_fit.py; do not edit by hand)
// Fit: 4590 device answers (2026-10-20 placement_v2 + host400 + test_all), clean rows x2, shrinkage A=5, global 0.754; held out placement_s24 n=3538: ECE 0.1519 -> 0.0508, Brier 0.2335 -> 0.1495.
// Rows: MinAge..MaxAge = readings from the model's onset to the window end (onsetAge; -1 = no onset in the
// window); Conf = shrunk empirical P(pattern correct) of the device v2 agent in that cell. "*" = a pattern
// without fit data (global rate per age). See calibration/calibration.md and reliability.svg.
var ConfidenceRecalV2 = map[string][]ConfRecalRow{
	"arrival":              {{-1, -1, 0.94}, {1, 6, 0.94}, {7, 12, 0.95}, {13, 24, 0.97}, {25, 48, 0.97}, {49, 96, 0.95}, {97, 144, 0.95}},
	"bias_jump":            {{-1, -1, 0.94}, {1, 6, 0.96}, {7, 12, 0.97}, {13, 24, 0.96}, {25, 48, 0.97}, {49, 96, 0.94}, {97, 144, 0.95}},
	"biased_reading":       {{-1, -1, 0.92}, {1, 6, 0.92}, {7, 12, 0.92}, {13, 24, 0.95}, {25, 48, 0.96}, {49, 96, 0.94}, {97, 144, 0.92}},
	"calibration_drift":    {{-1, -1, 0.92}, {1, 6, 0.92}, {7, 12, 0.92}, {13, 24, 0.92}, {25, 48, 0.97}, {49, 96, 0.95}, {97, 144, 0.92}},
	"departure":            {{-1, -1, 0.94}, {1, 6, 0.94}, {7, 12, 0.94}, {13, 24, 0.96}, {25, 48, 0.96}, {49, 96, 0.97}, {97, 144, 0.94}},
	"dip":                  {{-1, -1, 0.79}, {1, 6, 0.60}, {7, 12, 0.82}, {13, 24, 0.92}, {25, 48, 0.83}, {49, 96, 0.75}, {97, 144, 0.64}},
	"dropout":              {{-1, -1, 0.92}, {1, 6, 0.92}, {7, 12, 0.92}, {13, 24, 0.97}, {25, 48, 0.96}, {49, 96, 0.92}, {97, 144, 0.92}},
	"erratic":              {{-1, -1, 0.81}, {1, 6, 0.52}, {7, 12, 0.76}, {13, 24, 0.91}, {25, 48, 0.91}, {49, 96, 0.93}, {97, 144, 0.68}},
	"exponential_increase": {{-1, -1, 0.78}, {1, 6, 0.68}, {7, 12, 0.98}, {13, 24, 0.87}, {25, 48, 0.85}, {49, 96, 0.62}, {97, 144, 0.44}},
	"flatline":             {{-1, -1, 0.83}, {1, 6, 0.41}, {7, 12, 0.85}, {13, 24, 0.90}, {25, 48, 0.95}, {49, 96, 0.63}, {97, 144, 0.39}},
	"gradual_decrease":     {{-1, -1, 0.90}, {1, 6, 0.69}, {7, 12, 0.92}, {13, 24, 0.99}, {25, 48, 0.90}, {49, 96, 0.74}, {97, 144, 0.84}},
	"gradual_increase":     {{-1, -1, 0.53}, {1, 6, 0.62}, {7, 12, 0.65}, {13, 24, 0.89}, {25, 48, 0.96}, {49, 96, 0.79}, {97, 144, 0.69}},
	"intermittent":         {{-1, -1, 0.90}, {1, 6, 0.90}, {7, 12, 0.90}, {13, 24, 0.90}, {25, 48, 0.94}, {49, 96, 0.93}, {97, 144, 0.91}},
	"no_cooling_effect":    {{-1, -1, 0.91}, {1, 6, 0.91}, {7, 12, 0.95}, {13, 24, 0.91}, {25, 48, 0.92}, {49, 96, 0.92}, {97, 144, 0.92}},
	"normal_cycling":       {{-1, -1, 0.94}, {1, 6, 0.94}, {7, 12, 0.94}, {13, 24, 0.94}, {25, 48, 0.99}, {49, 96, 0.97}, {97, 144, 0.94}},
	"occupied":             {{-1, -1, 0.96}, {1, 6, 0.96}, {7, 12, 0.96}, {13, 24, 0.96}, {25, 48, 0.99}, {49, 96, 0.99}, {97, 144, 0.99}},
	"off_hours_presence":   {{-1, -1, 0.89}, {1, 6, 0.89}, {7, 12, 0.89}, {13, 24, 0.89}, {25, 48, 0.91}, {49, 96, 0.92}, {97, 144, 0.93}},
	"oscillation":          {{-1, -1, 0.49}, {1, 6, 0.61}, {7, 12, 0.83}, {13, 24, 0.72}, {25, 48, 0.64}, {49, 96, 0.28}, {97, 144, 0.15}},
	"pull_down":            {{-1, -1, 0.84}, {1, 6, 0.66}, {7, 12, 0.78}, {13, 24, 0.91}, {25, 48, 0.96}, {49, 96, 0.84}, {97, 144, 0.84}},
	"quantised":            {{-1, -1, 0.92}, {1, 6, 0.92}, {7, 12, 0.92}, {13, 24, 0.97}, {25, 48, 0.95}, {49, 96, 0.92}, {97, 144, 0.92}},
	"running_empty_room":   {{-1, -1, 0.92}, {1, 6, 0.92}, {7, 12, 0.97}, {13, 24, 0.95}, {25, 48, 0.95}, {49, 96, 0.92}, {97, 144, 0.92}},
	"saturation":           {{-1, -1, 0.91}, {1, 6, 0.92}, {7, 12, 0.92}, {13, 24, 0.95}, {25, 48, 0.93}, {49, 96, 0.91}, {97, 144, 0.91}},
	"setback_drift":        {{-1, -1, 0.97}, {1, 6, 0.97}, {7, 12, 0.97}, {13, 24, 0.98}, {25, 48, 0.99}, {49, 96, 0.98}, {97, 144, 0.98}},
	"short_cycling":        {{-1, -1, 0.93}, {1, 6, 0.93}, {7, 12, 0.93}, {13, 24, 0.98}, {25, 48, 0.94}, {49, 96, 0.94}, {97, 144, 0.93}},
	"slow_recovery":        {{-1, -1, 0.89}, {1, 6, 0.89}, {7, 12, 0.94}, {13, 24, 0.89}, {25, 48, 0.92}, {49, 96, 0.89}, {97, 144, 0.89}},
	"spike":                {{-1, -1, 0.48}, {1, 6, 0.66}, {7, 12, 0.85}, {13, 24, 0.84}, {25, 48, 0.58}, {49, 96, 0.13}, {97, 144, 0.50}},
	"stable":               {{-1, -1, 0.66}, {1, 6, 0.66}, {7, 12, 0.66}, {13, 24, 0.77}, {25, 48, 0.68}, {49, 96, 0.63}, {97, 144, 0.65}},
	"step_decrease":        {{-1, -1, 0.39}, {1, 6, 0.83}, {7, 12, 0.99}, {13, 24, 0.96}, {25, 48, 0.84}, {49, 96, 0.45}, {97, 144, 0.75}},
	"step_increase":        {{-1, -1, 0.59}, {1, 6, 0.94}, {7, 12, 0.97}, {13, 24, 0.99}, {25, 48, 0.91}, {49, 96, 0.74}, {97, 144, 0.62}},
	"stuck_off":            {{-1, -1, 0.91}, {1, 6, 0.92}, {7, 12, 0.93}, {13, 24, 0.92}, {25, 48, 0.95}, {49, 96, 0.91}, {97, 144, 0.91}},
	"stuck_on":             {{-1, -1, 0.89}, {1, 6, 0.89}, {7, 12, 0.89}, {13, 24, 0.89}, {25, 48, 0.94}, {49, 96, 0.91}, {97, 144, 0.89}},
	"throttling":           {{-1, -1, 0.90}, {1, 6, 0.92}, {7, 12, 0.93}, {13, 24, 0.90}, {25, 48, 0.87}, {49, 96, 0.97}, {97, 144, 0.92}},
	"too_cold":             {{-1, -1, 0.93}, {1, 6, 0.94}, {7, 12, 0.97}, {13, 24, 0.95}, {25, 48, 0.95}, {49, 96, 0.94}, {97, 144, 0.93}},
	"too_hot":              {{-1, -1, 0.91}, {1, 6, 0.92}, {7, 12, 0.92}, {13, 24, 0.93}, {25, 48, 0.93}, {49, 96, 0.93}, {97, 144, 0.91}},
	"unit_alarm":           {{-1, -1, 0.90}, {1, 6, 0.90}, {7, 12, 0.95}, {13, 24, 0.91}, {25, 48, 0.90}, {49, 96, 0.90}, {97, 144, 0.90}},
	"vacant":               {{-1, -1, 0.96}, {1, 6, 0.96}, {7, 12, 0.96}, {13, 24, 0.96}, {25, 48, 0.99}, {49, 96, 0.96}, {97, 144, 0.98}},
	"*":                    {{-1, -1, 0.51}, {1, 6, 0.69}, {7, 12, 0.85}, {13, 24, 0.92}, {25, 48, 0.82}, {49, 96, 0.58}, {97, 144, 0.51}},
}

// END generated D4 table

// RecalibrateConfidence returns the calibrated confidence for a v2 finding whose window held n readings
// ending at end (n <= 0: onset age unknown). A pattern without its own rows uses the "*" rows; with no
// table at all the model's confidence is kept.
func RecalibrateConfidence(f Finding, n int, end int64) float64 {
	rows, ok := ConfidenceRecalV2[normEnum(f.Pattern)]
	if !ok {
		rows, ok = ConfidenceRecalV2["*"]
	}
	if !ok {
		return f.Confidence
	}
	age := -1
	if f.Onset != "" && n > 0 {
		age = onsetAge(f.Onset, n, end)
	}
	for _, r := range rows {
		if age >= r.MinAge && age <= r.MaxAge {
			return r.Conf
		}
	}
	return f.Confidence
}

var reWindowN = regexp.MustCompile(`(?m)^WINDOW: .* IST, (\d+) x 5 min`)

// applyConfidenceRecal (v2 agent only): a valid agent answer's confidence becomes the D4 calibrated value
// before anything reads it (dashboard, report ordering, synthesizer prompt, fallback report). The window
// length is read from the prompt's WINDOW line (v2 and HVAC prompts alike); the model's own number stays
// in call.Raw for audit.
func applyConfidenceRecal(call *AgentCall, end int64, prompt string) {
	if !agentV2() || call == nil || call.Parsed == nil || !call.Valid {
		return
	}
	n := 0
	if m := reWindowN.FindStringSubmatch(prompt); m != nil {
		n, _ = strconv.Atoi(m[1])
	}
	call.Parsed.Confidence = RecalibrateConfidence(*call.Parsed, n, end)
}

// onsetAge: readings from onset (HH:MM) to the window end, searched within the window's n readings.
func onsetAge(onset string, n int, end int64) int {
	for i := n - 1; i >= 0; i-- {
		if idxTimeN(end, n, i) == onset {
			return n - i
		}
	}
	return -1
}
