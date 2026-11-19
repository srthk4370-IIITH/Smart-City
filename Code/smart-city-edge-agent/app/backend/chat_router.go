package main

import (
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// Question router: questions whose intent and arguments are clear from the words alone are answered here,
// deterministically, by one of the v3 chat tools (chat_tools_v3.go), with no NPU and no queue: the answer is
// built from the tool result and the call shows under "How I found this". It replaces the peak-only path
// (chat_peak.go, owner report 2026-10-29) and is conservative: anything it is not sure about goes to the model.

type chatRoute struct {
	Tool string
	Args map[string]any
	Act  string // answer variant: refuse | health | maint | about | realfault | do (deploy23); span | summary | top (deploy24)
	When string // deploy24: the period in words with its from/to (chatPrepV24)
}

var (
	chatIDRe      = regexp.MustCompile(`(?i)\bINC-?\d+`)
	chatIncWordRe = regexp.MustCompile(`(?i)\b(incidents?|alerts?|alarms?|events?|issues?|cases?)\b`)
	chatCountRe   = regexp.MustCompile(`(?i)\bhow\s+many\b|\bcount\b|\bnumber\s+of\b|\bhow\s+often\b`)
	chatNodeRe    = regexp.MustCompile(`\b[A-Z]{2}(?:-[A-Z0-9]+){1,4}\b`)

	// periods (first match wins); "week" stays last_7d as in chat_peak.go
	chatPeriods = []struct {
		re     *regexp.Regexp
		preset string
	}{
		{chatAajRe, "today"},     // deploy24: Hindi
		{chatKalRe, "yesterday"}, // deploy24: Hindi, past verb
		{regexp.MustCompile(`(?i)\byesterday\b`), "yesterday"},
		{regexp.MustCompile(`(?i)\b24\s*h(ours|rs)?\b|\blast day\b|\bpast day\b`), "last_24h"},
		{regexp.MustCompile(`(?i)\b30\s*days\b|\bpast month\b`), "last_30d"},
		{regexp.MustCompile(`(?i)\blast month\b`), "last_month"},
		{regexp.MustCompile(`(?i)\bthis month\b`), "this_month"},
		{regexp.MustCompile(`(?i)\bweek\b|\b7\s*days\b`), "last_7d"},
		{regexp.MustCompile(`(?i)\btoday\b|\bso far\b|\bthis (morning|afternoon|evening)\b`), "today"},
	}
	// period words the presets above do not cover: such a question is left to the model
	chatOtherPeriodRe = regexp.MustCompile(`(?i)\b\d+\s*(h|hrs?|hours?|days?|weeks?|months?|years?|mins?|minutes?)\b|\b(month|year|tonight|night|morning|afternoon|evening|since|between|before|after|ago|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|june|july|august|september|october|november|december)\b|\b20\d\d-\d\d`)

	chatDomainWords = []struct {
		re  *regexp.Regexp
		dom string
	}{
		{regexp.MustCompile(`(?i)\bair[\s-]?quality\b|\baqi\b`), "air_quality"},
		{regexp.MustCompile(`(?i)\bhvac\b|\bair[\s-]?con\w*|\bAC\b`), "hvac"},
		{regexp.MustCompile(`(?i)\bwater\b`), "water"},
		{regexp.MustCompile(`(?i)\bpower\b|\belectric\w*|\benergy\b`), "power"},
		{regexp.MustCompile(`(?i)\boccupancy\b`), "occupancy"},
		{regexp.MustCompile(`(?i)\bweather\b|\boutdoors?\b|\boutside\b`), "weather"},
	}

	chatCurrentRe = regexp.MustCompile(`(?i)\bkya\s+hai\b|\babhi\b|\bhow\s+(are|is)\b|\bhow's\b|\bcurrent(ly)?\b|\bright\s+now\b|\bat\s+(the\s+)?moment\b|\bnow\b|\blevels\b`)
	// a bare follow-up ("and right now?", "how are the levels?") takes the metric of the previous question
	chatFollowNowRe = regexp.MustCompile(`(?i)^\s*(and|so|ok|okay)?\s*(what|how)?\s*(about|are|is)?\s*(it|they|them|the)?\s*` +
		`(levels?|readings?|values?)?\s*((right\s+)?now|currently|at\s+the\s+moment|today)?\s*\??\s*$`)
	chatNotNowRe = regexp.MustCompile(`(?i)\b(trend|history|over time|graph|chart|plot|why|compare|compared|forecast|predict|calculated|measured|work)\b`)

	chatRecentRe   = regexp.MustCompile(`(?i)\b(recent|latest|newest|last|most recent)\b`)
	chatListRe     = regexp.MustCompile(`(?i)\b(list|show)\b(\s+me)?(\s+(all|the))?(\s+\w+)?\s+(incidents|alerts|alarms)\b`)
	chatLimitRe    = regexp.MustCompile(`(?i)\b(?:last|latest|recent|newest|top|show(?:\s+me)?|list)\s+(?:the\s+)?(\d{1,2})\b|\b(\d{1,2})\s+(?:most\s+recent|latest|newest|last|recent)\b`)
	chatSingularRe = regexp.MustCompile(`(?i)\b(the\s+)?(latest|last|newest|most recent)\s+(\w+\s+)?(incident|alert|alarm)\b`)

	chatOpenRe = regexp.MustCompile(`(?i)\b(open|pending|unresolved|outstanding|unreviewed|awaiting|waiting|unapproved|undecided)\b|` +
		`\bneed(s|ing)?\s+(my\s+|an?\s+|operator\s+|your\s+|our\s+)?(attention|decision|approval|review|action)\b|\bstill\s+need`)
	chatOpenObjRe = regexp.MustCompile(`(?i)\b(incidents?|alerts?|alarms?|issues?|review|decision|approval|attention|domains?)\b`)

	chatFaultyRe = regexp.MustCompile(`(?i)\b(faulty|broken|defective|malfunctioning|failing|dead|faulted)\s+(\w+\s+)?sensors?\b|` +
		`\bsensors?\b[^.?!]*\b(faulty|broken|defective|malfunction\w*|failing|not working|dead)\b|\bsensor\s+faults?\b`)
	chatFaultyNoRe = regexp.MustCompile(`(?i)\breplac\w*|\bconfirm\w*|\brepair\w*`)

	chatWhatIfRe = regexp.MustCompile(`(?i)\bwhat\s+(would\s+happen\s+|happens\s+|will\s+happen\s+)?if\b|\bsuppose\b|\bimagine\b|^\s*if\b|\bif\s+(the\s+)?\w+`)
	chatPctRe    = regexp.MustCompile(`(?i)([+-]?\d+(?:\.\d+)?)\s*(%|percent\b|per\s*cent\b)`)
	chatByRe     = regexp.MustCompile(`(?i)\bby\s+([+-]?\d+(?:\.\d+)?)\b`)
	chatUpRe     = regexp.MustCompile(`(?i)\b(increase[sd]?|increasing|rises?|rising|rose|go(es)?\s+up|went\s+up|grows?|grew|higher|more|raised?|boost(s|ed)?|jumps?)\b`)
	chatDownRe   = regexp.MustCompile(`(?i)\b(decrease[sd]?|decreasing|drops?|dropped|falls?|fell|go(es)?\s+down|went\s+down|reduced?|reduces|cut|lower(ed)?|less|fewer|declines?|shrinks?)\b`)
	chatMultRe   = regexp.MustCompile(`(?i)\b(doubles?|doubled|triples?|tripled|halves|halved|half)\b`)
	chatToRe     = regexp.MustCompile(`(?i)\b(goes|go|went|rises?|drops?|falls?|is|was|set)\s+to\s+\d`)
)

// chatPeriod: the preset a question names ("" none); ok false = it names a period no preset covers.
func chatPeriod(q string) (preset string, ok bool) {
	for _, p := range chatPeriods {
		if p.re.MatchString(q) {
			return p.preset, true
		}
	}
	if chatOtherPeriodRe.MatchString(q) {
		return "", false
	}
	return "", true
}

func chatDomainOf(q string) string {
	for _, d := range chatDomainWords {
		if d.re.MatchString(q) {
			return d.dom
		}
	}
	return ""
}

// chatLocationOf: a node id or a building code named in the question ("" none). Building codes count only as
// written in capitals ("KH") or followed by "building", so ordinary words are never taken for places.
func chatLocationOf(q string, buildings []string) string {
	for _, m := range chatNodeRe.FindAllString(q, -1) {
		if !strings.HasPrefix(m, "INC-") {
			return m
		}
	}
	for _, b := range buildings {
		if b == "" {
			continue
		}
		if regexp.MustCompile(`\b`+regexp.QuoteMeta(b)+`\b`).MatchString(q) ||
			regexp.MustCompile(`(?i)\b`+regexp.QuoteMeta(b)+`\s+building\b`).MatchString(q) {
			return b
		}
	}
	return ""
}

type chatMention struct {
	at     int
	metric string
}

// chatMetricMentions: every metric named in q, in order of appearance; an overlapping later pattern is skipped
// ("power factor" is pf, not power_kw too).
func chatMetricMentions(q string) []chatMention {
	var out []chatMention
	var used [][2]int
	for _, m := range chatPeakMetrics {
		for _, ix := range m.re.FindAllStringIndex(q, -1) {
			clash := false
			for _, u := range used {
				clash = clash || (ix[0] < u[1] && u[0] < ix[1])
			}
			if !clash {
				used = append(used, [2]int{ix[0], ix[1]})
				out = append(out, chatMention{ix[0], m.metric})
			}
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].at < out[j].at })
	return out
}

