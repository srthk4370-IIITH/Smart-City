package main

import "regexp"

// pH direction repair (2026-11-03). A high-pH incident (board INC-0660, pH 9.63) was reported as "The stored water is
// turning acidic (pH below 6.5)": the seed library (rag_seed.json) has only low-pH water cases, so the preliminary
// report's retrieved wording said "acidic", and the reasoner, trained on the same wording, wrote it too. pH has limits
// on both sides (rules.go StatusOf: above 8.5 / 9.0, below 6.5 / 6.0), so the direction is read from the incident's own
// pH window and the wording of every pH sentence is set to it: high pH = alkaline (above 8.5), low pH = acidic (below 6.5).

// phDirection: +1 when the incident's flagged pH readings are above the drinking-water range (> 8.5) and none below it,
// -1 when below (< 6.5) and none above, 0 otherwise (no pH sensor, in range, or both sides).
func phDirection(sensors []SensorRef) int {
	hi, lo := false, false
	for _, s := range sensors {
		if s.Metric != "ph" || s.Context {
			continue
		}
		for _, x := range s.Xs {
			hi = hi || x > 8.5
			lo = lo || x < 6.5
		}
	}
	switch {
	case hi && !lo:
		return 1
	case lo && !hi:
		return -1
	}
	return 0
}

var (
	// a sentence ends at . ; ! ? followed by a space or the end ("6.5" and "S1.E4" are not ends)
	phSentRe    = regexp.MustCompile(`(?s).+?(?:[.;!?](?:\s+|$)|$)`)
	phMentionRe = regexp.MustCompile(`(?i)\bph\b|acid|alkal`)
	phToHigh    = []struct {
		re  *regexp.Regexp
		rep string
	}{
		{regexp.MustCompile(`\bacidic\b`), "alkaline"},
		{regexp.MustCompile(`\bAcidic\b`), "Alkaline"},
		{regexp.MustCompile(`\bacidity\b`), "alkalinity"},
		{regexp.MustCompile(`(?i)\bbelow\s+6\.5\b`), "above 8.5"},
		{regexp.MustCompile(`(?i)\bbelow\s+6(\.0)?\b`), "above 9.0"},
		{regexp.MustCompile(`(?i)\b(falling|dropping|going|fell|dropped)\s+below\b`), "rising above"},
		{regexp.MustCompile(`(?i)\bbelow\s+the\s+(critical|warning|drinking-water|safe)\s+(limit|range)\b`), "above the $1 $2"},
		{regexp.MustCompile(`\blow pH\b`), "high pH"},
	}
	phToLow = []struct {
		re  *regexp.Regexp
		rep string
	}{
		{regexp.MustCompile(`\balkaline\b`), "acidic"},
		{regexp.MustCompile(`\bAlkaline\b`), "Acidic"},
		{regexp.MustCompile(`\balkalinity\b`), "acidity"},
		{regexp.MustCompile(`(?i)\babove\s+8\.5\b`), "below 6.5"},
		{regexp.MustCompile(`(?i)\babove\s+9(\.0)?\b`), "below 6.0"},
		{regexp.MustCompile(`(?i)\b(rising|climbing|going|rose|climbed)\s+above\b`), "falling below"},
		{regexp.MustCompile(`(?i)\babove\s+the\s+(critical|warning|drinking-water|safe)\s+(limit|range)\b`), "below the $1 $2"},
		{regexp.MustCompile(`\bhigh pH\b`), "low pH"},
	}
)

// phFixText: s with every pH sentence worded for direction dir (phDirection); s unchanged when dir is 0.
func phFixText(s string, dir int) string {
	if dir == 0 || s == "" || !phMentionRe.MatchString(s) {
		return s
	}
	rules := phToHigh
	if dir < 0 {
		rules = phToLow
	}
	return phSentRe.ReplaceAllStringFunc(s, func(sent string) string {
		if !phMentionRe.MatchString(sent) {
			return sent
		}
		for _, r := range rules {
			sent = r.re.ReplaceAllString(sent, r.rep)
		}
		return sent
	})
}

// phFixReport rewrites the report's free text for the incident's pH direction; true when anything changed.
func phFixReport(rep *Report, sensors []SensorRef) bool {
	dir := phDirection(sensors)
	if rep == nil || dir == 0 {
		return false
	}
	changed := false
	fix := func(p *string) {
		if n := phFixText(*p, dir); n != *p {
			*p, changed = n, true
		}
	}
	fix(&rep.Title)
	fix(&rep.RootCause)
	fix(&rep.CausalChain)
	fix(&rep.Explanation)
	fix(&rep.MonitorNext)
	for i := range rep.Observations {
		fix(&rep.Observations[i].Text)
	}
	for i := range rep.Checklist {
		fix(&rep.Checklist[i].Why)
	}
	return changed
}

// phDirWord: "alkaline (pH above 8.5)" / "acidic (pH below 6.5)" for logs and repairs.
func phDirWord(dir int) string {
	return map[int]string{1: "alkaline (pH above 8.5)", -1: "acidic (pH below 6.5)"}[dir]
}

