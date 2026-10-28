package main

// Port of the deterministic teacher rules in training/generate_dataset.py (status_of, cause_of,
// action_of, observations). Mode 1 = RulePattern + these rules, no LLM.

import (
	"fmt"
	"math"
	"strings"
)

func inSet(s string, set ...string) bool {
	for _, x := range set {
		if s == x {
			return true
		}
	}
	return false
}

func StatusOf(role, metric, pattern string, st Stats, baseMean float64) string {
	m := Metrics[role+"/"+metric]
	if pattern == "flatline" {
		if math.Abs(st.Last) > 1e-6 {
			return "sensor_fault"
		}
		return "normal"
	}
	// Physical plausibility (not in the training rules, added after the app stress test): indoor CO2
	// cannot sit below outdoor air (~420 ppm), so a reading under 350 ppm is a sensor fault. Without
	// this a drop to 270 ppm read as a harmless "step decrease" and raised nothing.
	if role == "air_quality" && metric == "co2" && st.Last < 350 {
		return "sensor_fault"
	}
	if pattern == "erratic" && role != "power" {
		return "sensor_fault"
	}
	if m.HasLimits {
		if m.Dir == "low" || (metric == "ph" && st.Min < 6.5 && st.Last < 7) {
			lv := st.Last
			if inSet(pattern, "spike", "dip") {
				lv = st.Min
			}
			if metric == "ph" {
				if lv < 6.0 {
					return "critical"
				}
				if lv < 6.5 {
					return "warning"
				}
			} else {
				if lv < m.Crit {
					return "critical"
				}
				if lv < m.Warn {
					return "warning"
				}
				return "normal"
			}
		}
		hv := st.Last
		if pattern == "spike" || pattern == "throttling" {
			hv = st.Max
		}
		if hv >= m.Crit {
			return "critical"
		}
		if hv >= m.Warn {
			return "warning"
		}
		if inSet(pattern, "stable", "oscillation", "gradual_decrease", "step_decrease", "dip") {
			return "normal"
		}
		if pattern == "exponential_increase" {
			return "warning"
		}
		return "normal"
	}
	ref := math.Max(math.Abs(baseMean), 1e-6)
	rel := st.Range / ref
	switch {
	case pattern == "stable":
		return "normal"
	case inSet(pattern, "spike", "step_increase", "step_decrease", "dip", "exponential_increase", "throttling", "erratic"):
		if rel > 1.5 {
			return "critical"
		}
		return "warning"
	case inSet(pattern, "gradual_increase", "gradual_decrease"):
		if rel > 0.3 {
			return "warning"
		}
		return "normal"
	case pattern == "oscillation":
		if role == "water" {
			return "warning"
		}
	}
	return "normal"
}