// chatPrevMetric: the metric of one of the last two user questions ("How are CO2 levels?" -> "and right now?").
func chatPrevMetric(history []ChatMsg) string {
	for i := len(history) - 1; i >= 0 && i >= len(history)-4; i-- {
		if history[i].Role == "user" {
			if m := chatPeakMetric(history[i].Text); m != "" {
				return m
			}
		}
	}
	return ""
}

func chatSeverities(q string) []any {
	var out []any
	if regexp.MustCompile(`(?i)\bcritical\b`).MatchString(q) {
		out = append(out, "critical")
	}
	if regexp.MustCompile(`(?i)\bwarnings?\b`).MatchString(q) {
		out = append(out, "warning")
	}
	if regexp.MustCompile(`(?i)\bsensor[\s_]+faults?\b|\bfaulty\b`).MatchString(q) {
		out = append(out, "sensor_fault")
	}
	return out
}

// chatRouteQuestion: the tool and arguments for a question the router answers itself; ok false = the model answers.
// buildings: the building codes of the device's sensors (location words).
func chatRouteQuestion(q string, history []ChatMsg, buildings []string) (chatRoute, bool) {
	preset, periodOK := chatPeriod(q)
	if r, ok := chatRouteOps(q, history, preset, periodOK); ok {
		return r, true
	}
	if chatIDRe.MatchString(q) {
		return chatRoute{}, false // several incidents named: the model
	}
	if r, ok := chatRouteV24(q, history, buildings, 0); ok {
		return r, true
	}
	loc := chatLocationOf(q, buildings)
	dom := chatDomainOf(q)
	inc := chatIncWordRe.MatchString(q)
	count := chatCountRe.MatchString(q)

	// what_if: a driver metric and a clear change (percent, "by N", doubles/halves)
	if chatWhatIfRe.MatchString(q) && !chatToRe.MatchString(q) {
		if r, ok := chatWhatIf(q, loc); ok {
			return r, true
		}
		if chatPctRe.MatchString(q) || chatMultRe.MatchString(q) {
			return chatRoute{}, false // a what-if the router could not parse: leave it to the model, not another intent
		}
	}
	// deploy24: what-if with a target value ("rises to 42 C"): change_abs from the driver's latest reading (chatPrepV24)
	if chatWhatIfRe.MatchString(q) {
		if m := chatToValRe.FindStringSubmatchIndex(q); m != nil {
			driver := ""
			for _, mm := range chatMetricMentions(q) {
				if mm.at < m[0] {
					driver = mm.metric
				}
			}
			// occupancy is a 0/1 presence fraction: "goes to 80" (people? percent?) stays with the model
			if to, err := strconv.ParseFloat(q[m[2]:m[3]], 64); err == nil && driver != "" && driver != "occ" {
				args := map[string]any{"driver": driver, "_to": to}
				if loc != "" {
					args["location"] = loc
				}
				if dom == "weather" || dom == "hvac" || dom == "air_quality" {
					args["_domain"] = dom
				}
				return chatRoute{Tool: "what_if", Args: args}, true
			}
		}
	}
	// faulty_sensors: which sensors look faulty (not counts, replacements or one named sensor)
	if (chatFaultyRe.MatchString(q) || chatFaultyHiRe.MatchString(q)) && !count && !chatFaultyNoRe.MatchString(q) && dom == "" && loc == "" && len(chatMetricMentions(q)) == 0 && periodOK {
		args := map[string]any{}
		if preset != "" {
			args["time"] = map[string]any{"preset": preset}
		}
		return chatRoute{Tool: "faulty_sensors", Args: args}, true
	}
	// open_incidents: what still waits for a decision (it has no period)
	if chatOpenRe.MatchString(q) && chatOpenObjRe.MatchString(q) && preset == "" && periodOK {
		args := map[string]any{}
		if dom != "" {
			args["domain"] = dom
		}
		return chatRoute{Tool: "open_incidents", Args: args}, true
	}
	// recent_incidents: the newest incidents of any day (a period goes to find_incidents via the model)
	if inc && !count && preset == "" && periodOK && (chatRecentRe.MatchString(q) || chatListRe.MatchString(q)) {
		args := map[string]any{}
		if m := chatLimitRe.FindStringSubmatch(q); m != nil {
			n, _ := strconv.Atoi(m[1] + m[2])
			args["limit"] = float64(n)
		} else if chatSingularRe.MatchString(q) {
			args["limit"] = float64(1)
		}
		if dom != "" {
			args["domain"] = dom
		}
		if s := chatSeverities(q); len(s) > 0 {
			args["severity"] = s
		}
		if m := chatPeakMetric(q); m != "" {
			args["metric"] = m
		}
		return chatRoute{Tool: "recent_incidents", Args: args}, true
	}
	if inc || count {
		return chatRoute{}, false
	}
	// rank_readings: highest / lowest of a metric (chat_peak.go words)
	if metric, _, low, ok := chatPeakQuestion(q, history); ok && periodOK {
		if preset == "" {
			preset = "today"
		}
		args := map[string]any{"metric": metric, "time": map[string]any{"preset": preset}}
		if low {
			args["order"] = "lowest"
		}
		if loc != "" {
			args["location"] = loc
		}
		if dom == "weather" && (metric == "temp" || metric == "rh") {
			args["domain"] = "weather" // outdoor temperature / humidity, not the indoor sensors
		}
		return chatRoute{Tool: "rank_readings", Args: args}, true
	}
	// current_levels: "how are CO2 levels", "current temperature in KH"
	// deploy24: a state question about a metric without "now" ("wind speed on the roof?", "is the tank about to overflow")
	stateLike := chatPeakMetric(q) != "" && (chatStateRe.MatchString(q) || len(strings.Fields(q)) <= 5) && !chatStateNoRe.MatchString(q)
	if (chatCurrentRe.MatchString(q) || stateLike) && !chatNotNowRe.MatchString(q) && periodOK && (preset == "" || preset == "today") {
		args := map[string]any{}
		metric := chatPeakMetric(q)
		if metric != "" {
			args["metric"] = metric
		}
		if loc != "" {
			args["location"] = loc
		}
		if dom != "" && (metric == "" || metric == "temp" || metric == "rh") {
			args["domain"] = dom
		}
		if len(args) == 0 && chatFollowNowRe.MatchString(q) {
			if m := chatPrevMetric(history); m != "" {
				args["metric"] = m
			}
		}
		if len(args) > 0 {
			return chatRoute{Tool: "current_levels", Args: args}, true
		}
	}
	return chatRoute{}, false
}

