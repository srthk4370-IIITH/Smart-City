package main

// Night sweep 2026-11-27 (proofs/2026-11-27_handson: findings.md chat sets A/B/C, decisions.md C items). Routes tried
// before the older v25 / polish routes, each for one question class the board run answered wrong:
//   #22 greeting / "?"            -> a hello and three example questions (was the off-topic refusal)
//   #21 unknown incident id       -> "no such incident (latest is X)", never another incident
//   #19 early look                -> what it is and how to judge it (was "no incident waiting for a decision")
//   #15 "what should I do if pf drops" -> the metric's first actions from the device knowledge (was limits only)
//   #90 "which readings are critical right now" -> every critical / warning / faulty reading from the live state
//   #68 "anything wrong in KH level 3" -> that building AND level (was the KH level 98 tank)
//   #92 "why has X not been analysed yet" -> the AI gate state (watching / batch / running), gate_status tool
//   #69 "has this happened before"  -> earlier incidents and outcomes on the same sensor
//   #67 "sensor fault or real?"     -> the explicit verdict of the final report (+ the overruled agent view)
//   #66 "explain the latest incident in simple words" -> the incident's facts (the reasoner writes them plainly)
// All answers are read-only facts from the device; nothing here changes state.

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
)

var (
	chatGreetRe = regexp.MustCompile(`(?i)^\s*(hi+|hii+|hello|hey|hlo|helo|namaste|namaskar|good\s+(morning|afternoon|evening|night)|yo|help|help\s+me|\?+|what\s+can\s+you\s+do\??|who\s+are\s+you\??|how\s+do\s+i\s+use\s+(you|this)\??)[\s!.?]*$`)
	chatEarlyRe = regexp.MustCompile(`(?i)\bearly[\s-]+looks?\b|\bprovisional\s+(report|reading|analysis|ai)\b`)
	chatDoIfRe  = regexp.MustCompile(`(?i)\bwhat\s+(should|do|must|can)\s+(i|we|the\s+\w+(\s+team)?)\s+do\b|\bwhat\s+to\s+do\b|\bhow\s+(do|should|can)\s+(i|we)\s+(fix|handle|respond|react|deal|bring)\b|\bwhat\s+action\b|\bkya\s+kar(na|e|u|un)\b`)
	chatCondRe  = regexp.MustCompile(`(?i)\b(if|when|agar|jab)\b[^?.!]*\b(drops?|falls?|goes|rises?|crosses|exceeds?|is|gets|reaches|below|above|over|under|high|low)\b`)
	// "which readings are critical right now", "any warnings now", "what is abnormal", "list the critical sensors"
	chatLiveBadRe  = regexp.MustCompile(`(?i)\b(critical|warnings?|abnormal|out\s+of\s+range|over\s+(the\s+)?limits?|beyond\s+(the\s+)?limits?|alarming|in\s+alarm)\b`)
	chatLiveAskRe  = regexp.MustCompile(`(?i)\b(which|what|any|list|show|kaun|kaunse|kaunsi|name)\b[^?.!]*\b(readings?|sensors?|values?|meters?|metrics?)\b|\b(readings?|sensors?|values?)\b[^?.!]*\b(are|is)\s+(critical|abnormal|in\s+warning)\b`)
	chatLiveNowRe  = regexp.MustCompile(`(?i)\b(now|right\s+now|currently|current|at\s+the\s+moment|abhi|live|today)\b`)
	chatPlaceBadRe = regexp.MustCompile(`(?i)\b(anything|something|kuch)\s+(wrong|off|abnormal|unusual|bad|happening|going\s+on)\b|\bany\s+(problems?|issues?|trouble|alerts?|alarms?)\b|\b(is\s+)?(everything|all|sab)\s+(ok|okay|fine|good|normal|theek)\b|\bwhat'?s\s+(wrong|happening|going\s+on)\b|\bkya\s+(gadbad|problem|dikkat)\b`)
	chatGateQRe    = regexp.MustCompile(`(?i)\bnot\s+(been\s+|yet\s+)?(analy[sz]ed|reported|alerted|looked\s+at|picked\s+up|raised)\b|\b(no|without)\s+(incident|alert|ai|report|analysis)\s+(yet|for|on)\b|\bwhy\s+(hasn'?t|isn'?t|is\s+there\s+no|no|has\s+no|did\s+not|didn'?t)\b[^?.!]*\b(ai|analys\w*|incident|alert|report)\b|\bwhen\s+will\s+(the\s+)?(ai|analysis|report|full\s+reading)\b|\bwaiting\s+for\s+(the\s+)?ai\b|\bai\s+(gate|wait\w*|queue)\b|\bwhat\s+is\s+the\s+ai\s+(waiting|doing)\b`)
	chatBeforeAskRe   = regexp.MustCompile(`(?i)\bhappened\s+before\b|\b(ever|previously)\s+happened\b|\b(before|earlier)\s+on\s+(this|that|the\s+same)\b|\bpehle\s+bhi\b|\bsame\s+thing\s+before\b|\b(has|did)\s+(this|that|it)\s+(ever\s+)?(happen|occur)\w*\s+(before|again)\b|\bhistory\s+of\s+(this|that|the)\s+(sensor|incident|problem)\b|\bhappen(ed|s)?\s+again\b`)
	chatExplainAskRe  = regexp.MustCompile(`(?i)\b(explain|describe|samjha\w*|batao|bata\s+do|tell\s+me\s+about|what\s+does\s+it\s+mean|what\s+is\s+it\s+about|kya\s+hai)\b`)
	chatLatestRe   = regexp.MustCompile(`(?i)\b(latest|last|newest|most\s+recent|current)\s+(critical\s+|warning\s+)?(incident|alert|alarm|issue|problem)\b`)
)