func CauseOf(role, metric, pattern, status string, offHours, indoor, zero bool) string {
	if status == "sensor_fault" {
		return "sensor_fault" // whatever the shape, a faulty reading has one cause (as for flatline/erratic)
	}
	up := inSet(pattern, "gradual_increase", "step_increase", "exponential_increase", "throttling")
	down := inSet(pattern, "gradual_decrease", "step_decrease", "dip")
	if pattern == "flatline" {
		if zero {
			if role == "water" {
				return "normal_usage"
			}
			if role == "power" {
				return "normal_load"
			}
		}
		return "sensor_fault"
	}
	if pattern == "erratic" {
		if role == "power" {
			return "power_quality_issue"
		}
		return "sensor_fault"
	}
	switch role {
	case "air_quality":
		if pattern == "stable" {
			return "normal_conditions"
		}
		switch metric {
		case "co2":
			if inSet(pattern, "exponential_increase", "throttling") {
				return "ventilation_insufficient"
			}
			if inSet(pattern, "gradual_increase", "step_increase") {
				if status == "warning" || status == "critical" {
					return "ventilation_insufficient"
				}
				return "occupancy_load"
			}
			if pattern == "spike" {
				return "occupancy_load"
			}
			if pattern == "oscillation" {
				if status != "normal" {
					return "ventilation_insufficient"
				}
				return "occupancy_load"
			}
			return "normal_conditions"
		case "pm25", "pm10":
			if pattern == "spike" {
				if indoor {
					return "indoor_emission_source"
				}
				return "outdoor_pollution_ingress"
			}
			if up || pattern == "oscillation" {
				return "outdoor_pollution_ingress"
			}
			return "normal_conditions"
		case "temp":
			if up || inSet(pattern, "oscillation", "spike") {
				if indoor {
					return "hvac_cooling_issue"
				}
			}
			return "normal_conditions"
		case "rh":
			if up || pattern == "spike" {
				return "humidity_control_issue"
			}
			return "normal_conditions"
		}
	case "water":
		switch metric {
		case "level":
			switch {
			case pattern == "stable":
				return "normal_usage"
			case pattern == "gradual_decrease":
				if offHours {
					return "possible_leak"
				}
				return "tank_draining"
			case inSet(pattern, "step_decrease", "dip"):
				return "tank_draining"
			case up:
				return "tank_filling"
			case pattern == "oscillation":
				return "pump_cycling"
			case pattern == "spike":
				return "sensor_fault"
			}
		case "flow":
			switch {
			case pattern == "stable":
				if offHours && !zero {
					return "possible_leak"
				}
				return "normal_usage"
			case inSet(pattern, "spike", "gradual_increase", "throttling"):
				return "high_demand"
			case inSet(pattern, "step_increase", "exponential_increase"):
				if offHours {
					return "possible_leak"
				}
				return "high_demand"
			case down:
				if status != "normal" {
					return "supply_interruption"
				}
				return "normal_usage"
			case pattern == "oscillation":
				return "pump_cycling"
			}
		case "tds", "ph":
			if pattern == "stable" {
				return "normal_usage"
			}
			if status == "warning" || status == "critical" {
				return "water_quality_issue"
			}
			return "normal_usage"
		}
	case "power":
		if metric == "pf" {
			if down || (pattern == "oscillation" && status != "normal") {
				return "power_quality_issue"
			}
			return "normal_load"
		}
		return map[string]string{"stable": "normal_load", "spike": "load_surge", "step_increase": "equipment_startup",
			"gradual_increase": "gradual_load_growth", "exponential_increase": "load_surge",
			"dip": "load_drop_or_outage", "step_decrease": "load_drop_or_outage",
			"gradual_decrease": "normal_load", "oscillation": "cyclic_equipment",
			"throttling": "capacity_limit_throttling"}[pattern]
	case "weather":
		if pattern == "stable" {
			return "normal_weather"
		}
		switch metric {
		case "temp":
			switch {
			case up:
				return "heat_buildup"
			case pattern == "gradual_decrease":
				return "cooling_trend"
			case inSet(pattern, "step_decrease", "dip"):
				return "weather_front"
			case pattern == "spike":
				return "sensor_fault"
			case pattern == "oscillation":
				return "weather_front"
			}
		case "rh":
			if up || pattern == "step_decrease" {
				return "weather_front"
			}
			if pattern == "spike" {
				return "sensor_fault"
			}
			return "normal_weather"
		case "wind":
			if inSet(pattern, "spike", "oscillation") {
				return "gusty_wind"
			}
			if up {
				return "weather_front"
			}
			return "normal_weather"
		}
	}
	return "sensor_fault"
}

var actionOf = map[string]string{
	"normal_conditions": "none", "normal_usage": "none", "normal_load": "none", "normal_weather": "none",
	"diurnal_cycle": "none", "vacant": "none", "normal_occupancy": "none", "arrival": "none", "departure": "none",
	"occupancy_load": "monitor", "ventilation_insufficient": "inspect_ventilation",
	"outdoor_pollution_ingress": "inspect_ventilation", "indoor_emission_source": "request_facility_review",
	"hvac_cooling_issue": "inspect_hvac", "humidity_control_issue": "inspect_hvac", "sensor_fault": "check_sensor",
	"high_demand": "monitor", "possible_leak": "inspect_water_system", "tank_filling": "monitor",
	"tank_draining": "monitor", "supply_interruption": "inspect_water_system", "pump_cycling": "inspect_water_system",
	"water_quality_issue": "request_facility_review", "load_surge": "monitor", "equipment_startup": "monitor",
	"load_drop_or_outage": "inspect_electrical", "capacity_limit_throttling": "inspect_electrical",
	"gradual_load_growth": "review_schedule", "cyclic_equipment": "monitor", "power_quality_issue": "inspect_electrical",
	"heat_buildup": "monitor", "cooling_trend": "none", "weather_front": "monitor", "gusty_wind": "monitor",
	"intermittent_presence": "monitor", "off_hours_presence": "request_facility_review",
}