// chatWhatIf parses "what if occupancy increases by 50%": the driver is the metric named just before the change
// words (or the only metric named), the change a percent, "by N" or doubles / halves.
func chatWhatIf(q, loc string) (chatRoute, bool) {
	ms := chatMetricMentions(q)
	if len(ms) == 0 {
		return chatRoute{}, false
	}
	// where the change is stated
	cut := -1
	for _, re := range []*regexp.Regexp{chatUpRe, chatDownRe, chatMultRe, chatPctRe} {
		if ix := re.FindStringIndex(q); ix != nil && (cut < 0 || ix[0] < cut) {
			cut = ix[0]
		}
	}
	if cut < 0 {
		return chatRoute{}, false
	}
	from := 0
	if ix := regexp.MustCompile(`(?i)\bif\b|\bsuppose\b|\bimagine\b`).FindStringIndex(q); ix != nil && ix[0] < cut {
		from = ix[0]
	}
	driver := ""
	for _, m := range ms {
		if m.at >= from && m.at < cut {
			driver = m.metric
		}
	}
	if driver == "" {
		distinct := map[string]bool{}
		for _, m := range ms {
			distinct[m.metric] = true
		}
		if len(distinct) != 1 {
			return chatRoute{}, false
		}
		driver = ms[0].metric
	}
	up, down := chatUpRe.MatchString(q), chatDownRe.MatchString(q)
	args := map[string]any{"driver": driver}
	if m := chatMultRe.FindString(q); m != "" {
		switch strings.ToLower(m)[0] {
		case 'd':
			args["change_pct"] = 100.0
		case 't':
			args["change_pct"] = 200.0
		default:
			args["change_pct"] = -50.0
		}
	} else {
		var v float64
		var signed bool
		key := "change_pct"
		if m := chatPctRe.FindStringSubmatch(q); m != nil {
			v, _ = strconv.ParseFloat(m[1], 64)
			signed = strings.ContainsAny(m[1], "+-")
		} else if m := chatByRe.FindStringSubmatch(q); m != nil {
			v, _ = strconv.ParseFloat(m[1], 64)
			signed, key = strings.ContainsAny(m[1], "+-"), "change_abs"
		} else {
			return chatRoute{}, false
		}
		switch {
		case signed:
		case up && !down:
		case down && !up:
			v = -v
		default:
			return chatRoute{}, false // direction unclear
		}
		if v == 0 {
			return chatRoute{}, false
		}
		args[key] = v
	}
	if loc != "" {
		args["location"] = loc
	}
	return chatRoute{Tool: "what_if", Args: args}, true
}