// chatStaleAt: a reading is stale after 3 missed readings (decision #105: the engine's one rule, sensorStale); an
// unknown reading time (0) is left to the data-quality status.
func chatStaleAt(updated, now int64) bool {
	return updated > 0 && sensorStale(updated, now)
}

// chatHandsonRoutes: ok false = none applies.
func (t chatTools) chatHandsonRoutes(q string, history []ChatMsg, place chatPlace, metrics []string, span chatSpan, dom string, nodes map[string]NodeInfo, picks []chatSensorPick) (chatV25, bool) {
	if chatGreetRe.MatchString(q) {
		return chatV25{chatHelloText(t), nil}, true
	}
	if chatInjectRe.MatchString(q) || chatIsAction(q) {
		return chatV25{}, false // the refusals of chatRouteV25
	}
	if v, ok := t.chatUnknownID(q); ok {
		return v, true
	}
	if chatEarlyRe.MatchString(q) && len(chatIDs(q)) == 0 {
		return t.chatEarlyLook(), true
	}
	if chatGateQRe.MatchString(q) && len(chatIDs(q)) == 0 {
		return t.chatGate(q, picks, nodes), true
	}
	if chatBeforeAskRe.MatchString(q) && !span.Found() {
		if v, ok := t.chatBefore(q, history, place, metrics, picks, nodes); ok {
			return v, true
		}
	}
	if chatRealFaultRe.MatchString(q) && len(chatIDs(q)) == 0 && (len(metrics) > 0 || place.Words || dom != "") && regexp.MustCompile(`(?i)\b(or|ya|vs)\b|\bis\s+(it|this|that|the)\b[^?.!]*\breal\b`).MatchString(q) {
		if v, ok := t.chatVerdictFor(q, place, metrics, dom, nodes); ok {
			return v, true
		}
	}
	if chatDoIfRe.MatchString(q) && len(metrics) > 0 && len(chatIDs(q)) == 0 && chatCondRe.MatchString(q) {
		if v, ok := t.chatMetricActions(metrics, picks); ok {
			return v, true
		}
	}
	if chatLiveBadRe.MatchString(q) && chatLiveAskRe.MatchString(q) && chatLiveNowRe.MatchString(q) && !chatIncWordRe.MatchString(q) && !span.Found() {
		return t.chatLiveAbnormal(q, place, nodes), true
	}
	if chatPlaceBadRe.MatchString(q) && place.Words && len(metrics) == 0 && (place.Building != "" || place.Level >= 0) && !span.Found() {
		return t.chatPlaceNow(place, nodes), true
	}
	if chatExplainAskRe.MatchString(q) && chatLatestRe.MatchString(q) && len(chatIDs(q)) == 0 {
		if v, ok := t.chatExplainLatest(q, place, nodes); ok {
			return v, true
		}
	}
	return chatV25{}, false
}

// ---------------------------------------------------------------- #22 greeting

func chatHelloText(t chatTools) string {
	ex := []string{"Which readings are critical right now?", "What incidents are waiting for a decision?", "What is the CO2 in KH level 3?"}
	if open := t.chatOpenIDs(); len(open) > 0 {
		ex[0] = "Why is " + open[0] + " open and what should I check first?"
	}
	return "Hello! I answer questions about the campus sensors, readings and incidents on this device (I can only read data, not change anything). " +
		"Try: \"" + strings.Join(ex, "\", \"") + "\"."
}

func (t chatTools) chatOpenIDs() []string {
	var ids []string
	for _, ci := range t.incidents() {
		if wfOf(ci.inc) == wfNeeds && !ci.inc.Injected {
			ids = append(ids, ci.inc.ID)
		}
	}
	sort.Slice(ids, func(i, j int) bool { return chatIncSeq(ids[i]) > chatIncSeq(ids[j]) })
	return ids
}

// ---------------------------------------------------------------- #21 unknown incident ids

