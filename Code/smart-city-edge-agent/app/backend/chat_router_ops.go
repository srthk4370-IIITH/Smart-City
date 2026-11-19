package main

import (
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// deploy23 (board chat sweep 2026-11-01, proofs/2026-11-01_chat): routes and answers for the failure classes the
// 40-question sweep found. All are deterministic answers from the existing read-only tools (no new tool, no model change):
//   - action requests ("close all open incidents") were answered with a list instead of a refusal  -> act "refuse"
//   - questions about one incident (INC-0605, or "why did it happen?" after an answer naming one) went to the model,
//     11-14 s, once printed a tool call as text instead of running it                                 -> get_incident
//   - "which sensors need maintenance" was read as "replaced in 30 days" (none) while 11 sensor-fault incidents
//     waited for a decision; faulty_sensors left those out                                             -> act "maint"
//   - "what did operators approve" gave a bare count                                                  -> find_incidents
//   - "overall health" mixed open/needs-decision counts with raw domain ids                            -> act "health"
//   - silent sensors (no new reading, quality stale) were reported as "right now: 596.3 kW (fine)"     -> chatAugment

var (
	chatActVerbs = `close|approve|dismiss|delete|remove|acknowledge|ack|resolve|clear|reset|switch|turn|shut|restart|reboot|disable|mute|silence|replace|escalate|assign`
	chatActRe    = regexp.MustCompile(`(?i)^\s*(please\s+|pls\s+|kindly\s+)?(` + chatActVerbs + `)\b|\b(can|could|will|would)\s+you\s+(please\s+)?(` + chatActVerbs + `)\b`)
	// a question about one incident (its id named)
	chatIncAboutRe = regexp.MustCompile(`(?i)\b(why|what|how|tell|explain|details?|describe|summar\w*|real|fault\w*|cause\w*|status|should|happen\w*|flag\w*|about|severity|recommend\w*|next|do|is|was)\b`)
	// a follow-up about the incident the previous answer named
	chatFollowIncRe = regexp.MustCompile(`(?i)\b(it|this|that|this one|that one|this incident|that incident|the incident|isko|iska|ye|yeh)\b`)
	chatFollowAskRe = regexp.MustCompile(`(?i)\b(why|kyun|kyon|cause\w*|what\s+should|what\s+(do|can)\s+(i|we)|recommend\w*|next\s+steps?|tell\s+me\s+more|more\s+details?|details|explain|real|sensor\s+fault|how\s+serious|severity|happen\w*)\b`)
	chatRealFaultRe = regexp.MustCompile(`(?i)\breal\b|\bgenuine\b|\bfalse\s+alarm\b|\bsensor\s+(fault|problem|issue|error)\b|\bfaulty\b`)
	chatDoRe        = regexp.MustCompile(`(?i)\bwhat\s+should\b|\bwhat\s+(do|can)\s+(i|we)\b|\brecommend\w*|\bnext\s+steps?\b|\bhow\s+(do|can|should)\s+(i|we)\s+(fix|handle|resolve)|\bshould\s+i\b`)
	chatMaintRe     = regexp.MustCompile(`(?i)\bsensors?\b[^.?!]*\b(maintenance|repair\w*|servic\w*|attention|fix\w*)\b|\b(maintenance|repair|servicing)\b[^.?!]*\bsensors?\b`)
	chatApprRe      = regexp.MustCompile(`(?i)\b(approved|dismissed)\b|\bdid\b[^?.!]*\b(approve|dismiss)\b`)
	chatApprAskRe   = regexp.MustCompile(`(?i)\b(what|which|list|show|did|were|was|incidents?|alerts?)\b`)
	chatHealthRe    = regexp.MustCompile(`(?i)\b(overall|campus|everything|system|all\s+domains)\b[^.?!]*\b(health|status|ok|okay|fine|doing|look\w*|going)\b|\bhow\s+is\s+(the\s+)?(campus|system|everything)\b|\bhealth\s+of\s+(the\s+)?(campus|system)\b`)
)

// chatLastIncID: the one incident id the last assistant answer named ("" none or several).
func chatLastIncID(history []ChatMsg) string {
	for i := len(history) - 1; i >= 0; i-- {
		if history[i].Role != "assistant" || history[i].Busy {
			continue
		}
		ids := chatIDs(history[i].Text)
		if len(ids) == 1 {
			return ids[0]
		}
		return ""
	}
	return ""
}

// chatIDs: the distinct incident ids in s, as INC-0123.
func chatIDs(s string) []string {
	var out []string
	seen := map[string]bool{}
	for _, m := range chatIDRe.FindAllString(s, -1) {
		id := strings.ToUpper(m)
		if !strings.HasPrefix(id, "INC-") {
			id = "INC-" + id[3:]
		}
		if !seen[id] {
			seen[id] = true
			out = append(out, id)
		}
	}
	return out
}

// chatRouteOps: the deploy23 routes, tried before the others; ok false = not one of them.
func chatRouteOps(q string, history []ChatMsg, preset string, periodOK bool) (chatRoute, bool) {
	if chatActRe.MatchString(q) {
		return chatRoute{Tool: "open_incidents", Args: map[string]any{}, Act: "refuse"}, true
	}
	incAct := func() string {
		switch {
		case chatRealFaultRe.MatchString(q):
			return "realfault"
		case chatDoRe.MatchString(q):
			return "do"
		}
		return "about"
	}
	ids := chatIDs(q)
	if len(ids) == 1 && chatIncAboutRe.MatchString(q) && !chatCountRe.MatchString(q) {
		return chatRoute{Tool: "get_incident", Args: map[string]any{"id": ids[0]}, Act: incAct()}, true
	}
	if len(ids) > 0 {
		return chatRoute{}, false
	}
	// deploy24: a short follow-up without a pronoun ("explain why") counts too
	if (chatFollowIncRe.MatchString(q) || len(strings.Fields(q)) <= 3) && chatFollowAskRe.MatchString(q) && !chatCountRe.MatchString(q) {
		if id := chatLastIncID(history); id != "" {
			return chatRoute{Tool: "get_incident", Args: map[string]any{"id": id}, Act: incAct()}, true
		}
	}
	count := chatCountRe.MatchString(q)
	if chatMaintRe.MatchString(q) && !count && !regexp.MustCompile(`(?i)\breplac\w*`).MatchString(q) && periodOK {
		args := map[string]any{}
		if preset != "" {
			args["time"] = map[string]any{"preset": preset}
		}
		return chatRoute{Tool: "faulty_sensors", Args: args, Act: "maint"}, true
	}
	if chatApprRe.MatchString(q) && chatApprAskRe.MatchString(q) && periodOK {
		ap := "approved"
		if regexp.MustCompile(`(?i)\bdismiss`).MatchString(q) {
			ap = "dismissed"
		}
		if preset == "" {
			preset = "last_7d"
		}
		args := map[string]any{"approval": ap, "time": map[string]any{"preset": preset}}
		if d := chatDomainOf(q); d != "" {
			args["domain"] = d
		}
		// "how many were dismissed, and how many approved?": both decisions, one count each
		if regexp.MustCompile(`(?i)\bapprov`).MatchString(q) && regexp.MustCompile(`(?i)\bdismiss`).MatchString(q) {
			delete(args, "approval")
			args["group_by"] = "approval"
			return chatRoute{Tool: "count_incidents", Args: args, Act: "approvals"}, true
		}
		if count {
			return chatRoute{Tool: "count_incidents", Args: args}, true
		}
		args["limit"] = float64(10)
		return chatRoute{Tool: "find_incidents", Args: args}, true
	}
	if chatHealthRe.MatchString(q) && !count && preset == "" {
		return chatRoute{Tool: "open_incidents", Args: map[string]any{}, Act: "health"}, true
	}
	return chatRoute{}, false
}

// ---------------------------------------------------------------- facts the tool results do not carry

// chatSilent: live sensors with no new reading (data quality stale), as "node metric" -> reason.
func (t chatTools) chatSilent() map[string]string {
	out := map[string]string{}
	if t.r == nil || t.r.eng == nil {
		return out
	}
	_, states, _ := t.r.eng.Snapshot()
	for _, s := range states {
		if !s.Injected && s.Quality == "stale" {
			out[s.Node+" "+s.Metric] = s.QualityWhy
		}
	}
	return out
}

// chatAugment adds what the routed answer needs beyond the tool result (keys starting with "_"; shown under
// "How I found this" only).
func (t chatTools) chatAugment(rt chatRoute, res map[string]any) {
	switch rt.Tool {
	case "current_levels":
		sil := t.chatSilent()
		items, _ := res["items"].([]map[string]any)
		for _, it := range items {
			if why, ok := sil[fmt.Sprint(it["node"])+" "+fmt.Sprint(it["metric"])]; ok {
				it["_silent"] = why
			}
		}
	case "faulty_sensors", "open_incidents":
		type agg struct {
			key    string
			n      int
			newest string
			seq    int
		}
		pend := map[string]*agg{}
		live := 0
		for _, ci := range t.incidents() {
			if ci.inc.Injected || wfOf(ci.inc) != wfNeeds || normSeverity(ci.inc.Severity) != "sensor_fault" {
				continue
			}
			for _, s := range ci.sensors {
				k := s.Node + " " + chatMetricName(s.Metric)
				g := pend[k]
				if g == nil {
					g = &agg{key: k}
					pend[k] = g
				}
				g.n++
				if q := chatIncSeq(ci.inc.ID); q > g.seq {
					g.seq, g.newest = q, ci.inc.ID
				}
			}
		}
		var ps []*agg
		for _, g := range pend {
			ps = append(ps, g)
		}
		sort.Slice(ps, func(i, j int) bool {
			if ps[i].n != ps[j].n {
				return ps[i].n > ps[j].n
			}
			return ps[i].key < ps[j].key
		})
		var lines []string
		for _, g := range ps {
			lines = append(lines, fmt.Sprintf("%s (%s, newest [%s])", g.key, plural(g.n, "incident", "incidents"), g.newest))
		}
		res["_pending_fault"] = lines
		sil := t.chatSilent()
		var ss []string
		for k := range sil {
			ss = append(ss, k)
		}
		sort.Strings(ss)
		res["_silent"] = ss
		if lv, ok := res["live"].([]map[string]any); ok {
			live = len(lv)
		} else if rt.Act == "health" {
			live = len(t.chatFaultsNow(t.incidents()))
		}
		res["_live_faults"] = live
	case "get_incident":
		id, _ := rt.Args["id"].(string)
		t.r.mu.RLock()
		defer t.r.mu.RUnlock()
		for _, p := range t.r.incidents {
			if p.ID != id {
				continue
			}
			var open []string
			for _, st := range p.Steps {
				if st.State == "open" && strings.TrimSpace(st.Text) != "" {
					open = append(open, strings.TrimRight(strings.TrimSpace(st.Text), "."))
				}
			}
			res["_open_steps"] = open
		}
	}
}

// chatSilentList: "a, b, c and 24 more".
func chatSilentList(ss []string, n int) string {
	if len(ss) <= n {
		return strings.Join(ss, ", ")
	}
	return strings.Join(ss[:n], ", ") + fmt.Sprintf(" and %d more", len(ss)-n)
}

// chatSayOps: the deploy23 answers ("" = not one of them).
func chatSayOps(rt chatRoute, res map[string]any, v int) string {
	switch {
	case rt.Act == "approvals":
		if _, bad := res["error"]; bad {
			return ""
		}
		n := map[string]int{}
		gs, _ := res["groups"].([]map[string]any)
		for _, g := range gs {
			k, _ := g["key"].(string)
			c, _ := g["count"].(int)
			n[k] = c
		}
		total, _ := res["total"].(int)
		when := chatPeriodWords[chatPresetOf(rt.Args, "last_7d")]
		if when == "" {
			when = "in that period"
		}
		text := fmt.Sprintf("%s: %s dismissed and %d approved by an operator.", strings.ToUpper(when[:1])+when[1:],
			plural(n["dismissed"], "incident was", "incidents were"), n["approved"])
		if rest := total - n["dismissed"] - n["approved"]; rest > 0 {
			text += fmt.Sprintf(" The other %d of the %d incidents have no decision yet.", rest, total)
		}
		return text
	case rt.Act == "refuse":
		text := "I can't do that: my tools only read the device's data, and changing an incident or a device needs an operator."
		if total, _ := res["total_pending_review"].(int); total > 0 {
			text += fmt.Sprintf(" %s waiting for a decision; open each one under Incidents and approve or dismiss it there.", plural(total, "incident is", "incidents are"))
		} else {
			text += " No incident is waiting for a decision right now."
		}
		return text
	case rt.Act == "health":
		doms, _ := res["domains"].([]map[string]any)
		total, _ := res["total_pending_review"].(int)
		var parts []string
		for _, d := range doms {
			if n, _ := d["pending_review"].(int); n > 0 {
				parts = append(parts, fmt.Sprintf("%s %d", chatDomainName(d["domain"].(string)), n))
			}
		}
		var text string
		if total == 0 {
			text = "No incident is waiting for an operator decision."
		} else {
			text = fmt.Sprintf("%s waiting for an operator decision (%s).", plural(total, "incident is", "incidents are"), strings.Join(parts, ", "))
		}
		if top, _ := res["top_pending"].([]map[string]any); len(top) > 0 {
			text += fmt.Sprintf(" Most urgent: [%s] %s (%s).", top[0]["id"], top[0]["title"], chatSevName(top[0]["severity"].(string)))
		}
		if n, _ := res["_live_faults"].(int); n > 0 {
			text += fmt.Sprintf(" %s a live sensor fault.", plural(n, "sensor reports", "sensors report"))
		} else {
			text += " No sensor reports a live fault."
		}
		if ss, _ := res["_silent"].([]string); len(ss) > 0 {
			text += fmt.Sprintf(" %s no new readings (silent), so their current state is unknown.", plural(len(ss), "sensor sends", "sensors send"))
		}
		return text
	}
	switch rt.Tool {
	case "get_incident":
		return chatSayIncident(rt, res)
	case "find_incidents":
		items, _ := res["items"].([]map[string]any)
		total, _ := res["total"].(int)
		ap, _ := rt.Args["approval"].(string)
		when := chatPeriodWords[chatPresetOf(rt.Args, "last_7d")]
		if total == 0 {
			return fmt.Sprintf("No incident was %s by an operator %s.", ap, when)
		}
		var ps []string
		for _, it := range items {
			ps = append(ps, fmt.Sprintf("[%s] %s (%s, %s)", it["id"], it["title"], chatSevName(it["severity"].(string)), it["time"]))
		}
		text := fmt.Sprintf("%s %s %s: %s.", plural(total, "incident was", "incidents were"), ap, when, strings.Join(ps, "; "))
		if total > len(items) {
			text += fmt.Sprintf(" (%d more not shown.)", total-len(items))
		}
		return text
	case "count_incidents":
		n, _ := res["count"].(int)
		ap, _ := rt.Args["approval"].(string)
		return fmt.Sprintf("%s %s by an operator %s.", plural(n, "incident was", "incidents were"), ap, chatPeriodWords[chatPresetOf(rt.Args, "last_7d")])
	}
	return ""
}

func chatSayIncident(rt chatRoute, res map[string]any) string {
	id, _ := rt.Args["id"].(string)
	if e, ok := res["error"]; ok {
		return fmt.Sprintf("There is no %s on this device (%v).", id, e)
	}
	sev, _ := res["severity"].(string)
	head := fmt.Sprintf("[%s] %s (%s, %s).", res["id"], res["title"], chatSevName(sev), res["time"])
	root, _ := res["root_cause"].(string)
	label, _ := res["label"].(string)
	var sens []string
	if ss, ok := res["sensors"].([]map[string]any); ok {
		for _, s := range ss {
			if s["flagged"] != true {
				continue
			}
			d := fmt.Sprintf("%s %s", s["node"], chatMetricName(fmt.Sprint(s["metric"])))
			if p, _ := s["pattern"].(string); p != "" && p != "-" {
				d += ", pattern " + strings.ReplaceAll(p, "_", " ")
			}
			if fk, _ := s["fault_kind"].(string); fk != "" {
				d += ", looks like " + fk
			}
			sens = append(sens, d)
		}
	}
	why := "The AI report is not final yet."
	if root != "" {
		why = "Root cause: " + strings.TrimRight(root, ".") + "."
	}
	if len(sens) > 0 {
		why += " Flagged: " + strings.Join(sens, "; ") + "."
	}
	state := map[string]string{wfNeeds: "It is waiting for your decision (approve or dismiss on the incident page).",
		wfInProgress: "It was approved and its checklist is in progress.", wfResolved: "Readings went back to normal; it waits to be closed.",
		wfClosed: "It is closed.", wfAnalysing: "The AI is still analysing it.", wfInterrupted: "Its analysis was interrupted."}[fmt.Sprint(res["workflow"])]
	if o, _ := res["outcome"].(string); o != "" {
		if t, ok := outcomeText[o]; ok {
			state = strings.TrimRight(state, ".") + " (outcome: " + strings.ToLower(t) + ")."
		}
	}
	steps, _ := res["_open_steps"].([]string)
	stepText := ""
	if len(steps) > 0 {
		stepText = " Open checklist: " + strings.Join(steps[:min(3, len(steps))], "; ") + "."
	}
	switch rt.Act {
	case "realfault":
		verdict := fmt.Sprintf("The AI judged it a real %s problem, not a sensor fault.", chatSevName(sev))
		if sev == "sensor_fault" || label == "sensor_fault" {
			verdict = "The AI judged it a sensor fault, not a real problem in the building."
		} else if sev == "normal" {
			verdict = "The AI judged the readings normal: not a real problem."
		}
		return verdict + " " + head + " " + why + " " + state
	case "do":
		if len(steps) == 0 {
			return head + " " + why + " No checklist step is open. " + state
		}
		return head + stepText + " " + state
	}
	return strings.TrimSpace(head + " " + why + stepText + " " + state)
}

// chatSaySilentRank: a highest/lowest question when no reading of the metric exists in the period.
func (t chatTools) chatSaySilentRank(rt chatRoute) string {
	metric, _ := rt.Args["metric"].(string)
	when := chatPeriodWords[chatPresetOf(rt.Args, "today")]
	sil := t.chatSilent()
	var ss []string
	for k := range sil {
		if strings.HasSuffix(k, " "+metric) {
			ss = append(ss, strings.TrimSuffix(k, " "+metric))
		}
	}
	sort.Strings(ss)
	if len(ss) == 0 || rt.Args["location"] != nil {
		return "" // not a silence (no such sensor, or a place): the model answers
	}
	text := fmt.Sprintf("No %s readings were recorded %s, so there is no highest or lowest value to report.", chatMetricName(metric), when)
	return text + fmt.Sprintf(" %s silent (no new readings): %s.", plural(len(ss), chatMetricName(metric)+" sensor is", chatMetricName(metric)+" sensors are"), chatSilentList(ss, 4))
}
