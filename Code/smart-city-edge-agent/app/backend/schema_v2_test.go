package main

import "testing"

// The frozen v2 fields (RETRAIN_V2_SPEC.md) are accepted, validated, and never fail a v1-style finding.
func TestSchemaV2Fields(t *testing.T) {
	s := SensorRef{Ref: "S1", Role: "air_quality", Evidence: []Evidence{{ID: "E1"}, {ID: "E8"}}}
	ok := `{"pattern": "flatline", "status": "sensor_fault", "observations": ["Frozen for 30 readings [E8]"], ` +
		`"likely_cause": "sensor_fault", "confidence": 0.8, "event_active": true, "onset": "09:40", "fault_kind": "stuck", "action": "check_sensor"}`
	c := checkAgent(s, GenieResult{Text: ok}, "")
	if !c.Valid || c.Parsed.FaultKind != "stuck" || c.Parsed.Onset != "09:40" || c.Parsed.EventActive == nil || !*c.Parsed.EventActive {
		t.Fatalf("v2 finding: valid=%v %+v errors=%v", c.Valid, c.Parsed, c.Errors)
	}
	bad := `{"pattern": "spike", "status": "warning", "observations": ["Peak [E1]"], "likely_cause": "occupancy_load", ` +
		`"confidence": 0.7, "onset": "9 am", "fault_kind": "stuck", "action": "monitor"}`
	c = checkAgent(s, GenieResult{Text: bad}, "")
	if !c.Valid || c.Parsed.FaultKind != "" || c.Parsed.Onset != "" || len(c.Repairs) < 2 {
		t.Fatalf("invalid v2 fields must be dropped as repairs: valid=%v %+v repairs=%v errors=%v", c.Valid, c.Parsed, c.Repairs, c.Errors)
	}
	// salvage path (malformed JSON) keeps them too
	if f, ok := salvageFinding(`{"pattern": "flatline", "status": "sensor_fault", "observations": ["x [E8]"], "event_active": false, "onset": "10:05", "fault_kind": "quantised",`); !ok || f.Onset != "10:05" || f.FaultKind != "quantised" || f.EventActive == nil || *f.EventActive {
		t.Fatalf("salvage: %+v", f)
	}
}

func TestRecommendOffAllowed(t *testing.T) {
	for _, s := range []string{"AC running in an empty room - recommend switching it off [E7]",
		"Suggest turning the AC unit off after review", "Consider switching the unit off"} {
		if blocksActuation(s) {
			t.Fatalf("recommendation blocked: %q", s)
		}
	}
	for _, s := range []string{"Switch off the pump now", "turn off the AC", "Shut down the chiller", "Recommend we bypass the valve"} {
		if !blocksActuation(s) {
			t.Fatalf("command allowed: %q", s)
		}
	}
	if !actionAllowed("switch_off_ac") || contains(Actions, "switch_off_ac") {
		t.Fatal("switch_off_ac must be allowed but kept out of the v1 prompt list")
	}
}