// chatUnknownID: q names an incident id the device does not have. The answer names only the latest id in words, so
// the next question does not take either id as its referent (chatRefOfMsg needs exactly one id).
func (t chatTools) chatUnknownID(q string) (chatV25, bool) {
	ids := chatIDs(q)
	if len(ids) == 0 {
		return chatV25{}, false
	}
	have := map[string]bool{}
	latest := ""
	for _, ci := range t.incidents() {
		have[ci.inc.ID] = true
		if ci.inc.SystemCheck {
			continue
		}
		if latest == "" || chatIncSeq(ci.inc.ID) > chatIncSeq(latest) {
			latest = ci.inc.ID
		}
	}
	var miss []string
	for _, id := range ids {
		if !have[id] {
			miss = append(miss, id)
		}
	}
	if len(miss) == 0 {
		return chatV25{}, false
	}
	text := fmt.Sprintf("There is no incident %s on this device.", strings.Join(miss, " or "))
	if latest != "" {
		text += fmt.Sprintf(" The newest incident is number %d; ask about it by its id.", chatIncSeq(latest))
	} else {
		text += " The device has no incidents yet."
	}
	return chatV25{text, nil}, true // no tool record: the unknown id must not become the next question's referent
}

// chatUnknownAnswer: an assistant message that answered an unknown id (left out of the model's history, #21).
func chatUnknownAnswer(m ChatMsg) bool {
	return m.Role == "assistant" && strings.HasPrefix(m.Text, "There is no incident ")
}

// chatModelHistory: the history the model sees, without unknown-id exchanges (no carry-forward of a wrong id).
func chatModelHistory(h []ChatMsg) []ChatMsg {
	var out []ChatMsg
	for i := 0; i < len(h); i++ {
		if h[i].Role == "user" && i+1 < len(h) && chatUnknownAnswer(h[i+1]) {
			i++
			continue
		}
		out = append(out, h[i])
	}
	return out
}

// ---------------------------------------------------------------- #19 early look

func (t chatTools) chatEarlyLook() chatV25 {
	tr := trigRules()
	k, _ := earlyAIConfig()
	kb := chatKB("KB-EARLY-LOOK")
	text := kb
	if k > 0 {
		text += fmt.Sprintf(" On this device the early look runs after %d abnormal readings; the full reading needs %d abnormal readings out of the last %d.", k, tr.AbnormalOfWindow, tr.PersistReadings)
	} else {
		text += " Early looks are switched off on this device right now, so every report is a full reading."
	}
	var open []string
	for _, ci := range t.incidents() {
		if ci.inc.RefineStage == "provisional" && wfOf(ci.inc) != wfClosed && !ci.inc.Injected {
			s := fmt.Sprintf("[%s] %s", ci.inc.ID, ci.inc.Title)
			if eta := t.chatFullEta(ci.inc); eta >= 0 {
				s += fmt.Sprintf(" (full reading in about %s)", chatMinWords(eta))
			}
			open = append(open, s)
		}
	}
	if len(open) > 0 {
		text += " Early looks open now: " + strings.Join(open, "; ") + "."
	}
	return chatV25{text, []ChatTool{chatToolRec("search_knowledge", map[string]any{"query": "early look"}, map[string]any{"passages": []string{"KB-EARLY-LOOK"}})}}
}

// chatKBExtra: night sweep 2026-11-27 #15 / #19 knowledge (early look, per-metric first actions). Kept out of
// fog_kb_cache.txt, whose search results must stay identical to the r3 training tools (TestChatFogParity); the
// deterministic routes answer from it.
//
//go:embed chat_kb_extra.txt
var chatKBExtraJSON []byte

var chatKBExtra = func() []kbPassage {
	var ps []kbPassage
	if err := json.Unmarshal(chatKBExtraJSON, &ps); err != nil {
		panic("chat_kb_extra.txt: " + err.Error())
	}
	return ps
}()

func chatKB(id string) string {
	for _, p := range append(append([]kbPassage(nil), chatKBExtra...), fogKBCache...) {
		if p.ID == id {
			return p.Text
		}
	}
	return ""
}

func chatMinWords(s int64) string {
	m := (s + 59) / 60
	if m <= 1 {
		return "a minute"
	}
	return fmt.Sprintf("%d min", m)
}

// ---------------------------------------------------------------- #92 gate status

// chatGateView: the engine's gate view (gateview.go) as plain JSON maps, so new fields need no change here.
func (t chatTools) chatGateView() (watch []map[string]any, batch map[string]any) {
	if t.r == nil || t.r.eng == nil {
		return nil, nil
	}
	b, _ := json.Marshal(t.r.eng.GateView())
	var g struct {
		Watching []map[string]any `json:"watching"`
		Batch    map[string]any   `json:"batch"`
	}
	_ = json.Unmarshal(b, &g)
	return g.Watching, g.Batch
}

func chatNum64(v any) int64 {
	f, _ := v.(float64)
	return int64(f)
}

// chatFullEta: seconds until an early look's full reading (-1 unknown).
func (t chatTools) chatFullEta(inc *Incident) int64 {
	w, _ := t.chatGateView()
	best := int64(-1)
	for _, s := range inc.Sensors {
		if s.Context {
			continue
		}
		for _, g := range w {
			if g["node"] == s.Node && g["metric"] == s.Metric {
				if e := chatNum64(g["eta_s"]); best < 0 || e < best {
					best = e
				}
			}
		}
	}
	return best
}

