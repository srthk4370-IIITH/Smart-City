package main

import (
	"fmt"
	"math"
	"sort"
)

// Long-range checks: what the 4 h domain agent misses (HANDBOOK 2.38).
//
// The agents read a 4 h window, and that is the length they are most accurate at, but they miss
// changes that started hours ago or build slowly. Two cheap CPU checks over the last 12 h of each
// flagged sensor add that view as evidence for the reasoner: a level shift that happened hours ago
// and stayed, and a slow drift. Measured on test months with the real NPU agent answers
// (proofs/2026-10-16_longrange): old steps caught 73% -> 93%, 6-12 h drifts 83% -> 95%, no new false
// alarms on calm windows, agent accuracy untouched. A third check (recurring small excursions) and a
// "same hours yesterday" baseline were tried and dropped: real sensors do both all the time.
//
// Mirrors training/window_study/longrange.py (stats/decide) exactly; longrange_test.go checks the two
// against fixtures that script writes. Thresholds were tuned on dev months only (params_final.json).

const (
	lrPoints    = 144 // 12 h of 5-min readings
	lrMinPoints = 96  // at least 8 h of history, else no long-range verdict
	lrKL        = 4.0 // level shift >= 4 x scale ...
	lrKD        = 4.0 // drift >= 4 x scale ...
	lrRD        = 0.8 // ... with r2 >= 0.8
	lrKQ        = 1.0 // scale also >= 1 x the first 3 h's IQR (sensors that normally switch)
)

// LongRange is one finding; Text is what the reasoner and the operator read.
type LongRange struct {
	ID     string  `json:"id"`   // E9, E10: citable by the reasoner as S#.E9
	Kind   string  `json:"kind"` // level_shift | slow_drift
	Delta  float64 `json:"delta"`
	AgoPts int     `json:"ago_pts,omitempty"`
	Hours  float64 `json:"hours,omitempty"`
	R2     float64 `json:"r2,omitempty"`
	Sigma  float64 `json:"sigma"`
	Text   string  `json:"text"`
}

func lrMedian(v []float64) float64 {
	s := append([]float64(nil), v...)
	sort.Float64s(s)
	n := len(s)
	if n%2 == 1 {
		return s[n/2]
	}
	return 0.5 * (s[n/2-1] + s[n/2])
}

// lrScale: robust 5-min noise (MAD of first differences), floored per metric, and at least the
// spread of the first 3 h so a sensor whose normal behaviour is switching is judged on that.
func lrScale(m Metric, xs []float64) float64 {
	d := make([]float64, 0, len(xs)-1)
	for i := 1; i < len(xs); i++ {
		d = append(d, xs[i]-xs[i-1])
	}
	md := lrMedian(d)
	ad := make([]float64, len(d))
	for i, v := range d {
		ad[i] = math.Abs(v - md)
	}
	noise := 1.4826 * lrMedian(ad) / math.Sqrt2
	floor := m.Floor
	if floor <= 0 {
		floor = math.Max(0.03*math.Abs(lrMedian(xs)), 0.05)
	}
	ref := append([]float64(nil), xs[:36]...)
	sort.Float64s(ref)
	iqr := ref[27] - ref[9]
	return math.Max(math.Max(noise, 0.5*floor), math.Max(1e-6, lrKQ*iqr))
}

func lrLinfit(xs []float64) (b, r2 float64) {
	n := float64(len(xs))
	mx := (n - 1) / 2
	my := 0.0
	for _, x := range xs {
		my += x
	}
	my /= n
	var sxx, sxy, ss float64
	for i, x := range xs {
		sxx += (float64(i) - mx) * (float64(i) - mx)
		sxy += (float64(i) - mx) * (x - my)
		ss += (x - my) * (x - my)
	}
	b = sxy / sxx
	var res float64
	for i, x := range xs {
		e := x - (my + b*(float64(i)-mx))
		res += e * e
	}
	if ss > 0 {
		r2 = 1 - res/ss
	}
	return b, r2
}

// longRange runs both checks on xs (oldest first, last = now, up to 12 h). unit is for the text.
func longRange(role, metric string, xs []float64) []LongRange {
	m, ok := Metrics[role+"/"+metric]
	if !ok || role == "occupancy" || len(xs) < lrMinPoints {
		return nil
	}
	return longRangeM(m, xs)
}

// longRangeM is longRange for an explicit metric spec (the v2 HVAC room temperature has its own floor).
func longRangeM(m Metric, xs []float64) []LongRange {
	if len(xs) < lrMinPoints {
		return nil
	}
	if len(xs) > lrPoints {
		xs = xs[len(xs)-lrPoints:]
	}
	n := len(xs)
	s := lrScale(m, xs)
	M := make([]float64, n-5) // rolling 30-min medians: robust to single spikes
	for i := range M {
		M[i] = lrMedian(xs[i : i+6])
	}
	steep := 0.0
	for i := 0; i+6 < len(M); i++ {
		steep = math.Max(steep, math.Abs(M[i+6]-M[i]))
	}
	base, now := lrMedian(xs[:36]), lrMedian(xs[n-12:])
	delta := now - base
	var out []LongRange
	u := ""
	if m.Unit != "" && m.Unit != "0/1" {
		u = " " + m.Unit
	}
	if math.Abs(delta) >= lrKL*s && steep >= 0.5*math.Abs(delta) {
		half := base + delta/2
		k := 0
		for i, v := range M {
			if (v-half)*delta > 0 {
				k = i
				break
			}
		}
		f := LongRange{Kind: "level_shift", Delta: delta, AgoPts: n - 1 - (k + 5), Sigma: math.Abs(delta) / s}
		f.Text = fmt.Sprintf("12 h view: level shifted %+.3g%s about %.1f h ago and stayed (%.1fx normal variation)",
			delta, u, float64(f.AgoPts)*5/60, f.Sigma)
		out = append(out, f)
	}
	b, r2 := lrLinfit(xs)
	total := b * float64(n-1)
	if math.Abs(total) >= lrKD*s && r2 >= lrRD && steep < 0.5*math.Abs(total) {
		f := LongRange{Kind: "slow_drift", Delta: total, Hours: float64(n) * 5 / 60, R2: r2, Sigma: math.Abs(total) / s}
		f.Text = fmt.Sprintf("12 h view: slow drift %+.3g%s over %.0f h (r2 %.2f, %.1fx normal variation)", total, u, f.Hours, r2, f.Sigma)
		out = append(out, f)
	}
	return out
}