func ActionOf(cause, status string) string {
	a := actionOf[cause]
	if a == "" {
		a = "monitor"
	}
	if a == "none" && (status == "warning" || status == "critical") {
		return "monitor"
	}
	if a == "monitor" && status == "critical" {
		if v, ok := map[string]string{"load_surge": "inspect_electrical", "equipment_startup": "inspect_electrical",
			"high_demand": "inspect_water_system", "occupancy_load": "inspect_ventilation",
			"heat_buildup": "monitor", "gusty_wind": "monitor"}[cause]; ok {
			return v
		}
		return "request_facility_review"
	}
	return a
}

var nice = map[string]string{"co2": "CO2", "pm25": "PM2.5", "pm10": "PM10", "temp": "Temperature", "rh": "Humidity",
	"level": "Tank level", "flow": "Flow", "tds": "TDS", "ph": "pH", "power_kw": "Power", "pf": "Power factor",
	"wind": "Wind speed", "occ": "Occupancy"}

// Finding is the DomainFinding contract shared by Mode 1 (rules) and Mode 3 (LLM agents).
type Finding struct {
	Pattern      string   `json:"pattern"`
	Status       string   `json:"status"`
	Observations []string `json:"observations"`
	LikelyCause  string   `json:"likely_cause"`
	Confidence   float64  `json:"confidence"`
	Action       string   `json:"action"`
	// v2 schema fields (training/RETRAIN_V2_SPEC.md, frozen 2026-10-16); the v1 model never emits them
	EventActive *bool  `json:"event_active,omitempty"` // still happening at the window end
	Onset       string `json:"onset,omitempty"`        // HH:MM sensor time the event started
	FaultKind   string `json:"fault_kind,omitempty"`   // only with status sensor_fault, one of FaultKinds
}

// mkFinding is a v1-shaped finding (the six fields the rules fill).
func mkFinding(pattern, status string, obs []string, cause string, conf float64, action string) Finding {
	return Finding{Pattern: pattern, Status: status, Observations: obs, LikelyCause: cause, Confidence: conf, Action: action}
}

// FaultKinds is the frozen v2 fault_kind enum.
var FaultKinds = []string{"stuck", "bias", "drift", "noise", "dropout", "saturation", "quantised"}

func occLabelFinding(pattern string, s OccStats, end int64) Finding {
	frac := fmt.Sprintf("%.2f", s.OccupiedFrac)
	t := func(i int) string { return IdxTime(end, i) }
	switch pattern {
	case "vacant":
		return mkFinding(pattern, "normal", []string{"Room unoccupied for the whole 4-hour window [E2,E1]"}, "vacant", 0.95, "none")
	case "occupied":
		return mkFinding(pattern, "normal", []string{"Room occupied for most of the window (fraction " + frac + ") [E2]"}, "normal_occupancy", 0.92, "none")
	case "arrival":
		return mkFinding(pattern, "normal", []string{"Room became occupied at " + t(s.FirstOn) + " and is still occupied [E4,E1]"}, "arrival", 0.9, "none")
	case "departure":
		return mkFinding(pattern, "normal", []string{"Room was occupied until " + t(s.LastOn) + " and is now empty [E5,E1]"}, "departure", 0.9, "none")
	case "intermittent":
		if s.Toggles >= 12 {
			return mkFinding(pattern, "sensor_fault", []string{fmt.Sprintf("State flips %d times in 4 hours, too often for real movement [E3]", s.Toggles)}, "sensor_fault", 0.75, "check_sensor")
		}
		return mkFinding(pattern, "normal", []string{fmt.Sprintf("Presence comes and goes: %d state changes, occupied fraction %s [E3,E2]", s.Toggles, frac)}, "intermittent_presence", 0.85, "monitor")
	case "off_hours_presence":
		lo := "never"
		if s.LastOn >= 0 {
			lo = t(s.LastOn)
		}
		return mkFinding(pattern, "warning", []string{"Presence detected during off-hours (occupied fraction " + frac + ") [E6,E2]", "Last occupied at " + lo + " [E5]"}, "off_hours_presence", 0.85, "request_facility_review")
	}
	return mkFinding(pattern, "normal", []string{"No rule [E1]"}, "vacant", 0.5, "none")
}

