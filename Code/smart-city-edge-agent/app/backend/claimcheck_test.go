package main

import (
	"testing"
	"time"
)

func TestClaimFlags(t *testing.T) {
	day := time.Date(2026, 10, 21, 13, 40, 0, 0, IST).Unix()   // Wednesday 13:40
	night := time.Date(2026, 10, 21, 23, 30, 0, 0, IST).Unix() // off-hours
	obs := []string{"Night-time water activity, not a usual demand period [E1]", "Level down from 450 to 928 ppm, step at 13:45 [E7,E5]"}
	fl := claimFlags("water", day, "", obs)
	if len(fl) != 2 || fl[0].Kind != "time_of_day" || fl[0].Claim != "night" || fl[1].Kind != "direction" || fl[1].Fact != "from 450 to 928" {
		t.Fatalf("day flags %+v", fl)
	}
	if fl[1].Evidence[0] != "E7" || fl[1].Evidence[1] != "E5" {
		t.Fatalf("evidence %+v", fl[1].Evidence)
	}
	if fl := claimFlags("water", night, "", obs[:1]); len(fl) != 0 {
		t.Fatalf("night claim at night flagged: %+v", fl)
	}
	if fl := claimFlags("water", night, "", []string{"Routine daytime drain, refill will follow [E4]"}); len(fl) != 1 || fl[0].Fact != "window end is off-hours" {
		t.Fatalf("daytime claim at night: %+v", fl)
	}
	if fl := claimFlags("power", day, "", []string{"Load rose from 3.1 to 4.0 kW [E7]"}); len(fl) != 0 {
		t.Fatalf("consistent direction flagged: %+v", fl)
	}
	p := "x\nE1 room now 30.0 C, setpoint 26.0 C (band 23.0-28.0)\nE2 max"
	fl = claimFlags("hvac", day, p, []string{"Room steady at 30.0 C inside the band around 26 [E1,E4]"})
	if len(fl) != 1 || fl[0].Kind != "inside_band" {
		t.Fatalf("inside band: %+v", fl)
	}
	if fl := claimFlags("hvac", day, "E1 room now 25.0 C, setpoint 26.0 C (band 23.0-28.0)", []string{"Room within the band [E1]"}); len(fl) != 0 {
		t.Fatalf("true inside-band claim flagged: %+v", fl)
	}
	// flags never touch the text
	if obs[0] != "Night-time water activity, not a usual demand period [E1]" {
		t.Fatal("observation changed")
	}
}

func TestApplyHVACRule(t *testing.T) {
	tr, fa := true, false
	hv := Finding{Pattern: "no_cooling_effect", Status: "critical", LikelyCause: "ac_not_cooling", EventActive: &tr, Onset: "12:10"}
	f := Finding{Pattern: "stable", Status: "normal", LikelyCause: "normal_operation", EventActive: &fa}
	ch := applyHVACRule(&hv, &f)
	if len(ch) != 5 || f.Pattern != "no_cooling_effect" || f.Status != "critical" || f.LikelyCause != "ac_not_cooling" || !*f.EventActive || f.Onset != "12:10" {
		t.Fatalf("not applied: %+v %+v", ch, f)
	}
	// the model already reports an event: kept
	f = Finding{Pattern: "too_hot", Status: "warning", LikelyCause: "high_heat_load"}
	if ch := applyHVACRule(&hv, &f); len(ch) != 0 || f.Pattern != "too_hot" {
		t.Fatalf("event answer overridden: %+v", ch)
	}
	// a sensor fault the rule does not see (its fault checks run first): the rule event wins
	f = Finding{Pattern: "flatline", Status: "sensor_fault", LikelyCause: "sensor_fault", FaultKind: "stuck"}
	if ch := applyHVACRule(&hv, &f); len(ch) != 5 || f.Status != "critical" || f.FaultKind != "" {
		t.Fatalf("sensor fault vs rule event not replaced: %+v %+v", ch, f)
	}
	// rule normal / not an event: nothing
	n := Finding{Pattern: "pull_down", Status: "normal", LikelyCause: "normal_operation"}
	f = Finding{Pattern: "stable", Status: "normal", LikelyCause: "normal_operation"}
	if ch := applyHVACRule(&n, &f); len(ch) != 0 {
		t.Fatalf("normal rule applied: %+v", ch)
	}
}

func TestPostLongDrain(t *testing.T) {
	xs := make([]float64, 48)
	for i := range xs {
		xs[i] = 80
		if i >= 12 {
			xs[i] = 80 - 0.8*float64(i-11)
		}
	}
	if !postLongDrain(xs, 0.1) {
		t.Fatal("steady 3 h drain not detected")
	}
	ys := append([]float64(nil), xs...)
	for i := 30; i < 34; i++ {
		ys[i] += 10 // a refill inside the last 3 h
	}
	if postLongDrain(ys, 0.1) {
		t.Fatal("drain with a refill detected as long drain")
	}
	if postLongDrain(xs[20:], 0.1) {
		t.Fatal("window shorter than 3 h")
	}
	if !postE9Falling("a\nE9 12 h view: slow drift -12.0 level since 03:10 (r2 0.91, 4.0x normal variation)\nE10 x") ||
		postE9Falling("a\nE9 12 h view: slow drift +3.0 level since 03:10\nE10") || postE9Falling("E9 none") {
		t.Fatal("E9 drift parse")
	}
}
