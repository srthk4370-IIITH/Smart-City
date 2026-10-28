package main

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func retWin(base, last float64) []float64 {
	xs := make([]float64, 48)
	for i := range xs {
		xs[i] = base + 5*math.Sin(float64(i))
		if i >= 40 {
			xs[i] = last + 3*math.Sin(float64(i))
		}
	}
	return xs
}

func retSensor(metric string, last float64, status string) SensorRef {
	role := "air_quality"
	xs := retWin(600, last)
	f := Finding{Pattern: "step_increase", Status: status, LikelyCause: "ventilation_insufficient",
		Observations: []string{"CO2 stepped up in the classroom [E5]"}}
	return SensorRef{Ref: "S1", Node: "SR-AQ-KH03-03", Metric: metric, Role: role, Xs: xs, End: 1_790_000_000, Rule: f}
}

func pastIncident(id string, metric string, last float64, sev string) *Incident {
	return &Incident{ID: id, Mode: 3, State: "done", Title: "CO2 step increase: KH building", Severity: sev,
		Sensors: []SensorRef{retSensor(metric, last, "warning")},
		Final: &ReportCall{Valid: true, Model: "reasoner v3", Parsed: &Report{Severity: sev, Label: "ventilation_insufficient",
			Action:       ActionOfRole("air_quality", "ventilation_insufficient", sev),
			RootCause:    "CO2 rose to 1850 ppm in a full classroom with the ventilation off",
			Observations: []V3Observation{{Text: "CO2 stepped up to 1850 ppm [S1]"}}}}}
}

func retReasoner(t *testing.T) *Reasoner {
	t.Helper()
	dir := t.TempDir()
	return NewReasoner(NewGenieRunner(dir, dir, true), nil, dir, func(string, any) {})
}

// Hit: wording from the similar past report, numbers from the LIVE window only, severity floor = max(rules, retrieved).
func TestRetrievalHitLiveNumbersAndSeverityFloor(t *testing.T) {
	r := retReasoner(t)
	r.ret.add(pastIncident("INC-0007", "co2", 1850, "critical"))
	inc := &Incident{ID: "INC-0100", Mode: 3, State: "running", Title: "CO2 step increase: KH building",
		Sensors: []SensorRef{retSensor("co2", 1700, "warning")}}
	rc := r.retrievalPreliminary(inc)
	if !strings.Contains(rc.Note, "based on 1 similar") || !strings.Contains(rc.Note, "INC-0007") {
		t.Fatalf("hit note %q", rc.Note)
	}
	if rc.Parsed.Severity != "critical" {
		t.Fatalf("severity floor: %s, want critical (retrieved) over warning (rules)", rc.Parsed.Severity)
	}
	all := rc.Parsed.Explanation + rc.Parsed.RootCause + rc.Parsed.Title
	if strings.Contains(all, "1850") {
		t.Fatalf("an old number leaked into the preliminary: %q", all)
	}
	if len(inc.Retrieved) != 1 || inc.Retrieved[0].ID != "INC-0007" {
		t.Fatalf("retrieved %+v", inc.Retrieved)
	}
}

// Miss: another metric -> rules preliminary with the "full AI report coming" message.
func TestRetrievalMissFallback(t *testing.T) {
	r := retReasoner(t)
	r.ret.add(pastIncident("INC-0007", "co2", 1850, "critical"))
	inc := &Incident{ID: "INC-0101", Mode: 3, State: "running", Title: "Temperature step increase",
		Sensors: []SensorRef{retSensor("temp", 31, "warning")}}
	rc := r.retrievalPreliminary(inc)
	if rc.Note != "Preliminary from the rules - full AI report coming" || len(inc.Retrieved) != 0 {
		t.Fatalf("miss: note %q retrieved %+v", rc.Note, inc.Retrieved)
	}
	if rc.Parsed == nil || rc.Parsed.Severity == "critical" {
		t.Fatalf("miss must keep the rules severity: %+v", rc.Parsed)
	}
}

// The index is rebuilt from the incident store on start.
func TestRetrievalIndexRebuild(t *testing.T) {
	dir := t.TempDir()
	r := NewReasoner(NewGenieRunner(dir, dir, true), nil, dir, func(string, any) {})
	inc := pastIncident("INC-0007", "co2", 1850, "critical")
	r.incidents = append(r.incidents, inc)
	r.persist(inc)
	r2 := NewReasoner(NewGenieRunner(dir, dir, true), nil, dir, func(string, any) {})
	if len(r2.ret.docs) != 1 || r2.ret.docs[0].ID != "INC-0007" {
		t.Fatalf("rebuilt index: %d docs", len(r2.ret.docs))
	}
}

// < 5 ms per query at 500 indexed reports.
func TestRetrievalSpeed500(t *testing.T) {
	r := retReasoner(t)
	sev := []string{"warning", "critical", "normal"}
	for i := 0; i < 500; i++ {
		r.ret.add(pastIncident(fmt.Sprintf("INC-%04d", i+1), "co2", 1000+float64(i), sev[i%3]))
	}
	inc := &Incident{ID: "INC-0900", Mode: 3, Title: "CO2 step increase: KH building", Sensors: []SensorRef{retSensor("co2", 1700, "warning")}}
	r.retrievalPreliminary(inc) // warm
	t0 := time.Now()
	const n = 20
	for i := 0; i < n; i++ {
		r.retrievalPreliminary(inc)
	}
	if per := time.Since(t0) / n; per > 5*time.Millisecond {
		t.Fatalf("retrieval preliminary %v per incident at 500 reports, want < 5 ms", per)
	}
}

// Seed library: loaded at start, labelled as reference cases, and a live report outranks an equally close seed.
func TestRetrievalSeedLibrary(t *testing.T) {
	dir := t.TempDir()
	os.MkdirAll(filepath.Join(dir, "data"), 0o755)
	q, _ := retFeatures([]SensorRef{retSensor("co2", 1700, "warning")})
	seed := []SeedDoc{{ID: "seed:r001", Prov: "seed:r001, model:rsn_test", Role: "air_quality", Metric: "co2", Domains: []string{"air_quality"},
		Pattern: q.Pattern, Status: q.Status, Cause: q.Cause, Mag: q.Mag, Pct: q.Pct, Tod: q.Tod, NSensors: q.NSensors,
		Text: "CO2 step increase ventilation insufficient classroom", Severity: "critical", Label: "ventilation_insufficient"}}
	b, _ := json.Marshal(seed)
	os.WriteFile(filepath.Join(dir, "data", "rag_seed.json"), b, 0o644)
	r := NewReasoner(NewGenieRunner(dir, dir, true), nil, dir, func(string, any) {})
	inc := &Incident{ID: "INC-0200", Mode: 3, Title: "CO2 step increase: KH building", Sensors: []SensorRef{retSensor("co2", 1700, "warning")}}
	rc := r.retrievalPreliminary(inc)
	if !strings.Contains(rc.Note, "reference case") || !inc.Retrieved[0].Seed {
		t.Fatalf("seed hit not labelled as a reference case: %q", rc.Note)
	}
	live := pastIncident("INC-0007", "co2", 1700, "warning")
	r.ret.add(live)
	r.retrievalPreliminary(inc)
	if inc.Retrieved[0].ID != "INC-0007" {
		t.Fatalf("live report must outrank an equally close seed: %+v", inc.Retrieved)
	}
}