// ---------------------------------------------------------------- answers

// chatRouted answers q itself when the router recognises it; ok false = the model answers (also when the tool
// failed or found nothing to rank).
func (t chatTools) chatRouted(q string, history []ChatMsg) (text string, tool ChatTool, ok bool) {
	if t.r == nil {
		return "", ChatTool{}, false
	}
	var buildings []string
	if t.r.eng != nil {
		seen := map[string]bool{}
		for _, n := range t.r.eng.Meta.Nodes {
			if !seen[n.Building] {
				seen[n.Building] = true
				buildings = append(buildings, n.Building)
			}
		}
		sort.Strings(buildings)
	}
	rt, ok := chatRouteQuestion(q, history, buildings)
	if !ok {
		return "", ChatTool{}, false
	}
	if !t.chatPrepV24(&rt) {
		return "", ChatTool{}, false
	}
	var res map[string]any
	var err error
	if rt.Act == "summary" {
		res, err = t.chatSummary(rt.Args)
	} else {
		res, err = t.run(rt.Tool, rt.Args)
	}
	if err != nil && rt.Tool != "rank_readings" {
		return "", ChatTool{}, false
	}
	if res == nil {
		res = map[string]any{"error": err.Error()}
	} else {
		t.chatAugment(rt, res)
	}
	text = chatSay(rt, res, len(q)%2)
	if text == "" && rt.Tool == "rank_readings" {
		text = t.chatSaySilentRank(rt) // no reading in the period: say so instead of handing the model an empty ranking
	}
	if text == "" {
		return "", ChatTool{}, false
	}
	a, _ := json.Marshal(rt.Args)
	r, _ := json.Marshal(res)
	return text, ChatTool{Name: rt.Tool, Args: string(a), Result: string(r)}, true
}