// RuleFinding = Mode 1 output for one window (deterministic, no LLM).
func RuleFinding(role, metric, node string, xs []float64, end int64) Finding {
	pattern := RulePattern(role, metric, xs, end)
	if role == "occupancy" {
		return occLabelFinding(pattern, ComputeOccStats(xs), end)
	}
	m := Metrics[role+"/"+metric]
	st := ComputeStats(xs, m.Dec)
	zero := maxf(absAll(xs)) < 1e-6 || (pattern == "flatline" && math.Abs(st.Last) < 1e-6)
	status := StatusOf(role, metric, pattern, st, mean(xs[:12]))
	cause := CauseOf(role, metric, pattern, status, IsOffHours(end), strings.HasPrefix(node, "SR-"), zero)
	obs := ruleObservations(role, metric, pattern, status, st, end, zero)
	conf := 0.7
	if pattern == "stable" {
		conf = 0.8
	}
	return mkFinding(pattern, status, obs, cause, conf, ActionOf(cause, status))
}

func absAll(xs []float64) []float64 {
	o := make([]float64, len(xs))
	for i, v := range xs {
		o[i] = math.Abs(v)
	}
	return o
}

func ruleObservations(role, metric, pattern, status string, st Stats, end int64, zero bool) []string {
	m := Metrics[role+"/"+metric]
	d := m.Dec
	u := ""
	if m.Unit != "" {
		u = " " + m.Unit
	}
	v := func(x float64) string { return Fmt(x, d) }
	sd := imax(d, 1)
	M := nice[metric]
	slope := sgn(st.SlopePerH, sd) + u + "/h"
	var obs []string
	switch pattern {
	case "stable":
		obs = append(obs, fmt.Sprintf("%s steady around %s%s, ranging only %s-%s [E6,E2,E3]", M, v(st.Mean), u, v(st.Min), v(st.Max)))
	case "spike":
		obs = append(obs, fmt.Sprintf("%s spiked to %s%s at %s and fell back to %s%s [E2,E1]", M, v(st.Max), u, IdxTime(end, st.MaxIdx), v(st.Last), u))
	case "dip":
		obs = append(obs, fmt.Sprintf("%s dropped briefly to %s%s at %s, then recovered to %s%s [E3,E1]", M, v(st.Min), u, IdxTime(end, st.MinIdx), v(st.Last), u))
	case "gradual_increase", "gradual_decrease":
		w := "upward"
		if pattern == "gradual_decrease" {
			w = "downward"
		}
		obs = append(obs, fmt.Sprintf("%s shows a steady %s trend of %s [E4]", M, w, slope))
	case "step_increase", "step_decrease":
		w := "up"
		if pattern == "step_decrease" {
			w = "down"
		}
		obs = append(obs, fmt.Sprintf("%s shifted %s abruptly by %s%s at %s and stayed there [E5,E7]", M, w, sgn(st.MaxJumpSigned, sd), u, IdxTime(end, st.MaxJumpIdx)))
	case "exponential_increase":
		obs = append(obs, fmt.Sprintf("%s is rising at an accelerating rate (curvature %s/h), now %s%s [E7,E1]", M, sgn(st.Curvature, sd), v(st.Last), u))
	case "oscillation":
		obs = append(obs, fmt.Sprintf("%s oscillates between %s and %s%s (%d crossings of its trend) [E7,E2,E3]", M, v(st.Min), v(st.Max), u, st.ZeroCross))
	case "throttling":
		obs = append(obs, fmt.Sprintf("%s climbed and then held flat at a ceiling of about %s%s for %d samples [E2,E8]", M, v(st.Max), u, st.PlateauRun))
	case "flatline":
		if zero {
			obs = append(obs, fmt.Sprintf("%s reads 0%s for %d consecutive samples, the asset is idle [E8,E1]", M, u, st.FlatRun))
		} else {
			obs = append(obs, fmt.Sprintf("%s frozen at exactly %s%s for %d consecutive samples [E8,E1]", M, v(st.Last), u, st.FlatRun))
		}
	case "erratic":
		obs = append(obs, fmt.Sprintf("%s jumps irregularly (noise %.*f, largest change %s%s) [E8,E5]", M, sd+1, st.Noise, sgn(st.MaxJumpSigned, sd), u))
	}
	if (status == "warning" || status == "critical") && m.HasLimits {
		limv := m.WarnS
		if status == "critical" {
			limv = m.CritS
		}
		if m.Dir == "low" {
			obs = append(obs, fmt.Sprintf("%s%s is below the %s limit of %s%s [E1]", v(st.Last), u, status, limv, u))
		} else {
			obs = append(obs, fmt.Sprintf("%s%s exceeds the %s limit of %s%s [E1]", v(st.Last), u, status, limv, u))
		}
	}
	if len(obs) > 3 {
		obs = obs[:3]
	}
	return obs
}
