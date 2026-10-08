package main

// Live sensor bank: the ONLY data source. Each sensor holds a current value that the user sets with the
// dashboard sliders, or that a real device POSTs to /api/ingest. Every poll the engine samples every
// sensor's current value (plus optional realistic measurement jitter) as that sensor's next 5-minute
// reading, so the rest of the pipeline (windows, statistics, rule patterns, event gate, Mode 1/2/3
// agents) is exactly what a physical sensor feed would drive.

import (
	"encoding/json"
	"fmt"
	"math"
	"math/rand"
	"os"
	"path/filepath"
	"time"
)

type SimSensor struct {
	Node     string  `json:"node"`
	Role     string  `json:"role"`
	Metric   string  `json:"metric"`
	Label    string  `json:"label"`
	Location string  `json:"location"`
	Building string  `json:"building"`
	Level    string  `json:"level"`
	Min      float64 `json:"min"`
	Max      float64 `json:"max"`
	Step     float64 `json:"step"`
	Value    float64 `json:"value"`
	Noise    float64 `json:"noise"`
	Unit     string  `json:"unit"`
	Source   string  `json:"source"`  // "slider" or "api" (who set the value last)
	SetAt    int64   `json:"set_at"`  // wall-clock unix time of the last change
	Default  float64 `json:"default"` // value from sensors.json, restored by "reset values"
}

type sensorFile struct {
	Sensors []SimSensor `json:"sensors"`
}

func loadSensors(dir string) ([]*SimSensor, error) {
	b, err := os.ReadFile(filepath.Join(dir, "data", "sensors.json"))
	if err != nil {
		return nil, err
	}
	var f sensorFile
	if err := json.Unmarshal(b, &f); err != nil {
		return nil, fmt.Errorf("sensors.json: %w", err)
	}
	out := make([]*SimSensor, 0, len(f.Sensors))
	for i := range f.Sensors {
		s := f.Sensors[i]
		if s.Max <= s.Min || s.Node == "" || s.Metric == "" {
			return nil, fmt.Errorf("sensors.json: bad entry %d (%s %s)", i, s.Node, s.Metric)
		}
		if m, ok := Metrics[s.Role+"/"+s.Metric]; ok {
			s.Unit = m.Unit
		}
		s.Default, s.Source = s.Value, "default"
		out = append(out, &s)
	}
	return out, nil
}

// reading draws one measurement from a sensor's current value (caller holds e.mu).
func (e *Engine) reading(s *SimSensor) float64 {
	v := s.Value
	if s.Noise > 0 && e.NoiseScale > 0 {
		v += e.rng.NormFloat64() * s.Noise * e.NoiseScale
	}
	switch s.Metric {
	case "occ":
		if v >= 0.5 {
			return 1
		}
		return 0
	case "ac_units_on":
		v = math.Round(v)
	}
	return math.Min(s.Max, math.Max(s.Min, v))
}

// SetSensor sets a sensor's current value (slider or real-device ingest). Returns the stored value.
func (e *Engine) SetSensor(node, metric string, v float64, source string) (float64, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	s := e.bank[key(node, metric)]
	if s == nil {
		return 0, fmt.Errorf("unknown sensor %s %s", node, metric)
	}
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return 0, fmt.Errorf("value must be a number")
	}
	s.Value = math.Min(s.Max, math.Max(s.Min, v))
	s.Source, s.SetAt = source, nowTime().Unix()
	return s.Value, nil
}

// Sensors returns a copy of the bank in file order.
func (e *Engine) Sensors() []SimSensor {
	e.mu.RLock()
	defer e.mu.RUnlock()
	out := make([]SimSensor, 0, len(e.bankOrder))
	for _, k := range e.bankOrder {
		out = append(out, *e.bank[k])
	}
	return out
}

// ResetValues restores every sensor to its sensors.json default.
func (e *Engine) ResetValues() {
	e.mu.Lock()
	defer e.mu.Unlock()
	for _, s := range e.bank {
		s.Value, s.Source, s.SetAt = s.Default, "default", nowTime().Unix()
	}
}

// clockOffset corrects a wrong device clock (the QIDK ships set to 2023): deploy.ps1 passes the
// laptop's time with --clock-unix. Without it the device clock is used as is.
var clockOffset time.Duration

// The QIDK's RTC comes up in 2023 after a reboot and is fixed by NTP once Wi-Fi connects; a correction
// that stacks on an already-synced clock pushed the sensor clock 3 years ahead. A large offset is only
// applied while the device clock is still unsynced (before 2025); after an NTP jump it is dropped.
func needClockFix() bool { return time.Now().Year() < 2025 }

func nowTime() time.Time {
	if clockOffset != 0 && (clockOffset > 24*time.Hour || clockOffset < -24*time.Hour) && !needClockFix() {
		return time.Now()
	}
	return time.Now().Add(clockOffset)
}

func newRNG() *rand.Rand { return rand.New(rand.NewSource(time.Now().UnixNano())) }
