package main

// P1 (proofs/2026-10-25_domain_plan/PLAN status): two agent-output checks that run after the model.
//
//   - applyHVACRule (post rule "hvac_rule", in post_rules=all): when the deterministic HVAC rule (ClassifyHVAC,
//     the exact Go mirror of the training teacher hvac.classify_hvac) finds an event at warning or above on the
//     agent's own window and the model calls the unit normal or a sensor fault, the rule's pattern / status /
//     cause are used.
//   - claimFlags (always on, flags only): observation claims that contradict the window's own facts -
//     a night / weekend / off-hours claim when the window end is not off-hours (or a daytime claim when it is),
//     a direction word against its own "from A to B" numbers, "inside the band" when E1 says the room is outside.
//     The observation text is NEVER rewritten or removed: operator wording belongs to the reasoner, which reads
//     AgentCall.ClaimFlags. Mirrored by proofs/2026-10-25_domain_plan/scripts/dp_lib.claim_flags.

import (
	"regexp"
	"strconv"
	"strings"
)

// ClaimFlag: one contradicted claim in observation Obs (0-based), with the evidence ids the observation cites.
type ClaimFlag struct {
	Kind     string   `json:"kind"` // time_of_day | direction | inside_band
	Obs      int      `json:"obs"`
	Claim    string   `json:"claim"`
	Fact     string   `json:"fact"`
	Evidence []string `json:"evidence,omitempty"`
}

func applyHVACRule(hv *Finding, f *Finding) []postChange {
	if hv == nil || (hv.Status != "warning" && hv.Status != "critical") || !contains(HVACEventPatterns, hv.Pattern) {
		return nil
	}
	// the model calls the unit normal, or calls a sensor fault the rule's own fault checks (run first) do not see
	if f.Status != "sensor_fault" && f.Status != "normal" && !contains(HVACNormalPatterns, f.Pattern) {
		return nil
	}
	var ch []postChange
	set := func(field string, from *string, to string) {
		if *from != to {
			ch = append(ch, postChange{"hvac_rule", field, *from, to})
			*from = to
		}
	}
	set("pattern", &f.Pattern, hv.Pattern)
	set("status", &f.Status, hv.Status)
	set("likely_cause", &f.LikelyCause, hv.LikelyCause)
	if hv.EventActive != nil {
		was := ""
		if f.EventActive != nil {
			was = boolStr(*f.EventActive)
		}
		if was != boolStr(*hv.EventActive) {
			b := *hv.EventActive
			f.EventActive = &b
			ch = append(ch, postChange{"hvac_rule", "event_active", was, boolStr(b)})
		}
	}
	if hv.Onset != "" {
		set("onset", &f.Onset, hv.Onset)
	}
	f.FaultKind = ""
	return ch
}

var (
	rxNight  = regexp.MustCompile(`(?i)\b(night|overnight|night-time|nighttime|off-hours|off hours|after hours|after-hours|weekend|midnight)\b`)
	rxDay    = regexp.MustCompile(`(?i)\b(daytime|day-time|working hours|work hours|office hours|business hours)\b`)
	rxFromTo = regexp.MustCompile(`(?i)from\s+(-?\d+(?:\.\d+)?)[^\d\-]{0,12}?\s*(?:to|->|→)\s*(-?\d+(?:\.\d+)?)`)
	rxUp     = regexp.MustCompile(`(?i)\b(up|rose|rise|rising|risen|increas\w*|climb\w*|grew|grow\w*|jump\w*|higher)\b`)
	rxDown   = regexp.MustCompile(`(?i)\b(down|fell|fall\w*|drop\w*|decreas\w*|declin\w*|lower\w*|sank|dipp?\w*)\b`)
	rxInBand = regexp.MustCompile(`(?i)\b(inside|within|in)\s+(the\s+)?(comfort\s+)?band\b`)
	rxHvE1   = regexp.MustCompile(`(?m)^E1 room now ([-\d.]+) C, setpoint [-\d.]+ C \(band ([-\d.]+)-([-\d.]+)\)`)
	rxEids   = regexp.MustCompile(`\[([E\d,\s]+)\]\s*$`)
)

func claimFlags(role string, end int64, prompt string, obs []string) []ClaimFlag {
	off := IsOffHours(end)
	if role == "hvac" {
		off = hvOffHours(end)
	}
	var out []ClaimFlag
	for k, o := range obs {
		var ev []string
		if m := rxEids.FindStringSubmatch(o); m != nil {
			for _, e := range strings.Split(m[1], ",") {
				if e = strings.TrimSpace(e); e != "" {
					ev = append(ev, e)
				}
			}
		}
		if m := rxNight.FindStringSubmatch(o); m != nil && !off {
			out = append(out, ClaimFlag{"time_of_day", k, strings.ToLower(m[1]), "window end is not off-hours", ev})
		}
		if m := rxDay.FindStringSubmatch(o); m != nil && off {
			out = append(out, ClaimFlag{"time_of_day", k, strings.ToLower(m[1]), "window end is off-hours", ev})
		}
		if m := rxFromTo.FindStringSubmatch(o); m != nil {
			a, e1 := strconv.ParseFloat(m[1], 64)
			b, e2 := strconv.ParseFloat(m[2], 64)
			up, dn := rxUp.MatchString(o), rxDown.MatchString(o)
			if e1 == nil && e2 == nil && up != dn && a != b && ((up && b < a) || (dn && b > a)) {
				c := "down"
				if up {
					c = "up"
				}
				out = append(out, ClaimFlag{"direction", k, c, "from " + strconv.FormatFloat(a, 'g', -1, 64) + " to " + strconv.FormatFloat(b, 'g', -1, 64), ev})
			}
		}
		if role == "hvac" && rxInBand.MatchString(o) {
			if m := rxHvE1.FindStringSubmatch(prompt); m != nil {
				now, _ := strconv.ParseFloat(m[1], 64)
				lo, _ := strconv.ParseFloat(m[2], 64)
				hi, _ := strconv.ParseFloat(m[3], 64)
				if now < lo || now > hi {
					out = append(out, ClaimFlag{"inside_band", k, "inside band", "room " + m[1] + " C, band " + m[2] + "-" + m[3], append(ev, "E1")})
				}
			}
		}
	}
	return out
}
