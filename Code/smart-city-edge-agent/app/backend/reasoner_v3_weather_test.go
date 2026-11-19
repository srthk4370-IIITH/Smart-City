package main

import (
	"strings"
	"testing"
)

// deploy22: a weather-only critical incident (outdoor heat; INC-0564) may start with monitor/review_schedule;
// any incident with a building/facility sensor flagged still needs inspect_* or request_facility_review.
func TestV3WeatherOnlyCriticalFloor(t *testing.T) {
	mon := []V3ChecklistItem{{Action: "monitor"}, {Action: "inspect_ventilation"}}
	if e := v3ActionFloor("critical", mon, true); e != "" {
		t.Fatalf("weather-only monitor rejected: %s", e)
	}
	if e := v3ActionFloor("critical", []V3ChecklistItem{{Action: "review_schedule"}}, true); e != "" {
		t.Fatalf("weather-only review_schedule rejected: %s", e)
	}
	for _, a := range []string{"none", "check_sensor"} {
		if e := v3ActionFloor("critical", []V3ChecklistItem{{Action: a}}, true); e == "" {
			t.Fatalf("weather-only critical %s accepted", a)
		}
	}
	if e := v3ActionFloor("critical", mon, false); !strings.Contains(e, "must start") {
		t.Fatalf("mixed/facility critical monitor accepted")
	}
	// warning/normal/sensor_fault floors are unchanged by weatherOnly
	if v3ActionFloor("sensor_fault", mon, true) == "" || v3ActionFloor("normal", []V3ChecklistItem{{Action: "inspect_hvac"}}, true) == "" {
		t.Fatal("weatherOnly loosened a non-critical floor")
	}
	// end to end through the gate: v3Good with monitor first
	known := v3Prompt + "\nlimit 1500"
	txt := strings.Replace(v3Good, `"inspect_ventilation"`, `"monitor"`, 1)
	if _, errs, _ := checkReportV3For(txt, known, true); len(errs) != 0 {
		t.Fatalf("weather-only report rejected: %v", errs)
	}
	if _, errs, _ := checkReportV3For(txt, known, false); !strings.Contains(strings.Join(errs, ";"), "must start") {
		t.Fatalf("facility report accepted: %v", errs)
	}
	w := &Incident{Roles: []string{"weather"}}
	m := &Incident{Roles: []string{"weather", "air_quality"}}
	if !weatherOnlyIncident(w) || weatherOnlyIncident(m) || weatherOnlyIncident(&Incident{}) {
		t.Fatal("weatherOnlyIncident")
	}
}