func chatDomainName(d string) string {
	if n, ok := map[string]string{"air_quality": "air quality", "hvac": "HVAC"}[d]; ok {
		return n
	}
	return d
}

func chatSevName(s string) string {
	if n, ok := map[string]string{"sensor_fault": "sensor fault", "normal": "fine"}[s]; ok {
		return n
	}
	return s
}

// chatNum prints a rounded value with its unit ("0/1" occupancy is a fraction, printed bare).
func chatNum(v any, unit string) string {
	f, _ := v.(float64)
	s := strconv.FormatFloat(f, 'f', -1, 64)
	if unit == "" || unit == "0/1" {
		return s
	}
	return s + " " + unit
}

var chatPeriodWords = map[string]string{"today": "today", "yesterday": "yesterday", "last_24h": "in the last 24 hours", "last_7d": "in the last 7 days",
	"this_week": "this week", "this_month": "this month", "last_30d": "in the last 30 days", "last_month": "last month"}

func chatPresetOf(args map[string]any, def string) string {
	if tv, ok := args["time"].(map[string]any); ok {
		if p, _ := tv["preset"].(string); p != "" {
			return p
		}
	}
	return def
}

func plural(n int, one, many string) string {
	if n == 1 {
		return "1 " + one
	}
	return fmt.Sprintf("%d %s", n, many)
}

