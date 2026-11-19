package main

import (
	"math"
	"sort"
	"testing"
	"time"
)

// Every built-in scenario resolves (PickTargets) to an existing live sensor of the campus-style live engine, and
// applying it changes that sensor's window values by its kind: flatline and set exact, ramp monotone, step up by
// amp, spike then back.
func TestScenarioTargetsLiveAndKinds(t *testing.T) {
	for _, base := range Scenarios {
		sc := base
		t.Run(sc.ID, func(t *testing.T) {
			eng := newTestEngine(t)
			eng.NoiseScale = 0
			eng.SetLive(4 * time.Hour)
			now := nowTime().Unix()
			hist := map[string]float64{} // newest historical value per sensor
			put := func(ts int64, i int, steady bool) {
				for _, k := range eng.bankOrder {
					sn := eng.bank[k]
					rng := sn.Max - sn.Min
					v := sn.Min + 0.4*rng
					if sn.Metric == "occ" {
						v = 0
					} else if steady {
						v = hist[k]
					} else {
						v += 0.04 * rng * math.Sin(float64(i)*0.9+float64(len(k)))
					}
					if !steady {
						hist[k] = v
					}
					vv := v
					if _, err := eng.IngestReading(Reading{Node: sn.Node, Metric: sn.Metric, Value: &vv, Ts: float64(ts)}, nowTime().Unix()); err != nil {
						t.Fatal(err)
					}
				}
			}
			i := 0
			for ts := now - 4*3600 + 300; ts <= now; ts += 300 {
				put(ts, i, false)
				i++
			}
			eng.LiveReady()
			eng.Tick()
			orig := sc.Targets
			sc.Targets = eng.PickTargets(sc.Targets)
			seen := map[string]bool{}
			for j, tg := range sc.Targets {
				if _, ok := eng.bank[key(tg.Node, tg.Metric)]; !ok {
					t.Fatalf("target %s %s (requested %s) is not a live sensor", tg.Node, tg.Metric, orig[j].Node)
				}
				if seen[key(tg.Node, tg.Metric)] {
					t.Fatalf("duplicate target %s %s", tg.Node, tg.Metric)
				}
				seen[key(tg.Node, tg.Metric)] = true
				t.Logf("%s %s: %s -> %s", sc.ID, tg.Metric, orig[j].Node, tg.Node)
			}
			injs := eng.Inject(sc)
			saved := clockOffset
			defer func() { clockOffset = saved }()
			for n := 1; n <= 40; n++ {
				clockOffset = saved + time.Duration(n)*5*time.Minute
				put(nowTime().Unix(), 0, true)
				eng.Tick()
			}
			for _, in := range injs {
				k := key(in.Node, in.Metric)
				var bs []int64
				for b := range eng.series[k] {
					if b >= in.Start && b < in.Start+int64(in.Dur)*300 {
						bs = append(bs, b)
					}
				}
				sort.Slice(bs, func(a, b int) bool { return bs[a] < bs[b] })
				if len(bs) < 8 {
					t.Fatalf("%s %s: only %d injected points", in.Node, in.Metric, len(bs))
				}
				vals := make([]float64, len(bs))
				for j, b := range bs {
					vals[j] = eng.series[k][b]
				}
				b0 := hist[k]
				m := Metrics[eng.Meta.Nodes[in.Node].Role+"/"+in.Metric]
				clamp := func(v float64) float64 {
					if m.Hi > m.Lo {
						return math.Min(m.Hi, math.Max(m.Lo, v))
					}
					return v
				}
				switch in.Kind {
				case "flatline":
					for _, v := range vals {
						if v != in.base {
							t.Fatalf("flatline not exact: %v want %v", v, in.base)
						}
					}
				case "set":
					for _, v := range vals {
						if v != clamp(in.Amp) {
							t.Fatalf("set not exact: %v want %v", v, in.Amp)
						}
					}
				case "ramp_up", "exp_rise":
					for j := 1; j < len(vals); j++ {
						if vals[j] < vals[j-1]-1e-9 {
							t.Fatalf("%s not monotone at %d: %v", in.Kind, j, vals)
						}
					}
					if vals[len(vals)-1] <= vals[0] {
						t.Fatalf("%s did not rise: %v", in.Kind, vals)
					}
				case "ramp_down":
					for j := 1; j < len(vals); j++ {
						if vals[j] > vals[j-1]+1e-9 {
							t.Fatalf("ramp_down not monotone at %d: %v", j, vals)
						}
					}
					if vals[len(vals)-1] >= vals[0] {
						t.Fatalf("ramp_down did not fall: %v", vals)
					}
				case "step_up":
					want := clamp(b0 + in.Amp)
					if math.Abs(vals[len(vals)-1]-want) > 1e-6 || math.Abs(vals[0]-b0) > 1e-6 {
						t.Fatalf("step_up first %v last %v want %v -> %v", vals[0], vals[len(vals)-1], b0, want)
					}
				case "spike":
					up, want := 0, clamp(b0+in.Amp)
					for _, v := range vals {
						if math.Abs(v-want) < 1e-6 {
							up++
						} else if math.Abs(v-b0) > 1e-6 {
							t.Fatalf("spike value %v neither base %v nor peak %v", v, b0, want)
						}
					}
					if up == 0 || math.Abs(vals[len(vals)-1]-b0) > 1e-6 {
						t.Fatalf("spike did not rise and return: %v", vals)
					}
				default: // throttle, oscillate: must leave the base
					moved := false
					for _, v := range vals {
						if math.Abs(v-b0) > 1e-6 {
							moved = true
						}
					}
					if !moved {
						t.Fatalf("%s did not change the window: %v", in.Kind, vals)
					}
				}
			}
		})
	}
}