// gateStatus: the gate_status tool (also callable by the model): what the AI is waiting for.
func (t chatTools) gateStatus(args map[string]any) map[string]any {
	w, b := t.chatGateView()
	node, metric := strArg(args, "node"), strArg(args, "metric")
	var items []map[string]any
	for _, g := range w {
		if (node == "" || g["node"] == node) && (metric == "" || g["metric"] == metric) {
			items = append(items, g)
		}
	}
	if items == nil {
		items = []map[string]any{}
	}
	tr := trigRules()
	out := map[string]any{"watching": items, "need_abnormal": tr.AbnormalOfWindow, "of_last": tr.PersistReadings, "reading_s": bucketSec}
	if b != nil {
		out["batch"] = b
	}
	if t.r != nil {
		out["analysing_now"] = chatNull(t.r.analysingIncident())
	}
	return out
}

func (t chatTools) chatGate(q string, picks []chatSensorPick, nodes map[string]NodeInfo) chatV25 {
	w, batch := t.chatGateView()
	res := t.gateStatus(map[string]any{})
	tool := chatToolRec("gate_status", map[string]any{}, res)
	running := ""
	if t.r != nil {
		running = t.r.analysingIncident()
	}
	tr := trigRules()
	watchOf := func(p chatSensorPick) map[string]any {
		for _, g := range w {
			if g["node"] == p.Node && g["metric"] == p.Metric {
				return g
			}
		}
		return nil
	}
	say := func(g map[string]any, name string) string {
		have, need := chatNum64(g["have"]), chatNum64(g["need"])
		s := fmt.Sprintf("%s has %d of the %d abnormal readings the AI needs", name, have, need)
		eta := chatNum64(g["eta_s"])
		if f, _ := g["fast"].(bool); f {
			s += "; it is critical, so one more critical reading opens an incident at once"
		}
		if hb, _ := g["held_by"].(string); hb != "" && !strings.HasPrefix(hb, fmt.Sprint(g["node"])) {
			s += fmt.Sprintf("; the AI batch is also waiting for %s", strings.ReplaceAll(hb, "|", " "))
		}
		if eta > 0 {
			s += fmt.Sprintf(" (AI in about %s if it stays abnormal)", chatMinWords(eta))
		} else {
			s += " (the AI run is due now)"
		}
		return s
	}
	var parts []string
	if len(picks) > 0 {
		incs := t.incidents()
		for _, p := range picks[:min(4, len(picks))] {
			s := t.chatState(p.Node, p.Metric)
			if s == nil {
				continue
			}
			name := fmt.Sprintf("%s at %s (%s)", chatMetricName(p.Metric), s.Location, p.Node)
			if g := watchOf(p); g != nil {
				parts = append(parts, say(g, strings.ToUpper(name[:1])+name[1:]))
				continue
			}
			var in *chatInc
			for i := range incs {
				ci := &incs[i]
				if wfOf(ci.inc) == wfClosed || ci.inc.Injected {
					continue
				}
				for _, sr := range ci.sensors {
					if sr.Node == p.Node && sr.Metric == p.Metric && (in == nil || ci.at.After(in.at)) {
						in = ci
					}
				}
			}
			switch {
			case in != nil && running == in.inc.ID:
				parts = append(parts, fmt.Sprintf("%s is in [%s] and the AI is writing its report right now", name, in.inc.ID))
			case in != nil && in.inc.RefineStage == "provisional":
				e := ""
				if eta := t.chatFullEta(in.inc); eta >= 0 {
					e = fmt.Sprintf(", full reading in about %s", chatMinWords(eta))
				}
				parts = append(parts, fmt.Sprintf("%s is in [%s] with an early look (a first idea%s)", name, in.inc.ID, e))
			case in != nil:
				parts = append(parts, fmt.Sprintf("%s is already in [%s]; its AI report is done", name, in.inc.ID))
			case s.Last != nil && chatLimitStatus(s.Role, s.Metric, *s.Last) == "normal" && normSeverity(s.Status) != "sensor_fault":
				parts = append(parts, fmt.Sprintf("%s reads %s now, which is normal, so there is nothing for the AI to analyse", name, chatValueWord(p.Metric, *s.Last, s.Unit)))
			default:
				parts = append(parts, fmt.Sprintf("%s is not abnormal in the AI window yet (the AI needs %d abnormal readings out of the last %d)", name, tr.AbnormalOfWindow, tr.PersistReadings))
			}
		}
	}
	if len(parts) == 0 {
		var ws []string
		for _, g := range w[:min(4, len(w))] {
			loc, _ := g["location"].(string)
			ws = append(ws, say(g, fmt.Sprintf("%s at %s", chatMetricName(fmt.Sprint(g["metric"])), loc)))
		}
		if len(ws) == 0 {
			parts = append(parts, "No sensor is waiting for the AI right now")
		} else {
			parts = append(parts, "Waiting for the AI: "+strings.Join(ws, "; "))
		}
	}
	for i := range parts {
		parts[i] = chatCap(parts[i])
	}
	text := strings.Join(parts, ". ") + "."
	if batch != nil {
		text += fmt.Sprintf(" An AI batch is open (opened by %s); it closes within %s.", strings.ReplaceAll(fmt.Sprint(batch["opened_by"]), "|", " "), chatMinWords(chatNum64(batch["closes_within_s"])))
	}
	if running != "" && !strings.Contains(text, "["+running+"] and the AI is writing") {
		text += fmt.Sprintf(" The AI is analysing [%s] right now.", running)
	}
	return chatV25{text, []ChatTool{tool}}
}