// chatSay builds the routed answer from the tool result; v picks between two wordings. "" = nothing to say.
func chatSay(rt chatRoute, res map[string]any, v int) string {
	if s := chatSayV24(rt, res, v); s != "" {
		return s
	}
	if s := chatSayOps(rt, res, v); s != "" {
		return s
	}
	if _, bad := res["error"]; bad {
		return ""
	}
	switch rt.Tool {
	case "rank_readings":
		items, _ := res["items"].([]map[string]any)
		if len(items) == 0 {
			return ""
		}
		metric, _ := res["metric"].(string)
		f := func(it map[string]any) string {
			at, _ := it["at"].(string)
			if len(at) == 16 {
				at = at[11:]
			}
			s := fmt.Sprintf("%s at %s (%s), %s", chatNum(it["value"], it["unit"].(string)), it["location"], it["node"], at)
			if it["faulty_suspect"] == true {
				s += " - this sensor is flagged as faulty, so the value may not be real"
			}
			return s
		}
		word := map[bool]string{true: "Lowest", false: "Highest"}[res["order"] == "lowest"]
		text := fmt.Sprintf("%s %s %s: %s.", word, chatMetricName(metric), chatPeriodWords[chatPresetOf(rt.Args, "today")], f(items[0]))
		if len(items) > 1 {
			var next []string
			for _, it := range items[1:] {
				next = append(next, f(it))
			}
			text += map[int]string{0: " Next: ", 1: " Then: "}[v] + strings.Join(next, "; ") + "."
		}
		n, _ := res["sensors"].(int)
		return text + fmt.Sprintf(" (%s checked, device readings every 5 min.)", plural(n, chatMetricName(metric)+" sensor", chatMetricName(metric)+" sensors"))
	case "current_levels":
		items, _ := res["items"].([]map[string]any)
		if len(items) == 0 {
			return ""
		}
		var parts []string
		for _, it := range items[:min(4, len(items))] {
			metric, unit := it["metric"].(string), it["unit"].(string)
			name := chatMetricName(metric)
			if metric != "ph" {
				name = strings.ToUpper(name[:1]) + name[1:]
			}
			s := name + " at " + it["location"].(string) + ": "
			if why, silent := it["_silent"]; silent {
				if it["last"] == nil {
					s += "no reading yet (sensor silent)"
				} else {
					s += "no new reading (sensor silent"
					if w, _ := why.(string); w != "" {
						s += ": " + w
					}
					s += "); last value " + chatNum(it["last"], unit)
				}
			} else if it["last"] == nil {
				s += "no reading yet"
			} else {
				s += chatNum(it["last"], unit) + " (" + chatSevName(it["status"].(string)) + ")"
			}
			if td, ok := it["today"].(map[string]any); ok {
				s += fmt.Sprintf(", today %s to %s, mean %s", chatNum(td["min"], ""), chatNum(td["max"], unit), chatNum(td["mean"], ""))
			}
			if lm, ok := it["limit"].(map[string]any); ok {
				dir := "above"
				if metric == "pf" {
					dir = "below"
				}
				s += fmt.Sprintf("; alert limits: warning %s %s, critical %s %s", dir, chatNum(lm["warning"], ""), dir, chatNum(lm["critical"], ""))
				if metric == "ph" {
					s += " (or below 6.5 / 6.0)"
				}
			}
			parts = append(parts, s)
		}
		head := map[int]string{0: "Current readings: ", 1: "Right now: "}[v]
		text := head + strings.Join(parts, ". ") + "."
		if n, _ := res["count"].(int); n > len(parts) {
			text += fmt.Sprintf(" (%d more sensors match; ask for a building or metric to narrow it down.)", n-len(parts))
		}
		return text
	case "recent_incidents":
		items, _ := res["items"].([]map[string]any)
		total, _ := res["total"].(int)
		if len(items) == 0 {
			return "There are no matching incidents on this device yet (demo injections are not counted)."
		}
		var parts []string
		for _, it := range items {
			parts = append(parts, fmt.Sprintf("%s %s (%s, %s)", it["id"], it["title"], chatSevName(it["severity"].(string)), it["time"]))
		}
		var head string
		if len(items) == 1 {
			head = map[int]string{0: "The most recent incident is ", 1: "The latest incident is "}[v]
		} else {
			head = fmt.Sprintf(map[int]string{0: "The %d most recent incidents, newest first: ", 1: "Latest %d incidents, newest first: "}[v], len(items))
		}
		return head + strings.Join(parts, "; ") + fmt.Sprintf(". (%s on this device match in total.)", plural(total, "incident", "incidents"))
	case "open_incidents":
		doms, _ := res["domains"].([]map[string]any)
		total, _ := res["total_pending_review"].(int)
		var parts []string
		analysing := 0
		for _, d := range doms {
			n, _ := d["pending_review"].(int)
			a, _ := d["analysing"].(int)
			analysing += a
			if n == 0 {
				continue
			}
			bs, _ := d["by_severity"].(map[string]int)
			var sev []string
			for _, s := range []string{"critical", "warning", "sensor_fault", "normal"} {
				if bs[s] > 0 {
					sev = append(sev, fmt.Sprintf("%d %s", bs[s], chatSevName(s)))
				}
			}
			parts = append(parts, fmt.Sprintf("%s %d (%s; oldest from %v)", chatDomainName(d["domain"].(string)), n, strings.Join(sev, ", "), d["oldest_pending"]))
		}
		var text string
		if total == 0 {
			text = map[int]string{0: "Nothing is waiting for an operator decision right now.", 1: "No incident is waiting for a decision at the moment."}[v]
		} else if v == 0 {
			text = fmt.Sprintf("%s waiting for an operator decision. By domain: %s.", plural(total, "incident is", "incidents are"), strings.Join(parts, "; "))
		} else {
			text = fmt.Sprintf("%s still %s a decision. Per domain: %s.", plural(total, "incident", "incidents"),
				map[bool]string{true: "needs", false: "need"}[total == 1], strings.Join(parts, "; "))
		}
		if analysing > 0 {
			text += " The AI is still analysing " + map[bool]string{true: "one more.", false: "more."}[analysing == 1]
		}
		return text
	case "faulty_sensors":
		live, _ := res["live"].([]map[string]any)
		ai, _ := res["ai_diagnosed"].([]map[string]any)
		when := chatPeriodWords[chatPresetOf(rt.Args, "last_7d")]
		var text string
		if len(live) == 0 {
			text = "No sensor reports a sensor fault right now."
		} else {
			var ps []string
			for _, s := range live {
				ps = append(ps, fmt.Sprintf("%s %s (%s, since %s)", s["node"], chatMetricName(s["metric"].(string)), s["location"], s["since"]))
			}
			text = fmt.Sprintf("Right now %s a sensor fault: %s.", plural(len(live), "sensor reports", "sensors report"), strings.Join(ps, "; "))
		}
		if len(ai) == 0 {
			text += fmt.Sprintf(" The AI diagnosed no sensor as faulty %s.", when)
		} else {
			var ps []string
			for _, s := range ai {
				p := fmt.Sprintf("%s %s (%s, last %s", s["node"], chatMetricName(s["metric"].(string)), plural(s["incidents"].(int), "incident", "incidents"), s["last"])
				if fk, ok := s["fault_kind"].(string); ok {
					p += ", looks like " + fk
				}
				ps = append(ps, p+")")
			}
			text += fmt.Sprintf(map[int]string{0: " %s the AI diagnosed these as faulty: %s.", 1: " Sensors the AI diagnosed as faulty %s: %s."}[v],
				map[int]string{0: strings.ToUpper(when[:1]) + when[1:], 1: when}[v], strings.Join(ps, "; "))
		}
		n, _ := res["count_distinct"].(int)
		text += fmt.Sprintf(" (%s in all.)", plural(n, "distinct sensor", "distinct sensors"))
		if pf, _ := res["_pending_fault"].([]string); len(pf) > 0 {
			text += " Sensor-fault incidents still waiting for your decision: " + strings.Join(pf, "; ") + "."
		}
		if ss, _ := res["_silent"].([]string); rt.Act == "maint" && len(ss) > 0 {
			text += fmt.Sprintf(" %s no new readings (silent): %s.", plural(len(ss), "sensor sends", "sensors send"), chatSilentList(ss, 4))
		}
		return text
	case "what_if":
		return chatSayWhatIf(rt, res, v)
	}
	return ""
}

