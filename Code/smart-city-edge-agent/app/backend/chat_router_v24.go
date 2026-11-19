package main

import (
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// deploy24 (held-out chat sweep 2026-11-01, proofs/2026-11-01_chat/VERDICT_heldout.md): 40 new questions, worded unlike
// the deploy23 sweep. The general failure classes it found, all answered here from the existing read-only tools:
//   - time spans no preset covers ("last 48 hours", "past 2 days") and Hindi day words (aaj, kal ... the) were mapped
//     to the wrong preset by the model (24 h / 7 d)                       -> chatTimeOf, routed counts (act "span")
//   - follow-ups on a count ("and air quality?", "which of those are still pending?") kept the wrong window
//                                                                         -> chatFollowV24 (same filters, one changed)
//   - "summary of the past 2 days" became one 7-day count                 -> act "summary"
//   - "which incident needs my attention first?" listed domains and named no incident, so "explain why" /
//     "is it a real problem?" had nothing to refer to                      -> act "top" (names exactly one incident)
//   - state questions without "now" ("wind speed on the roof?", "is the tank about to overflow") listed old incidents
//                                                                         -> current_levels (chat_router.go)
//   - "what if outdoor temperature rises to 42 C" (a target, not a change) was refused -> what_if with change_abs
//   - a sensor described in words ("KH level 2 AC unit 24") became an invented node id -> chatWithNode
//   - "show the 3 most recent" showed 5; Hindi "sensors kharab" (faulty) went to the model (chat_router.go)

var (
	chatNumWord = map[string]int{"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10, "twelve": 12, "fourteen": 14}
	chatSpanRe  = regexp.MustCompile(`(?i)\b(?:last|past|previous|prior)\s+(\d{1,3}|one|two|three|four|five|six|seven|ten|twelve|fourteen)\s*(hours?|hrs?|h|days?|weeks?)\b`)
	// Hindi: aaj = today; kal = yesterday when the verb is past (kal is also tomorrow)
	chatAajRe     = regexp.MustCompile(`(?i)\baaj\b`)
	chatKalRe     = regexp.MustCompile(`(?i)\bkal\b[^?.!]*\b(the|tha|thi|hue|hua|hui|aaye|aaya|aayi|aye|aya|gaye|gaya|gayi|raha|rahi|rahe)\b`)
	chatCountHiRe = regexp.MustCompile(`(?i)\bkitn[eai]\b`)
	// counts the span route leaves to the model (groupings, comparisons, decisions, real-vs-fault)
	chatCountNoRe  = regexp.MustCompile(`(?i)\b(which|each|per|by|most|least|top|compare\w*|vs|versus|breakdown|split|real|genuine|false\s+alarms?|pending|open|unresolved|waiting|outstanding|approved|dismissed|average|trend|like|similar)\b|\band\s+how\s+many\b`)
	chatSummaryRe  = regexp.MustCompile(`(?i)\b(summary|summari[sz]e|overview|recap|digest)\b|\bwhat\s+(has\s+|have\s+)?happened\b|\bkya\s+hua\b`)
	chatBackRe     = regexp.MustCompile(`(?i)\b(those|them|these|which\s+ones?)\b`)
	chatAndRe      = regexp.MustCompile(`(?i)^\s*(and|what\s+about|how\s+about|also|same\s+for)\b`)
	chatPendRe     = regexp.MustCompile(`(?i)\b(pending|open|waiting|undecided|unresolved|outstanding|still)\b`)
	chatTopRe      = regexp.MustCompile(`(?i)\b(most\s+urgent|urgent|priorit\w*|most\s+important|most\s+serious)\b|\bfirst\b[^?.!]*\b(attention|look|handle|deal|fix|check|start)\w*|\b(attention|look|handle|deal|fix|check|start)\w*\b[^?.!]*\bfirst\b`)
	chatTopObjRe   = regexp.MustCompile(`(?i)\b(incidents?|alerts?|alarms?|issues?|problems?|attention)\b`)
	chatStateRe    = regexp.MustCompile(`(?i)\b(ok|okay|fine|normal|safe|wrong|alright|overflow\w*|empty|status|reading|value)\b`)
	chatStateNoRe  = regexp.MustCompile(`(?i)\b(faulty|fault\w*|broken|kharaa?b|replac\w*|calibrat\w*|install\w*|limits?|threshold\w*)\b`)
	chatFaultyHiRe = regexp.MustCompile(`(?i)\bsensors?\b[^?.!]*\bkharaa?b\b|\bkharaa?b\b[^?.!]*\bsensors?\b`)
	chatToValRe    = regexp.MustCompile(`(?i)\b(?:goes|go|went|rises?|rose|drops?|dropped|falls?|fell|is|was|set|reaches?|hits?|climbs?)\s+to\s+([+-]?\d+(?:\.\d+)?)`)
	chatLevelRe    = regexp.MustCompile(`(?i)\b(?:level|floor|lvl)\s*(\d{1,2})\b`)
	chatUnitRe     = regexp.MustCompile(`(?i)\b(?:unit|sensor|meter|station|no\.?|number|#)\s*(\d{1,2})\b`)
)

// chatTimeOf: the time argument a question names (nil = none); ok false = a period neither a span nor a preset covers.
// Spans are kept relative ({"_hours": N}) and turned into from/to at the device's current time (chatPrepV24).
func chatTimeOf(q string) (map[string]any, bool) {
	if m := chatSpanRe.FindStringSubmatch(q); m != nil {
		n, err := strconv.Atoi(m[1])
		if err != nil {
			n = chatNumWord[strings.ToLower(m[1])]
		}
		h := n
		switch u := strings.ToLower(m[2]); {
		case strings.HasPrefix(u, "d"):
			h = n * 24
		case strings.HasPrefix(u, "w"):
			h = n * 24 * 7
		}
		switch h {
		case 24:
			return map[string]any{"preset": "last_24h"}, true
		case 24 * 7:
			return map[string]any{"preset": "last_7d"}, true
		case 24 * 30:
			return map[string]any{"preset": "last_30d"}, true
		}
		if h <= 0 || h > 24*400 {
			return nil, false
		}
		return map[string]any{"_hours": float64(h)}, true
	}
	preset, ok := chatPeriod(q)
	if !ok {
		return nil, false
	}
	if preset == "" {
		return nil, true
	}
	return map[string]any{"preset": preset}, true
}

func chatCopyArgs(a map[string]any) map[string]any {
	out := map[string]any{}
	for k, v := range a {
		out[k] = v
	}
	return out
}

// chatRouteV24: the deploy24 routes (tried after the deploy23 ones and the incident-id check).
func chatRouteV24(q string, history []ChatMsg, buildings []string, depth int) (chatRoute, bool) {
	tv, tok := chatTimeOf(q)
	inc := chatIncWordRe.MatchString(q)
	count := chatCountRe.MatchString(q) || chatCountHiRe.MatchString(q)
	loc := chatLocationOf(q, buildings)
	if r, ok := chatFollowV24(q, history, buildings, depth, count); ok {
		return r, true
	}
	// which incident to handle first: name exactly one, so "why?" / "is it real?" can follow
	if chatTopRe.MatchString(q) && chatTopObjRe.MatchString(q) && !count && tv == nil && tok && loc == "" && len(chatMetricMentions(q)) == 0 {
		args := map[string]any{}
		if d := chatDomainOf(q); d != "" {
			args["domain"] = d
		}
		return chatRoute{Tool: "open_incidents", Args: args, Act: "top"}, true
	}
	// summary of a period
	if chatSummaryRe.MatchString(q) && !count && tok && loc == "" && (tv != nil || !regexp.MustCompile(`(?i)\bwhat\s+(has\s+|have\s+)?happened\b`).MatchString(q)) {
		if tv == nil {
			tv = map[string]any{"preset": "today"}
		}
		args := map[string]any{"time": tv}
		if d := chatDomainOf(q); d != "" {
			args["domain"] = d
		}
		return chatRoute{Tool: "count_incidents", Args: args, Act: "summary"}, true
	}
	// a plain count over a period: domain / severity / metric filters only
	if count && inc && tv != nil && !chatCountNoRe.MatchString(q) && loc == "" && !chatWhatIfRe.MatchString(q) {
		args := map[string]any{"time": tv}
		if d := chatDomainOf(q); d != "" {
			args["domain"] = d
		} else if m := chatPeakMetric(q); m != "" {
			args["metric"] = m
		}
		if s := chatSeverities(q); len(s) > 0 {
			args["severity"] = s
		}
		return chatRoute{Tool: "count_incidents", Args: args, Act: "span"}, true
	}
	return chatRoute{}, false
}

// chatFollowV24: "and air quality?" / "which of those are still pending?" / "how many of them were critical?" after
// a span answer: the previous filters, with what this question names changed or added.
func chatFollowV24(q string, history []ChatMsg, buildings []string, depth int, count bool) (chatRoute, bool) {
	if depth >= 3 {
		return chatRoute{}, false
	}
	back := chatBackRe.MatchString(q)
	and := chatAndRe.MatchString(q) && len(strings.Fields(q)) <= 6
	if !back && !and {
		return chatRoute{}, false
	}
	i := len(history) - 1
	for i >= 0 && history[i].Role != "user" {
		i--
	}
	if i < 0 || i == len(history)-1 {
		return chatRoute{}, false
	}
	prev, ok := chatRouteV24(history[i].Text, history[:i], buildings, depth+1)
	if !ok || prev.Act != "span" {
		return chatRoute{}, false
	}
	args := chatCopyArgs(prev.Args)
	delete(args, "limit")
	changed := false
	if d := chatDomainOf(q); d != "" {
		args["domain"] = d
		delete(args, "metric")
		changed = true
	} else if m := chatPeakMetric(q); m != "" && and {
		args["metric"] = m
		delete(args, "domain")
		changed = true
	}
	if s := chatSeverities(q); len(s) > 0 {
		args["severity"] = s
		changed = true
	}
	if chatPendRe.MatchString(q) {
		args["workflow"] = wfNeeds // waiting for an operator decision, as open_incidents counts it
		changed = true
	}
	if tv, _ := chatTimeOf(q); tv != nil {
		args["time"] = tv
		changed = true
	}
	if and && !back && !changed {
		return chatRoute{}, false
	}
	tool := prev.Tool
	switch {
	case count:
		tool = "count_incidents"
	case back:
		tool = "find_incidents"
	}
	if tool == "find_incidents" {
		args["limit"] = float64(10)
	}
	return chatRoute{Tool: tool, Args: args, Act: "span"}, true
}

// chatPrepV24: turns relative spans into from/to at the device's time (rt.When describes the period) and a what-if
// target into a change from the driver's latest reading. false = the router cannot answer (the model does).
func (t chatTools) chatPrepV24(rt *chatRoute) bool {
	if tv, ok := rt.Args["time"].(map[string]any); ok {
		words := ""
		if h, ok := tv["_hours"].(float64); ok {
			now := t.now.In(IST).Truncate(time.Minute)
			tv = map[string]any{"from": now.Add(-time.Duration(h) * time.Hour).Format("2006-01-02T15:04"), "to": now.Add(time.Minute).Format("2006-01-02T15:04")}
			rt.Args["time"] = tv
			words = fmt.Sprintf("in the last %d hours", int(h))
			if int(h)%24 == 0 {
				words = fmt.Sprintf("in the last %d days", int(h)/24)
			}
		} else if p, _ := tv["preset"].(string); p != "" {
			words = chatPeriodWords[p]
			if words == "" {
				words = strings.ReplaceAll(p, "_", " ")
			}
		} else {
			words = "in that period"
		}
		if a, b, err := t.span(tv, true); err == nil {
			if b.After(t.now) {
				b = t.now
			}
			rt.When = fmt.Sprintf("%s (%s to %s)", words, chatTS(a), chatTS(b))
		} else {
			rt.When = words
		}
	}
	if rt.Tool == "what_if" {
		to, ok := rt.Args["_to"].(float64)
		if !ok {
			return true
		}
		if t.r == nil || t.r.eng == nil {
			return false
		}
		driver, _ := rt.Args["driver"].(string)
		loc, _ := rt.Args["location"].(string)
		dom, _ := rt.Args["_domain"].(string)
		_, states, _ := t.r.eng.Snapshot()
		var hit []SensorState
		for _, s := range states {
			if s.Metric == driver && !s.Injected && s.Last != nil && (dom == "" || s.Role == dom) && chatLocMatch(loc, s, t.chatBuilding(s.Node)) {
				hit = append(hit, s)
			}
		}
		if len(hit) != 1 {
			return false // no or several sensors: which one changes is unclear
		}
		d := math.Round((to-*hit[0].Last)*100) / 100
		if d == 0 {
			return false
		}
		delete(rt.Args, "_to")
		delete(rt.Args, "_domain")
		rt.Args["change_abs"], rt.Args["location"] = d, hit[0].Node
	}
	return true
}

// chatSummary: counts by severity and domain, the newest incident and what waits for a decision, for one period.
func (t chatTools) chatSummary(args map[string]any) (map[string]any, error) {
	a := chatCopyArgs(args)
	a["group_by"] = "severity"
	sev, err := t.run("count_incidents", a)
	if err != nil {
		return nil, err
	}
	a["group_by"] = "domain"
	dom, err := t.run("count_incidents", a)
	if err != nil {
		return nil, err
	}
	f := chatCopyArgs(args)
	f["limit"] = float64(1)
	newest, err := t.run("find_incidents", f)
	if err != nil {
		return nil, err
	}
	open, err := t.run("open_incidents", map[string]any{})
	if err != nil {
		return nil, err
	}
	return map[string]any{"total": sev["total"], "by_severity": sev["groups"], "by_domain": dom["groups"], "newest": newest["items"],
		"pending_overall": open["total_pending_review"], "coverage": sev["coverage"]}, nil
}

// chatIncSubject: "HVAC critical" for the filters of a span route ("" none).
func chatIncSubject(args map[string]any) string {
	var w []string
	if d, _ := args["domain"].(string); d != "" {
		w = append(w, chatDomainName(d))
	}
	if m, _ := args["metric"].(string); m != "" {
		w = append(w, chatMetricName(m))
	}
	if ss, ok := args["severity"].([]any); ok {
		var s []string
		for _, x := range ss {
			s = append(s, chatSevName(fmt.Sprint(x)))
		}
		w = append(w, strings.Join(s, " or "))
	}
	return strings.Join(w, " ")
}

// chatSayV24: the deploy24 answers ("" = not one of them).
func chatSayV24(rt chatRoute, res map[string]any, v int) string {
	switch rt.Act {
	case "top":
		top, _ := res["top_pending"].([]map[string]any)
		total, _ := res["total_pending_review"].(int)
		if len(top) == 0 {
			return "Nothing is waiting for an operator decision right now, so there is no incident to start with."
		}
		x := top[0]
		text := fmt.Sprintf("Start with [%s] %s (%s, %s): it is the most urgent of the %s waiting for your decision (worst severity first, then oldest).",
			x["id"], x["title"], chatSevName(fmt.Sprint(x["severity"])), chatDomainName(fmt.Sprint(x["domain"])), plural(total, "incident", "incidents"))
		return text + " Ask why, or what to do, for its details."
	case "span":
		subj := chatIncSubject(rt.Args)
		one, many := strings.TrimSpace(subj+" incident"), strings.TrimSpace(subj+" incidents")
		pend := ""
		if rt.Args["workflow"] == wfNeeds {
			pend = " waiting for your decision"
		}
		if rt.Tool == "count_incidents" {
			n, _ := res["count"].(int)
			return fmt.Sprintf("%s%s %s.", plural(n, one, many), pend, rt.When)
		}
		items, _ := res["items"].([]map[string]any)
		total, _ := res["total"].(int)
		if total == 0 {
			return fmt.Sprintf("No %s%s %s.", one, pend, rt.When)
		}
		var ps []string
		for _, it := range items {
			ps = append(ps, fmt.Sprintf("[%s] %s (%s, %s)", it["id"], it["title"], chatSevName(fmt.Sprint(it["severity"])), it["time"]))
		}
		text := fmt.Sprintf("%s%s %s, newest first: %s.", plural(total, one, many), pend, rt.When, strings.Join(ps, "; "))
		if total > len(items) {
			text += fmt.Sprintf(" (%d more not shown.)", total-len(items))
		}
		return text
	case "summary":
		total, _ := res["total"].(int)
		pend, _ := res["pending_overall"].(int)
		subj := chatIncSubject(rt.Args)
		pendText := fmt.Sprintf(" Overall, %s waiting for your decision.", plural(pend, "incident is", "incidents are"))
		if total == 0 {
			return fmt.Sprintf("Summary %s: no %s was raised.", rt.When, strings.TrimSpace(subj+" incident")) + pendText
		}
		grp := func(k string, name func(string) string) string {
			gs, _ := res[k].([]map[string]any)
			var ps []string
			for _, g := range gs {
				ps = append(ps, fmt.Sprintf("%s %v", name(fmt.Sprint(g["key"])), g["count"]))
			}
			return strings.Join(ps, ", ")
		}
		text := fmt.Sprintf("Summary %s: %s. By severity: %s. By domain: %s.", rt.When, plural(total, strings.TrimSpace(subj+" incident"), strings.TrimSpace(subj+" incidents")),
			grp("by_severity", chatSevName), grp("by_domain", chatDomainName))
		if it, _ := res["newest"].([]map[string]any); len(it) > 0 {
			text += fmt.Sprintf(" Newest: [%s] %s (%s, %s).", it[0]["id"], it[0]["title"], chatSevName(fmt.Sprint(it[0]["severity"])), it[0]["time"])
		}
		return text + pendText
	}
	return ""
}

// chatWithNode: a sensor described in words ("KH level 2 AC unit 24") gets its node id appended, for the router and
// the model, when exactly one sensor matches the building, level, unit number and domain named.
func chatWithNode(r *Reasoner, q string) string {
	if r == nil || r.eng == nil {
		return q
	}
	return chatWithNodeOf(q, r.eng.Meta.Nodes)
}

func chatWithNodeOf(q string, nodes map[string]NodeInfo) string {
	um := chatUnitRe.FindStringSubmatch(q)
	if um == nil || len(nodes) == 0 {
		return q
	}
	for _, m := range chatNodeRe.FindAllString(q, -1) {
		if !strings.HasPrefix(m, "INC-") {
			return q // a node id is already named
		}
	}
	unit, _ := strconv.Atoi(um[1])
	level := -1
	if lm := chatLevelRe.FindStringSubmatch(q); lm != nil {
		level, _ = strconv.Atoi(lm[1])
	}
	var buildings []string
	seen := map[string]bool{}
	for _, n := range nodes {
		if !seen[n.Building] {
			seen[n.Building] = true
			buildings = append(buildings, n.Building)
		}
	}
	b := chatLocationOf(q, buildings)
	dom := chatDomainOf(q)
	hit := ""
	for id, n := range nodes {
		if (b != "" && n.Building != b) || (dom != "" && n.Role != dom) {
			continue
		}
		if lv, err := strconv.Atoi(n.Level); level >= 0 && (err != nil || lv != level) {
			continue
		}
		suf, err := strconv.Atoi(id[strings.LastIndex(id, "-")+1:])
		if err != nil || suf != unit {
			continue
		}
		if hit != "" {
			return q // ambiguous
		}
		hit = id
	}
	if hit == "" {
		return q
	}
	// the place words go: "level 2" made the model pick the metric "level" (board r1, held-out #25)
	// deploy25: with the preposition before them ("AC unit 15 on level 3" left "AC on", read as the AC's on/off state)
	q = regexp.MustCompile(`(?i)\b(?:on|at|in|of|for|from)\s+(?:the\s+)?(?:level|floor|lvl)\s*\d{1,2}\b`).ReplaceAllString(q, "")
	q = chatUnitRe.ReplaceAllString(chatLevelRe.ReplaceAllString(q, ""), "")
	return strings.Join(strings.Fields(q), " ") + " (sensor " + hit + ")"
}