// ---------------------------------------------------------------- #69 history on the same sensor

func (t chatTools) chatBefore(q string, history []ChatMsg, place chatPlace, metrics []string, picks []chatSensorPick, nodes map[string]NodeInfo) (chatV25, bool) {
	var node, metric, skip string
	if len(picks) > 0 && (place.Words || len(metrics) > 0) {
		node, metric = picks[0].Node, picks[0].Metric
	} else if ids := chatIDs(q); len(ids) == 1 {
		skip = ids[0]
	} else if id := chatLastAnswerID(history); id != "" {
		// 2026-11-28 re-run: after "Is the pH problem real?" (a verdict answer without a tool record) the older
		// reference (a PM reading two turns back) won and the history went to the dust incident; the latest answer wins
		skip = id
	} else if ref := chatRefOf(history); ref != nil {
		switch {
		case ref.ID != "":
			skip = ref.ID
		case len(ref.Picks) > 0:
			node, metric = ref.Picks[0].Node, ref.Picks[0].Metric
		}
	}
	incs := t.incidents()
	if skip != "" {
		for _, ci := range incs {
			if ci.inc.ID == skip && len(ci.sensors) > 0 {
				node, metric = ci.sensors[0].Node, ci.sensors[0].Metric
			}
		}
	}
	if node == "" {
		return chatV25{}, false
	}
	if skip == "" { // "before" = before the newest open incident on that sensor
		var at time.Time
		for _, ci := range incs {
			if wfOf(ci.inc) == wfClosed || ci.inc.Injected {
				continue
			}
			for _, s := range ci.sensors {
				if s.Node == node && (metric == "" || s.Metric == metric) && ci.at.After(at) {
					skip, at = ci.inc.ID, ci.at
				}
			}
		}
	}
	var prev []chatInc
	for _, ci := range incs {
		if ci.inc.ID == skip || ci.inc.Injected {
			continue
		}
		for _, s := range ci.sensors {
			if s.Node == node && (metric == "" || s.Metric == metric) {
				prev = append(prev, ci)
				break
			}
		}
	}
	sort.Slice(prev, func(i, j int) bool { return prev[i].at.After(prev[j].at) })
	args := map[string]any{"node": node, "metric": metric}
	ids := []string{}
	for _, ci := range prev {
		ids = append(ids, ci.inc.ID)
	}
	tools := []ChatTool{chatToolRec("find_incidents", args, map[string]any{"total": len(prev), "items": ids})}
	ah, err := t.run("get_action_history", map[string]any{"node": node, "metric": metric})
	if err == nil {
		tools = append(tools, chatToolRec("get_action_history", map[string]any{"node": node, "metric": metric}, ah))
	}
	name := fmt.Sprintf("%s on %s", chatMetricName(metric), node)
	if s := t.chatState(node, metric); s != nil && s.Location != "" {
		name = fmt.Sprintf("%s at %s (%s)", chatMetricName(metric), s.Location, node)
	}
	if len(prev) == 0 {
		text := fmt.Sprintf("No: there is no earlier incident on %s on this device", name)
		if skip != "" {
			text += fmt.Sprintf(" besides [%s]", skip)
		}
		return chatV25{text + ".", tools}, true
	}
	var ps []string
	for _, ci := range prev[:min(4, len(prev))] {
		s := fmt.Sprintf("[%s] %s (%s, %s", ci.inc.ID, ci.inc.Title, chatSevName(normSeverity(ci.inc.Severity)), chatTS(ci.at))
		if o := ci.inc.Outcome; o != "" {
			if tx, ok := outcomeText[o]; ok {
				o = strings.ToLower(tx)
			}
			s += ", closed as " + strings.ReplaceAll(o, "_", " ")
		} else {
			s += ", " + chatWfWords(wfOf(ci.inc))
		}
		ps = append(ps, s+")")
	}
	text := fmt.Sprintf("Yes: %s had %s before", name, plural(len(prev), "earlier incident", "earlier incidents"))
	if skip != "" {
		text += fmt.Sprintf(" (besides [%s])", skip)
	}
	text += ": " + strings.Join(ps, "; ") + "."
	if len(prev) > 4 {
		text += fmt.Sprintf(" (%d more.)", len(prev)-4)
	}
	return chatV25{text, tools}, true
}

// ---------------------------------------------------------------- #67 real or sensor fault