func chatSayWhatIf(rt chatRoute, res map[string]any, v int) string {
	driver, _ := res["driver"].(string)
	unit, _ := res["unit"].(string)
	when := chatPeriodWords[chatPresetOf(rt.Args, "last_7d")]
	text := fmt.Sprintf(map[int]string{0: "This is an estimate from the device's readings %s - an association in recent data, not a guarantee. ",
		1: "An estimate fitted from recent device data (%s): it shows an association, not a guarantee. "}[v], when)
	if n, _ := res["driver_now"].(float64); n == 0 {
		// no non-zero hour in the window: a percent change of zero is zero, there is nothing to fit
		return fmt.Sprintf("The %s sensor at %s reported 0 in every hour %s, so the device's data cannot estimate what a change of %s would do. "+
			"Ask again once it has recorded the building in use.", chatMetricName(driver), res["location"], when, res["change"])
	}
	if b, _ := res["driver_basis"].(string); strings.HasPrefix(b, "typical") {
		text += fmt.Sprintf("%s at %s is about zero right now, so the change is applied to its typical in-use level. ", chatMetricName(driver), res["location"])
	}
	text += fmt.Sprintf("If %s at %s changes %s (%s to %s)", chatMetricName(driver), res["location"], res["change"], chatNum(res["driver_now"], unit), chatNum(res["driver_after"], unit))
	ests, _ := res["estimates"].([]map[string]any)
	if len(ests) == 0 {
		text += ", the recent data shows no clear link to the other readings there"
	} else {
		var ps []string
		for _, e := range ests {
			u, _ := e["unit"].(string)
			ps = append(ps, fmt.Sprintf("%s (%s) %s -> %s", chatMetricName(e["metric"].(string)), e["node"], chatNum(e["now"], u), chatNum(e["after"], u)))
		}
		text += ": " + strings.Join(ps, "; ")
	}
	text += "."
	if nl, _ := res["no_clear_link"].([]string); len(nl) > 0 {
		var names []string
		for _, m := range nl {
			names = append(names, chatMetricName(m))
		}
		text += " No clear link found for: " + strings.Join(names, ", ") + "."
	}
	return text
}

// chatNowOf: the device's current (sensor) time for the router and the tools.
func chatNowOf(r *Reasoner) time.Time {
	now := time.Now()
	if r != nil && r.eng != nil {
		if sim, _, _ := r.eng.Snapshot(); sim > 0 {
			now = time.Unix(sim, 0)
		}
	}
	return now
}
