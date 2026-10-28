package main

import (
	"bufio"
	"os"
	"strconv"
	"strings"
	"testing"
)

// TestDQRealSCRCReplay replays a real SCRC CO2 series (data/series, 5-min bucket means of the raw feed)
// through both ingest paths over every stretch of 3 days that holds a real outage (> 1 h, < 12 h):
//   - before: the legacy held path (a device that stops posting keeps "reading" its last value),
//   - after: the measured path (ts per reading).
//
// It counts fabricated readings and AI candidates raised while the window held fabricated data.
// Skipped when the local data is not present (data never leaves the laptop).
func TestDQRealSCRCReplay(t *testing.T) {
	path := "../../data/series/air_quality/SR-AQ-KH03-03.csv"
	f, err := os.Open(path)
	if err != nil {
		t.Skip("real series not present: " + path)
	}
	defer f.Close()
	vals := map[int64]float64{}
	var first, last int64
	sc := bufio.NewScanner(f)
	sc.Scan() // header bucket,co2,...
	for sc.Scan() {
		p := strings.Split(sc.Text(), ",")
		if len(p) < 2 || p[1] == "" {
			continue
		}
		b, _ := strconv.ParseInt(p[0], 10, 64)
		v, err := strconv.ParseFloat(p[1], 64)
		if err != nil {
			continue
		}
		vals[b] = v
		if first == 0 || b < first {
			first = b
		}
		if b > last {
			last = b
		}
	}
	// stretches: 6 h of complete lead-in, then 3 days containing a gap of 13..144 buckets
	type stretch struct{ start int64 }
	var sts []stretch
	for b := first; b+int64(72*3600) < last && len(sts) < 6; b += 3600 {
		lead := true
		for i := int64(0); i < 72 && lead; i++ {
			_, lead = vals[b+i*bucketSec]
		}
		if !lead {
			continue
		}
		gap, best := 0, 0
		for i := int64(72); i < 72+864; i++ {
			if _, ok := vals[b+i*bucketSec]; ok {
				gap = 0
			} else if gap++; gap > best {
				best = gap
			}
		}
		if best > 12 && best <= 144 {
			sts = append(sts, stretch{b})
			b += 4 * 86400
		}
	}
	if len(sts) == 0 {
		t.Skip("no outage stretch found")
	}
	defer func() { apiHoldSec = 900 }()
	var fabBefore, fabAfter, candBefore, candAfter, gapBuckets, insuff int
	for _, s := range sts {
		for _, measured := range []bool{false, true} {
			if !measured {
				apiHoldSec = 1 << 40 // the code before this change: a held value never expired
			} else {
				apiHoldSec = 900
			}
			e := dqEngine(t)
			k := key(dqNode, dqMetric)
			var cands []Candidate
			e.onEvent = func(c []Candidate) {
				for _, x := range c {
					if x.Node == dqNode && x.Metric == dqMetric {
						cands = append(cands, x)
					}
				}
			}
			wall := int64(2_000_000_000)
			lastSet := wall
			for i := int64(0); i < 72+864; i++ {
				v, ok := vals[s.start+i*bucketSec]
				wall += bucketSec
				if ok {
					if measured {
						if _, err := e.IngestReading(Reading{Node: dqNode, Metric: dqMetric, Value: fp(v), Ts: float64(wall)}, wall); err != nil {
							t.Fatal(err)
						}
					} else {
						e.SetSensor(dqNode, dqMetric, v, "api")
						lastSet = wall
					}
				}
				// legacy path: sensor wall clock is the replay clock (SetAt checked against nowTime)
				e.bank[k].SetAt = nowTime().Unix() - (wall - lastSet)
				e.Tick()
				_, got := e.series[k][e.sim]
				if !ok {
					if measured {
						gapBuckets++
					}
					if got {
						if measured {
							fabAfter++
						} else {
							fabBefore++
						}
					}
				}
				if measured && e.states[k].Status == "insufficient_data" && i >= 72 {
					insuff++
				}
			}
			if measured {
				candAfter += len(cands)
			} else {
				candBefore += len(cands)
			}
		}
	}
	t.Logf("real SCRC SR-AQ-KH03-03 co2: %d stretches of 3 days with outages; %d missing 5-min buckets", len(sts), gapBuckets)
	t.Logf("before (held ingest): %d fabricated readings, %d AI candidates", fabBefore, candBefore)
	t.Logf("after (measured ingest): %d fabricated readings, %d AI candidates, %d bucket-polls insufficient_data", fabAfter, candAfter, insuff)
	if fabAfter != 0 {
		t.Fatalf("the measured path invented %d readings", fabAfter)
	}
	if fabBefore == 0 {
		t.Fatal("test premise: the held path should have filled outage buckets")
	}
}