// chatVerdictFor: "is the water pH problem a sensor fault or real?" without an id: the open (else newest) incident on
// that metric / place, answered with the explicit verdict (chatSayIncident "realfault").
func (t chatTools) chatVerdictFor(q string, place chatPlace, metrics []string, dom string, nodes map[string]NodeInfo) (chatV25, bool) {
	var best *chatInc
	incs := t.incidents()
	for i := range incs {
		ci := &incs[i]
		if ci.inc.Injected || ci.archived {
			continue
		}
		ok := false
		for _, s := range ci.sensors {
			m := len(metrics) == 0
			for _, w := range metrics {
				m = m || len(chatResolveMetric(w, []string{s.Metric})) > 0 || (w == "wq" && (s.Metric == "ph" || s.Metric == "tds"))
			}
			if m && (!place.Words || chatNodeMatch(s.Node, nodes[s.Node], place)) && (dom == "" || len(metrics) > 0 || s.Role == dom) {
				ok = true
			}
		}
		if !ok {
			continue
		}
		if best == nil || (wfOf(ci.inc) == wfNeeds) != (wfOf(best.inc) == wfNeeds) && wfOf(ci.inc) == wfNeeds ||
			(wfOf(ci.inc) == wfNeeds) == (wfOf(best.inc) == wfNeeds) && ci.at.After(best.at) {
			best = ci
		}
	}
	if best == nil {
		return chatV25{}, false
	}
	rt := chatRoute{Tool: "get_incident", Args: map[string]any{"id": best.inc.ID}, Act: "realfault"}
	res, err := t.run("get_incident", rt.Args)
	if err != nil {
		return chatV25{}, false
	}
	t.chatAugment(rt, res)
	return chatV25{chatSayIncident(rt, res), []ChatTool{chatToolRec("get_incident", rt.Args, res)}}, true
}

// ---------------------------------------------------------------- #15 per-metric actions

// chatActionKB: the device-knowledge passage with the first actions for each metric (fog_kb_cache.txt).
var chatActionKB = map[string]string{"pf": "SOP-PF-01", "power_kw": "SOP-PW-01", "co2": "SOP-AQ-01", "pm25": "SOP-PM-01", "pm10": "SOP-PM-01",
	"ph": "SOP-WT-02", "tds": "SOP-WT-03", "level": "SOP-WT-01", "flow": "SOP-WT-01", "temp": "SOP-HV-02", "room_temp": "SOP-HV-02",
	"rh": "SOP-HV-03", "wq": "SOP-WT-02", "aq": "SOP-AQ-01"}

func (t chatTools) chatMetricActions(metrics []string, picks []chatSensorPick) (chatV25, bool) {
	var parts []string
	var used []string
	for _, w := range metrics {
		id := chatActionKB[w]
		if id == "" || contains(used, id) {
			continue
		}
		if tx := chatKB(id); tx != "" {
			used = append(used, id)
			name := chatMetricName(w)
			if w != "ph" && w != "pf" {
				name = strings.ToUpper(name[:1]) + name[1:]
			}
			lim := ""
			if m, ok := chatMetricLimits(w); ok {
				lim = " " + m
			}
			parts = append(parts, fmt.Sprintf("%s%s: %s", name, lim, tx))
		}
	}
	if len(parts) == 0 {
		return chatV25{}, false
	}
	text := strings.Join(parts, " ")
	tools := []ChatTool{chatToolRec("search_knowledge", map[string]any{"query": strings.Join(metrics, " ") + " actions"}, map[string]any{"passages": used})}
	if len(picks) > 0 && len(picks) <= 2 {
		if v, tl := t.chatValues(picks, false); v != "" {
			text += " Right now: " + v
			tools = append(tools, tl)
		}
	}
	return chatV25{text, tools}, true
}

// chatMetricLimits: "(warning below 0.85, critical below 0.7)" from the rule limits of any role that has them.
func chatMetricLimits(metric string) (string, bool) {
	var keys []string
	for k := range Metrics {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		m := Metrics[k]
		if !strings.HasSuffix(k, "/"+metric) || !m.HasLimits {
			continue
		}
		dir := "above"
		if m.Dir == "low" {
			dir = "below"
		}
		if metric == "ph" {
			return "(warning below 6.5 or from 8.5, critical below 6.0 or from 9.0)", true
		}
		return fmt.Sprintf("(warning %s %s, critical %s %s)", dir, chatNum(m.Warn, ""), dir, chatNum(m.Crit, "")), true
	}
	return "", false
}

// ---------------------------------------------------------------- #90 every abnormal reading now

type chatBadRow struct {
	sev  string
	line string
	rank int
}

