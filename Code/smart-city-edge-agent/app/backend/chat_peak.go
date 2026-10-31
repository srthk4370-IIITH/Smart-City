package main

import (
	"regexp"
)

// Peak questions ("highest CO2 today", "biggest spike", "lowest water level this week") rank readings across every
// sensor of a metric. None of the 9 trained chat tools can rank by value (find_incidents is newest first), so the
// model answered them with the latest incident (owner report 2026-10-29). The question router (chat_router.go)
// answers them with rank_readings (chat_tools_v3.go); the words below are shared with it.

var (
	chatPeakRe = regexp.MustCompile(`(?i)\b(highest|peak|max(imum)?|spikes?|worst|biggest|largest|lowest|min(imum)?|hottest|coldest)\b`)
	chatLowRe  = regexp.MustCompile(`(?i)\b(lowest|min(imum)?|coldest)\b`)
	// question words -> metric (first match wins; longer phrases first). Whole words only: "download" is not load.
	chatPeakMetrics = []struct {
		re     *regexp.Regexp
		metric string
	}{
		{regexp.MustCompile(`(?i)\bpower\s*factor\b|\bpf\b`), "pf"},
		{regexp.MustCompile(`(?i)\broom\s*temp\w*`), "room_temp"},
		{regexp.MustCompile(`(?i)\bco2\b|\bcarbon\b`), "co2"},
		{regexp.MustCompile(`(?i)\bpm\s*2\.?5\b`), "pm25"},
		{regexp.MustCompile(`(?i)\bpm\s*10\b`), "pm10"},
		{regexp.MustCompile(`(?i)\bhumid\w*|\brh\b`), "rh"},
		{regexp.MustCompile(`(?i)\btds\b|\bdissolved\b`), "tds"},
		{regexp.MustCompile(`(?i)\bph\b`), "ph"},
		{regexp.MustCompile(`(?i)\bwater\s*level\b|\btanks?\b|\blevel\b`), "level"},
		{regexp.MustCompile(`(?i)\bflow\b`), "flow"},
		{regexp.MustCompile(`(?i)\bpower\b|\bload\b|\bkw\b|\belectric\w*`), "power_kw"},
		{regexp.MustCompile(`(?i)\boccupan\w*|\bpeople\b|\bcrowd\w*`), "occ"},
		{regexp.MustCompile(`(?i)\bwind\b`), "wind"},
		{regexp.MustCompile(`(?i)\btemp\w*|\bhottest\b|\bcoldest\b|\bheat\w*`), "temp"},
	}
	chatPeakPeriods = []struct {
		re     *regexp.Regexp
		preset string
	}{
		{regexp.MustCompile(`(?i)yesterday`), "yesterday"},
		{regexp.MustCompile(`(?i)24\s*h|24 hours|last day`), "last_24h"},
		{regexp.MustCompile(`(?i)week|7 days`), "last_7d"},
	}
)

// chatPeakMetric: the metric a question names ("" = none).
func chatPeakMetric(s string) string {
	for _, m := range chatPeakMetrics {
		if m.re.MatchString(s) {
			return m.metric
		}
	}
	return ""
}

// chatPeakQuestion: metric, period preset and direction when q is a peak question. The metric may come from the
// previous user question ("How are CO2 levels today?" -> "Highest spike today").
func chatPeakQuestion(q string, history []ChatMsg) (metric, preset string, low, ok bool) {
	if !chatPeakRe.MatchString(q) {
		return "", "", false, false
	}
	metric = chatPeakMetric(q)
	for i := len(history) - 1; metric == "" && i >= 0 && i >= len(history)-4; i-- {
		if history[i].Role == "user" {
			metric = chatPeakMetric(history[i].Text)
		}
	}
	if metric == "" {
		return "", "", false, false
	}
	preset = "today"
	for _, p := range chatPeakPeriods {
		if p.re.MatchString(q) {
			preset = p.preset
			break
		}
	}
	return metric, preset, chatLowRe.MatchString(q), true
}

func chatMetricName(m string) string {
	if n, ok := map[string]string{"co2": "CO2", "temp": "temperature", "room_temp": "room temperature", "rh": "humidity", "pm25": "PM2.5",
		"pm10": "PM10", "level": "water level", "flow": "water flow", "tds": "TDS", "ph": "pH", "power_kw": "power",
		"pf": "power factor", "occ": "occupancy", "wind": "wind", "ac_units_on": "AC units on", "ac_on": "AC on", "setpoint": "setpoint"}[m]; ok {
		return n
	}
	return m
}