func (t chatTools) chatLiveAbnormal(q string, place chatPlace, nodes map[string]NodeInfo) chatV25 {
	want := map[string]bool{"critical": true, "warning": true, "sensor_fault": true}
	cw := regexp.MustCompile(`(?i)\bcritical\b`).MatchString(q)
	ww := regexp.MustCompile(`(?i)\bwarnings?\b`).MatchString(q)
	if cw && !ww {
		want = map[string]bool{"critical": true}
	} else if ww && !cw {
		want = map[string]bool{"warning": true}
	}
	rows, checked, stale := t.chatBadRows(place, nodes)
	var shown []chatBadRow
	count := map[string]int{}
	for _, r := range rows {
		if want[r.sev] {
			shown = append(shown, r)
			count[r.sev]++
		}
	}
	res := map[string]any{"checked": checked, "critical": count["critical"], "warning": count["warning"], "sensor_fault": count["sensor_fault"], "stale": stale}
	tool := chatToolRec("current_levels", map[string]any{"status": keysOf(want)}, res)
	where := "on this device"
	if place.Words {
		where = chatPlaceWords(place)
	}
	if len(shown) == 0 {
		var ws []string
		for _, s := range []string{"critical", "warning", "sensor_fault"} {
			if want[s] {
				ws = append(ws, chatSevName(s))
			}
		}
		text := fmt.Sprintf("No reading is %s right now %s (%d live readings checked against their limits).", strings.Join(ws, " or "), where, checked)
		if stale > 0 {
			text += fmt.Sprintf(" %s sent no new reading for over 15 minutes, so they are not counted.", plural(stale, "sensor has", "sensors have"))
		}
		return chatV25{text, []ChatTool{tool}}
	}
	var heads []string
	for _, s := range []string{"critical", "warning", "sensor_fault"} {
		if count[s] > 0 {
			heads = append(heads, fmt.Sprintf("%d %s", count[s], map[string]string{"critical": "critical", "warning": "warning", "sensor_fault": "flagged as sensor fault"}[s]))
		}
	}
	var lines []string
	for _, r := range shown[:min(10, len(shown))] {
		lines = append(lines, r.line)
	}
	text := fmt.Sprintf("%s right now %s (%s): %s.", plural(len(shown), "reading is abnormal", "readings are abnormal"), where, strings.Join(heads, ", "), strings.Join(lines, "; "))
	if len(shown) > 10 {
		text += fmt.Sprintf(" (%d more.)", len(shown)-10)
	}
	if stale > 0 {
		text += fmt.Sprintf(" %s sent no new reading for over 15 minutes, so they are not counted.", plural(stale, "sensor has", "sensors have"))
	}
	return chatV25{text, []ChatTool{tool}}
}

func keysOf(m map[string]bool) []string {
	var out []string
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// chatBadRows: every live reading (at the place) whose CURRENT value is beyond a limit or is flagged faulty, worst
// first; stale readings are counted apart (no data, #105).
func (t chatTools) chatBadRows(place chatPlace, nodes map[string]NodeInfo) (rows []chatBadRow, checked, stale int) {
	if t.r == nil || t.r.eng == nil {
		return nil, 0, 0
	}
	_, states, _ := t.r.eng.Snapshot()
	faults := t.chatFaultsNow(t.incidents())
	rank := map[string]int{"critical": 0, "sensor_fault": 1, "warning": 2}
	for _, s := range states {
		if place.Words && !chatNodeMatch(s.Node, nodes[s.Node], place) {
			continue
		}
		if s.Last == nil {
			continue
		}
		if chatStaleAt(s.Updated, t.now.Unix()) || s.Quality == "stale" {
			stale++
			continue
		}
		checked++
		st := chatLiveStatus(s, faults)
		if st != "critical" && st != "warning" && st != "sensor_fault" {
			continue
		}
		val := chatValueWord(s.Metric, *s.Last, s.Unit)
		if s.Metric == "ph" {
			val = strings.TrimSuffix(val, " pH")
		}
		line := fmt.Sprintf("%s %s at %s (%s)", chatMetricName(s.Metric), val, s.Location, s.Node)
		if st == "sensor_fault" {
			line += ", flagged as a sensor fault"
		} else if m, ok := Metrics[s.Role+"/"+s.Metric]; ok && m.HasLimits {
			lim := m.Crit
			if st == "warning" {
				lim = m.Warn
			}
			dir := "above"
			if m.Dir == "low" {
				dir = "below"
			}
			if s.Metric == "ph" {
				line += ", " + st
			} else {
				line += fmt.Sprintf(", %s (%s %s)", st, dir, chatNum(lim, s.Unit))
			}
		}
		rows = append(rows, chatBadRow{st, line, rank[st]})
	}
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].rank < rows[j].rank })
	return rows, checked, stale
}

// ---------------------------------------------------------------- #68 one place now

// chatPlaceNow: "is anything wrong in KH level 3 right now?": the abnormal readings and open incidents of exactly that
// building and level.
func (t chatTools) chatPlaceNow(place chatPlace, nodes map[string]NodeInfo) chatV25 {
	rows, checked, stale := t.chatBadRows(place, nodes)
	where := chatPlaceWords(place)
	var open []string
	for _, ci := range t.incidents() {
		if wfOf(ci.inc) == wfClosed || ci.inc.Injected || ci.archived {
			continue
		}
		for _, s := range ci.sensors {
			if chatNodeMatch(s.Node, nodes[s.Node], place) {
				open = append(open, fmt.Sprintf("[%s] %s (%s, %s)", ci.inc.ID, ci.inc.Title, chatSevName(normSeverity(ci.inc.Severity)), chatWfWords(wfOf(ci.inc))))
				break
			}
		}
	}
	res := map[string]any{"checked": checked, "abnormal": len(rows), "stale": stale, "open_incidents": len(open)}
	tool := chatToolRec("current_levels", map[string]any{"location": strings.TrimPrefix(where, "at ")}, res)
	if checked == 0 && stale == 0 {
		return chatV25{fmt.Sprintf("This device has no sensors %s.", where), []ChatTool{tool}}
	}
	var text string
	if len(rows) == 0 {
		text = fmt.Sprintf("Nothing is abnormal %s right now: all %s within their limits.", where, plural(checked, "live reading is", "live readings are"))
	} else {
		var ls []string
		for _, r := range rows[:min(6, len(rows))] {
			ls = append(ls, r.line)
		}
		text = fmt.Sprintf("Yes, %s %s: %s.", plural(len(rows), "reading is abnormal", "readings are abnormal"), where, strings.Join(ls, "; "))
	}
	if len(open) > 0 {
		text += " Open incidents there: " + strings.Join(open[:min(3, len(open))], "; ") + "."
	}
	if stale > 0 {
		text += fmt.Sprintf(" %s there sent no new reading for over 15 minutes, so %s not checked.", plural(stale, "sensor", "sensors"), map[bool]string{true: "it is", false: "they are"}[stale == 1])
	}
	return chatV25{text, []ChatTool{tool}}
}

// ---------------------------------------------------------------- #66 explain the latest incident

func (t chatTools) chatExplainLatest(q string, place chatPlace, nodes map[string]NodeInfo) (chatV25, bool) {
	sev := ""
	if regexp.MustCompile(`(?i)\bcritical\b`).MatchString(q) {
		sev = "critical"
	} else if regexp.MustCompile(`(?i)\bwarning\b`).MatchString(q) {
		sev = "warning"
	}
	var best *chatInc
	incs := t.incidents()
	for i := range incs {
		ci := &incs[i]
		if ci.inc.Injected || ci.archived || (sev != "" && normSeverity(ci.inc.Severity) != sev) {
			continue
		}
		if place.Words {
			ok := false
			for _, s := range ci.sensors {
				ok = ok || chatNodeMatch(s.Node, nodes[s.Node], place)
			}
			if !ok {
				continue
			}
		}
		if best == nil || ci.at.After(best.at) || ci.at.Equal(best.at) && chatIncSeq(ci.inc.ID) > chatIncSeq(best.inc.ID) {
			best = ci
		}
	}
	if best == nil {
		return chatV25{}, false
	}
	rt := chatRoute{Tool: "get_incident", Args: map[string]any{"id": best.inc.ID}, Act: "realfault"}
	res, err := t.run("get_incident", rt.Args)
	if err != nil {
		return chatV25{}, false
	}
	t.chatAugment(rt, res)
	return chatV25{chatSayIncident(rt, res), []ChatTool{chatToolRec("get_incident", rt.Args, res)}}, true
}

// ---------------------------------------------------------------- #24 multi-part questions

var chatPartSplitRe = regexp.MustCompile(`(?i),?\s+(?:and\s+)?then\s+|;\s*|\band\s+also\b|\balso\s+(?:tell|give|say|explain|show|list)\b|\?\s+(?:and\s+)?(?:what|which|how|is|are|why|when|where|who|can|should|does|do)\b`)

// chatMultiPart: a question with two or more asks ("explain X in one sentence, then give the value, then say ...").
func chatMultiPart(q string) bool {
	n := 0
	for _, p := range chatPartSplitRe.Split(q, -1) {
		if len(strings.Fields(p)) >= 2 {
			n++
		}
	}
	return n >= 2
}

// chatIncAt: the incident has a flagged sensor at the place (any place when the question names none).
func chatIncAt(ci chatInc, place chatPlace, nodes map[string]NodeInfo) bool {
	if !place.Words {
		return true
	}
	for _, s := range ci.sensors {
		if chatNodeMatch(s.Node, nodes[s.Node], place) {
			return true
		}
	}
	return false
}

// chatCap: the first letter upper case ("pH" stays as written).
func chatCap(s string) string {
	if s == "" || strings.HasPrefix(s, "pH") {
		return s
	}
	return strings.ToUpper(s[:1]) + s[1:]
}

// chatFaultOverruled: the final report (not preliminary) kept a real label, so an agent's sensor_fault status on one of
// its sensors was overruled and does not flag that sensor as faulty (night sweep 2026-11-27 #67, the pH case).
func chatFaultOverruled(ci chatInc) bool {
	return ci.label != "" && ci.label != "sensor_fault" && normSeverity(ci.inc.Severity) != "sensor_fault"
}

// chatLastAnswerID: the single incident id the latest assistant answer was about ("" if none or several).
func chatLastAnswerID(history []ChatMsg) string {
	for i := len(history) - 1; i >= 0; i-- {
		if history[i].Role != "assistant" {
			continue
		}
		if ids := chatIDs(history[i].Text); len(ids) == 1 {
			return ids[0]
		}
		return ""
	}
	return ""
}
