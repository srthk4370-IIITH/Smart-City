package main

import (
	"encoding/json"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"
)

// deploy25 (blind chat sweep 2026-11-01, proofs/2026-11-01_chat/VERDICT_blind.md). The deploy23/24 routes were tuned on
// two question sets and failed fresh wording (5/11 on the first blind slice). This layer runs first and works by
// question TYPE, not by phrase:
//   - chatIntentOf: action / injection / out-of-scope / reading (value) / sensor health / incidents / scenario, for
//     English, Hinglish (kitna, theek hai, kharab, ghante, kal) and typos (chatNormalize);
//   - chatSpanOf (chat_time.go): every time span, never silently widened;
//   - chatRefOf: what the previous answer was about (an incident set with its filters, one incident, or sensors), so
//     follow-ups ("any of those still unresolved?", "humidity in that room", "is that normal?") keep their referent;
//   - chatResolveSensors / chatPickMetrics: the sensors a question means and the metric for each (a temperature
//     question on an AC unit is room_temp, never its on/off state);
//   - chatValidateCall / chatCheckAnswer (chat.go): the model's tool arguments and answer ids are checked.

// ---------------------------------------------------------------- normalising

// chatTypos: common chat shorthand and misspellings -> the word (whole words only).
var chatTypos = map[string]string{"hw": "how", "mny": "many", "abt": "about", "wat": "what", "wht": "what", "rite": "right", "nw": "now",
	"lvl": "level", "lvls": "levels", "flr": "floor", "temp.": "temp", "pls": "please", "plz": "please", "u": "you", "r": "are", "ur": "your",
	"thr": "there", "ther": "there", "wen": "when", "watr": "water", "sensr": "sensor", "sensrs": "sensors", "senser": "sensor", "snsr": "sensor",
	"alrt": "alert", "alrts": "alerts", "incdent": "incident", "incidnt": "incident", "incidnets": "incidents", "temprature": "temperature",
	"tempreature": "temperature", "temperture": "temperature", "temparature": "temperature", "tempratur": "temperature", "humidty": "humidity",
	"humidiy": "humidity", "humidit": "humidity", "occupancey": "occupancy", "ocupancy": "occupancy", "presure": "pressure", "elec": "electric",
	"yday": "yesterday", "yest": "yesterday", "tmrw": "tomorrow", "2day": "today", "hrs": "hours", "hr": "hour", "mins": "minutes", "min": "minute",
	"wk": "week", "wks": "weeks", "thik": "theek", "thk": "theek", "kitn": "kitna", "kya.": "kya", "abhe": "abhi", "abi": "abhi", "pani": "water",
	"bijli": "power", "garmi": "heat", "rm": "room", "bldg": "building", "bldng": "building", "co₂": "co2", "pm2.5": "pm25", "aircon": "AC",
	"criticl": "critical", "warnng": "warning", "pendng": "pending", "statsu": "status", "staus": "status", "readng": "reading", "readings?": "readings"}

// chatVocab: words a misspelling is matched against (edit distance 1, or 2 for long words).
var chatVocab = []string{"temperature", "humidity", "occupancy", "incident", "incidents", "sensor", "sensors", "reading", "readings", "alert", "alerts",
	"warning", "warnings", "critical", "pending", "status", "building", "level", "water", "power", "energy", "weather", "outdoor", "indoor",
	"yesterday", "today", "tomorrow", "overnight", "morning", "evening", "minutes", "hours", "weeks", "days", "month", "approved", "dismissed",
	"unresolved", "resolved", "faulty", "broken", "normal", "current", "currently", "running", "setpoint", "feeder", "substation", "station",
	"meter", "flow", "tank", "quality", "average", "highest", "lowest", "compare", "summary", "domain", "domains", "severity", "happened",
	"anything", "problem", "problems", "trouble", "rooftop", "classroom", "humid", "carbon", "dioxide", "pressure", "consumption", "load"}

var chatWordRe = regexp.MustCompile(`[A-Za-z][A-Za-z0-9.₂]*`)

func chatEditDist(a, b string) int {
	if a == b {
		return 0
	}
	ra, rb := []rune(a), []rune(b)
	prev := make([]int, len(rb)+1)
	cur := make([]int, len(rb)+1)
	for j := range prev {
		prev[j] = j
	}
	for i := 1; i <= len(ra); i++ {
		cur[0] = i
		for j := 1; j <= len(rb); j++ {
			c := 1
			if ra[i-1] == rb[j-1] {
				c = 0
			}
			cur[j] = min(min(prev[j]+1, cur[j-1]+1), prev[j-1]+c)
		}
		prev, cur = cur, prev
	}
	return prev[len(rb)]
}

// chatNormalize fixes shorthand and misspellings word by word (case of the rest kept; node ids and codes untouched).
func chatNormalize(q string) string {
	known := map[string]bool{}
	for _, w := range chatVocab {
		known[w] = true
	}
	return chatWordRe.ReplaceAllStringFunc(q, func(w string) string {
		lw := strings.ToLower(w)
		if r, ok := chatTypos[lw]; ok {
			return r
		}
		if len(lw) < 5 || known[lw] || w == strings.ToUpper(w) || strings.ContainsAny(w, "0123456789") {
			return w
		}
		best, bd := "", 3
		for _, v := range chatVocab {
			if math.Abs(float64(len(v)-len(lw))) > 2 || v[0] != lw[0] {
				continue
			}
			lim := 1
			if len(v) >= 8 {
				lim = 2
			}
			if strings.HasPrefix(v, lw) || strings.HasPrefix(lw, v) {
				continue // an inflection ("approve" / "approved"), not a misspelling
			}
			if d := chatEditDist(lw, v); d <= lim && d < bd {
				best, bd = v, d
			}
		}
		if best != "" {
			return best
		}
		return w
	})
}

// ---------------------------------------------------------------- intent

var (
	chatInjectRe = regexp.MustCompile(`(?i)\bignore\s+(all\s+|any\s+|your\s+|the\s+|previous\s+|prior\s+|above\s+)*(rules?|instructions?|prompts?|guidelines?)\b|` +
		`\bsystem\s+prompt\b|\byou\s+are\s+now\b|\b(maintenance|developer|admin|god|debug|root)\s+mode\b|\bjailbreak\b|\bpretend\s+(to\s+be|you)\b|` +
		`\b(reveal|print|show|repeat)\s+(me\s+)?(your|the)\s+(full\s+)?(instructions?|prompt|rules)\b|\bnew\s+instructions?\b|\boverride\s+(your|the)\s+(rules|safety)\b`)
	chatActVerbV25 = `set|increase|decrease|raise|lower|change|adjust|modify|update|turn|switch|shut|start|stop|restart|reboot|reset|open|close|` +
		`delete|remove|erase|clear|purge|approve|dismiss|acknowledge|ack|resolve|silence|mute|disable|enable|override|calibrate|trigger|cancel|` +
		`book|schedule|order|send|email|call|lock|unlock|assign|escalate|replace|activate|deactivate|power\s+(?:off|on|down|up)|bump|crank|drop`
	chatActStartRe = regexp.MustCompile(`(?i)^\s*(?:ok(?:ay)?[,\s]+|hey[,\s]+|so[,\s]+)?(?:please\s+|pls\s+|kindly\s+|just\s+|now\s+)?(` + chatActVerbV25 + `)\b`)
	chatActAskRe   = regexp.MustCompile(`(?i)\b(?:can|could|will|would)\s+you\s+(?:please\s+|just\s+|kindly\s+|quickly\s+)*(` + chatActVerbV25 + `)\b|` +
		`\b(?:please|pls|kindly)\s+(` + chatActVerbV25 + `)\b|\b(?:i\s+want|i'd\s+like|i\s+need)\s+you\s+to\s+(` + chatActVerbV25 + `)\b|` +
		`\b(` + chatActVerbV25 + `)\b[^?.!]*\bfor\s+me\b`)
	chatActHiRe = regexp.MustCompile(`(?i)\b(band|chalu|on|off|delete|reset|approve|dismiss|set|clear|restart)\s+(kar\s*(do|dena|dijiye|o)|karo|kijiye)\b|` +
		`\b(badha|ghata|kam|hata|mita)\s*(do|dijiye|o|na)\b`)
	// read-only openings: a sentence starting like this asks, it does not order
	chatReadOpenRe = regexp.MustCompile(`(?i)^\s*(what|which|who|whom|when|where|why|how|is|are|was|were|did|does|do|has|have|had|any|kya|kitn|kab|kaun|kahan|show|list|tell|give|explain|compare|summar|count|find|check|if|suppose|imagine)\b`)

	// campus-monitoring vocabulary: a question with none of it is out of scope
	chatScopeRe = regexp.MustCompile(`(?i)\b(sensors?|incidents?|alerts?|alarms?|warnings?|critical|campus|buildings?|rooms?|floors?|levels?|classrooms?|labs?|hvac|ac|a/c|air|aircon\w*|cool\w*|heat\w*|` +
		`power|energy|electric\w*|load|kw|feeder|substation|meters?|water|tanks?|flow|tds|ph|leak\w*|valves?|pumps?|co2|carbon|pm\s*2\.?5|pm25|pm10|humid\w*|temp\w*|weather|wind|rain|` +
		`outdoor|outside|occupan\w*|people|crowd\w*|device|npu|board|qidk|monitor\w*|readings?|values?|faults?|faulty|broken|kharaa?b|pending|approv\w*|dismiss\w*|` +
		`setpoint|units?|stations?|rooftop|roof|kh|vn|sb|kn|inc-?\d+|domains?|severity|maintenance|checklist|report|reasoner|agents?|model|you|summary|status|health|pani|bijli|garmi|mausam|hawa|log|kamra)\b`)
	chatOOSCueRe = regexp.MustCompile(`(?i)\b(share\s+price|stock|crypto|bitcoin|recipe|movie|song|joke|poem|cricket|football|score|news|translate|python|javascript|code|script|program|essay|homework|` +
		`capital\s+of|president|prime\s+minister|restaurant|flight|train\s+ticket|meeting\s+room|calendar|invite)\b`)

	// a what-if (not "check if the room is occupied")
	chatWhatIfV25Re = regexp.MustCompile(`(?i)\bwhat\s+(would\s+happen\s+|happens\s+|will\s+happen\s+)?if\b|\bsuppose\b|\bimagine\b|^\s*if\b|\bif\s+(we|they|i|you|someone)\b|\bwhat\s+happens\b|\bwhat\s+would\s+happen\b|\bagar\b`)
	chatIncQRe      = regexp.MustCompile(`(?i)\b(incidents?|alerts?|alarms?|warnings?|events?|issues?|problems?|trouble|faults?|anomal\w*|flag(ged|s)?|raised?|fired?|triggered|went\s+wrong|go(ne)?\s+wrong|happen\w*|hua|hue|hui|aaya|aaye|aayi|aya|aye|kya\s+kya|kuch|anything|dismissed|approved|pending|unresolved|open)\b`)
	chatCountQRe    = regexp.MustCompile(`(?i)\bhow\s+many\b|\bcount\b|\bnumber\s+of\b|\bkitne\b|\btotal\b`)
	chatGroupRe     = regexp.MustCompile(`(?i)\b(?:per|by|each|every|for\s+each|breakdown\s+by|split\s+by|grouped\s+by|har)\s+(domain|severity|building|sensor|node|metric|day|type|category|system)\b|\bwhich\s+(domain|building|sensor|metric|day|system)\b|\b(domain|severity|building)[\s-]?wise\b`)
	chatApprBothRe  = [2]*regexp.Regexp{regexp.MustCompile(`(?i)\bapprov\w*`), regexp.MustCompile(`(?i)\bdismiss\w*`)}
	chatRankWordRe  = regexp.MustCompile(`(?i)\b(fewest|least|lowest|most|highest|top|sabse\s+(kam|zyada|jyada))\b`)
	chatCompareRe   = regexp.MustCompile(`(?i)\b(compare|vs\.?|versus|compared\s+(to|with)|than)\b`)
	chatValueCueRe  = regexp.MustCompile(`(?i)\b(signs?\s+of|any\s+signs?|signs?\s+hai|check|dekh\w*|batao|bata\s+do|look\s+at|kitna|kitni|kya\s+hai|kya\s+h|how\s+much|what('s|\s+is|\s+are)\s+(the|it|its)|reading|readings|value|values|theek|thik|ok|okay|normal|fine|high|low|right\s+now|abhi|currently|current|now|at\s+the\s+moment|running|switched\s+on|turned\s+on|on\s+or\s+off|set\s+to|set\s+at|setpoint|occupied|empty|khali|anyone|anybody|koi\s+hai|log\s+hain|how\s+(hot|cold|humid|warm|busy|full)|levels?\s+(now|today)|le\s+raha|chal\s+raha|chal\s+rahi|draw\w*|consum\w*|status\s+of|cooling)\b`)
	chatTrendRe     = regexp.MustCompile(`(?i)\b(trend|trending|change[ds]?|changing|rising|falling|going\s+up|going\s+down|increas\w*|decreas\w*|over\s+the\s+(last|past)|history|ago|pehle|was\s+it|earlier|same\s+as|badal\w*|graph|plot)\b`)
	chatHealthQRe   = regexp.MustCompile(`(?i)\b(faulty|broken|kharaa?b|dead|malfunction\w*|working(\s+properly)?|reporting(\s+normally)?|stuck|glitch\w*|offline|silent|data\s+coming|functioning)\b`)
	chatScenarioRe  = regexp.MustCompile(`(?i)\b(fails?|failed|failing|failure|breaks?\s+down|trips?|tripped|leaks?|leaking|bursts?|stops?\s+working|goes\s+(offline|down|dead)|shut|outage|blackout|clogs?|jams?|overflows?)\b`)
	chatHowFastRe   = regexp.MustCompile(`(?i)\bhow\s+(fast|quickly|soon|long)\b|\bwould\s+(we|you|it)\s+(know|notice|detect|alert)\b|\bwhat\s+would\s+(the\s+)?sensors?\s+show\b|\bwhich\s+(sensors?|systems?)\s+would\b`)
	chatOldestRe    = regexp.MustCompile(`(?i)\b(longest|oldest|earliest|waiting\s+the\s+most|been\s+waiting)\b`)
	chatHowLongRe   = regexp.MustCompile(`(?i)\bhow\s+long\b|\bsince\s+when\b|\bkab\s+se\b|\bhow\s+old\b`)
	chatWhoRe       = regexp.MustCompile(`(?i)\bwho\b|\bkisne\b|\bkis\s+ne\b|\bkisi\s+ne\b|\bhandled\b|\bapproved\s+by\b`)
	chatWorstRe     = regexp.MustCompile(`(?i)\b(most\s+serious|most\s+severe|worst|most\s+critical|most\s+important|biggest|serious\s+one|sabse\s+(bada|serious|kharab))\b`)
	chatBackRefRe   = regexp.MustCompile(`(?i)\b(those|them|these|they|it|its|that|this|there|same|wahan|waha|wahaan|us|uska|uski|unme|unmein|inme|inmein|iska|iski|isme|ye|yeh|woh|wo)\b`)
	chatFollowStRe  = regexp.MustCompile(`(?i)^\s*(and|also|then|so|ok(ay)?|aur|what\s+about|how\s+about|same\s+for|is\s+that|was\s+it|is\s+it|are\s+they)\b`)
)

const (
	intModel    = ""
	intAction   = "action"
	intInject   = "inject"
	intOOS      = "oos"
	intFuture   = "future"
	intValue    = "value"
	intHealth   = "health"
	intIncident = "incident"
	intScenario = "scenario"
)

// chatIsAction: a request to change something (any sentence of q starting with an action verb, or asking for one).
func chatIsAction(q string) bool {
	if chatWhatIfV25Re.MatchString(q) && !regexp.MustCompile(`(?i)^\s*(please\s+)?(set|increase|decrease|raise|lower|turn|switch)\b`).MatchString(q) {
		return false
	}
	for _, s := range regexp.MustCompile(`[.!;\n]+`).Split(q, -1) {
		if strings.TrimSpace(s) == "" {
			continue
		}
		if chatActStartRe.MatchString(s) && !chatReadOpenRe.MatchString(s) {
			return true
		}
	}
	return chatActAskRe.MatchString(q) || chatActHiRe.MatchString(q)
}

// chatIntentOf: the question type ("" = leave to the other routes / the model).
func chatIntentOf(q string, span chatSpan, sensors []string, metrics []string, ctx bool) string {
	// out of scope: an explicit off-topic cue, or no campus word at all in a fresh question that asks about no time or
	// incident ("what went wrong overnight?" and "what was the root cause" after an answer are in scope)
	strong := chatOOSCueRe.MatchString(q) && len(metrics) == 0 && !chatIncQRe.MatchString(q)
	weak := !ctx && !chatScopeRe.MatchString(q) && !chatIncQRe.MatchString(q) && !span.Found() && !span.Future
	switch {
	case chatInjectRe.MatchString(q):
		return intInject
	case chatIsAction(q):
		return intAction
	case strong || weak:
		return intOOS
	}
	if chatWhatIfV25Re.MatchString(q) && chatScenarioRe.MatchString(q) && chatHowFastRe.MatchString(q) {
		return intScenario
	}
	if chatWhatIfV25Re.MatchString(q) || chatIDRe.MatchString(q) {
		return intModel
	}
	if span.Future {
		return intFuture
	}
	thing := len(sensors) > 0 || len(metrics) > 0
	if thing && chatHealthQRe.MatchString(q) && !chatCountQRe.MatchString(q) && !span.Found() {
		return intHealth
	}
	incWords := chatIncQRe.MatchString(q)
	// peaks and averages are the rank / history routes of chat_router.go; explanations go to the model
	ranked := chatPeakRe.MatchString(q) || regexp.MustCompile(`(?i)\b(average|mean|explain|why|how\s+does|what\s+does|meaning|calculated|measured)\b`).MatchString(q)
	if thing && !incWords && !ranked && !chatCountQRe.MatchString(q) && !chatGroupRe.MatchString(q) &&
		(chatValueCueRe.MatchString(q) || chatTrendRe.MatchString(q) || len(strings.Fields(q)) <= 6) {
		return intValue
	}
	// "how many people in room 3" / "how many AC units are on": a count of a reading, not of incidents
	if thing && !incWords && chatCountQRe.MatchString(q) && (contains(metrics, "occ") || contains(metrics, "ac_on") || contains(metrics, "ac_units_on")) {
		return intValue
	}
	if incWords || (chatCountQRe.MatchString(q) && chatIncWordRe.MatchString(q)) {
		return intIncident
	}
	return intModel
}

// ---------------------------------------------------------------- sensors and metrics

// chatMetricWords: words -> metric, beyond chatPeakMetrics (state words of an AC, occupancy, power draw).
var chatMetricWords = []struct {
	re     *regexp.Regexp
	metric string
}{
	{regexp.MustCompile(`(?i)\bset\s*-?\s*(points?|to|at)\b|\bsetpoint\b|\bset\s+temp\w*`), "setpoint"},
	{regexp.MustCompile(`(?i)\b(running|switched\s+on|turned\s+on|is\s+(it\s+)?on|on\s+or\s+off|chal\s+raha|chal\s+rahi|chalu|on\s+hai|off\s+hai|ac\s+(be\s+)?on|be\s+on)\b|\bwhich\s+ac\b[^?]*\b(on|running)\b`), "ac_on"},
	{regexp.MustCompile(`(?i)\b(anyone|anybody|people|log|occupied|empty|khali|vacant|koi\s+hai)\b|\boccupan\w*`), "occ"},
	{regexp.MustCompile(`(?i)\b(power\s*factor|pf)\b`), "pf"},
	{regexp.MustCompile(`(?i)\b(load|kw|kilowatt\w*|power\s+draw|draw\w*|consum\w*|demand|le\s+raha|bijli|power)\b`), "power_kw"},
	{regexp.MustCompile(`(?i)\bco2\b|\bcarbon\b|\bstuffy\b|\bventilation\b`), "co2"},
	{regexp.MustCompile(`(?i)\bpm\s*2\.?5\b|\bpm25\b`), "pm25"},
	{regexp.MustCompile(`(?i)\bpm\s*10\b`), "pm10"},
	{regexp.MustCompile(`(?i)\bhumid\w*|\brh\b|\bnami\b`), "rh"},
	{regexp.MustCompile(`(?i)\btds\b|\bdissolved\b`), "tds"},
	{regexp.MustCompile(`(?i)\bph\b`), "ph"},
	{regexp.MustCompile(`(?i)\bwater\s+quality\b`), "wq"}, // pH and TDS (2026-11-03: was TDS only, so pH alerts were missed)
	{regexp.MustCompile(`(?i)\bwater\s*level\b|\btank\s+level\b|\btanks?\b|\boverflow\w*\b`), "level"},
	{regexp.MustCompile(`(?i)\bflow\b|\bleak\w*`), "flow"},
	{regexp.MustCompile(`(?i)\bwind\b|\bhawa\b`), "wind"},
	{regexp.MustCompile(`(?i)\btemp\w*|\bhot\b|\bcold\b|\bwarm\w*|\bgaram\b|\bthanda\b|\bheat\b|\bcooling\b|\bcool\b`), "temp"},
	{regexp.MustCompile(`(?i)\bair\s+quality\b|\baqi\b`), "aq"},
}

// chatMetricsOf: every metric word in q, in order ("aq" = the air-quality metrics, "temp" = a temperature of any kind).
func chatMetricsOf(q string) []string {
	type hit struct {
		at int
		m  string
	}
	var hs []hit
	var used [][2]int
	for _, w := range chatMetricWords {
		for _, ix := range w.re.FindAllStringIndex(q, -1) {
			clash := false
			for _, u := range used {
				clash = clash || (ix[0] < u[1] && u[0] < ix[1])
			}
			if !clash {
				used = append(used, [2]int{ix[0], ix[1]})
				hs = append(hs, hit{ix[0], w.metric})
			}
		}
	}
	sort.Slice(hs, func(i, j int) bool { return hs[i].at < hs[j].at })
	// "running" / "chal raha" is an AC's on/off state only when an AC is named ("feeder load kitna chal raha hai" is power)
	acCtx := regexp.MustCompile(`(?i)\b(ac|a/c|acs|hvac|air\s*con\w*|aircon|indoor\s+unit|cooling\s+unit)\b`).MatchString(q)
	var out []string
	for _, h := range hs {
		if h.m == "ac_on" && !acCtx {
			continue
		}
		if !contains(out, h.m) {
			out = append(out, h.m)
		}
	}
	return out
}

var (
	chatLevelWordRe = regexp.MustCompile(`(?i)\b(?:level|floor|lvl)\s*-?\s*(\d{1,2})\b|\b(\d{1,2})(?:st|nd|rd|th)\s+floor\b|\bL(\d{1,2})\b`)
	chatUnitWordRe  = regexp.MustCompile(`(?i)\b(?:unit|sensor|meter|station|room|no\.?|number|#|ac)\s*-?\s*(\d{1,2})\b`)
	chatKindWords   = []struct {
		re   *regexp.Regexp
		loc  string // substring of the node's location text (lower case)
		role string
	}{
		{regexp.MustCompile(`(?i)\b(rooftop|roof|weather\s+station|mausam)\b`), "weather station", "weather"},
		{regexp.MustCompile(`(?i)\boutdoor\s+air\b|\bair\s+station\b`), "outdoor air station", "air_quality"},
		{regexp.MustCompile(`(?i)\b(feeder|substation|11\s*kv|main\s+supply|incomer)\b`), "feeder", "power"},
		{regexp.MustCompile(`(?i)\benergy\s+meter\b|\broom\s+meter\b`), "energy meter", "power"},
		{regexp.MustCompile(`(?i)\bflow\s+meter\b`), "flow meter", "water"},
		{regexp.MustCompile(`(?i)\bwater\s+quality\b|\bquality\s+sensor\b`), "water quality", "water"},
		{regexp.MustCompile(`(?i)\btank\b`), "tank", "water"},
		{regexp.MustCompile(`(?i)\boccupancy\s+sensor\b`), "occupancy sensor", "occupancy"},
		{regexp.MustCompile(`(?i)\b(indoor\s+air|air\s+sensor|classroom|lecture\s+hall|class)\b`), "indoor air sensor", "air_quality"},
		{regexp.MustCompile(`(?i)\b(ac|a/c|air\s*con\w*)\s+(indoor\s+)?unit\b|\bindoor\s+unit\b`), "ac indoor unit", "hvac"},
		{regexp.MustCompile(`(?i)\bac\s+units\b|\ball\s+(the\s+)?acs?\b|\bacs\b|\bevery\s+ac\b`), "ac ", "hvac"},
	}
)

type chatPlace struct {
	Node     string // a node id named or resolved
	Building string
	Level    int // -1 none
	Unit     int // -1 none
	Kinds    []int
	Outdoor  bool
	Words    bool   // the question names a place at all
	Unknown  string // a building code the device has no sensors in ("NB building")
}

// chatPlaceOf: the place words of q.
func chatPlaceOf(q string, buildings []string) chatPlace {
	p := chatPlace{Level: -1, Unit: -1}
	for _, m := range chatNodeRe.FindAllString(q, -1) {
		if !strings.HasPrefix(m, "INC-") {
			p.Node, p.Words = m, true
			return p
		}
	}
	for _, b := range buildings {
		if b != "" && (regexp.MustCompile(`\b`+regexp.QuoteMeta(b)+`\b`).MatchString(q) ||
			regexp.MustCompile(`(?i)\b`+regexp.QuoteMeta(b)+`\s*(building|bldg|block)\b`).MatchString(q)) {
			p.Building, p.Words = b, true
		}
	}
	if p.Building == "" {
		if m := regexp.MustCompile(`\b([A-Z]{2,3})\s*(?:building|bldg|block)\b`).FindStringSubmatch(q); m != nil && !contains(buildings, m[1]) && len(buildings) > 0 {
			p.Unknown, p.Words = m[1], true
		}
	}
	if m := chatLevelWordRe.FindStringSubmatch(q); m != nil {
		p.Level, _ = strconv.Atoi(m[1] + m[2] + m[3])
		p.Words = true
	}
	if m := chatUnitWordRe.FindStringSubmatch(q); m != nil {
		p.Unit, _ = strconv.Atoi(m[1])
		p.Words = true
	}
	// "KH 03 room 15" / "KH 3": a number right after the building is its level
	if p.Building != "" && p.Level < 0 {
		if m := regexp.MustCompile(`\b` + p.Building + `\s*-?\s*(\d{1,2})\b`).FindStringSubmatch(q); m != nil {
			p.Level, _ = strconv.Atoi(m[1])
		}
	}
	for i, k := range chatKindWords {
		if k.re.MatchString(q) {
			p.Kinds = append(p.Kinds, i)
			p.Words = true
		}
	}
	p.Outdoor = regexp.MustCompile(`(?i)\b(outdoor|outside|bahar|ambient|weather)\b`).MatchString(q)
	return p
}

// chatNodeMatch: does node n (its info) fit the place?
func chatNodeMatch(id string, n NodeInfo, p chatPlace) bool {
	if p.Node != "" {
		return id == p.Node
	}
	if p.Building != "" && n.Building != p.Building && !strings.Contains(id, p.Building) {
		return false
	}
	if p.Level >= 0 {
		if lv, err := strconv.Atoi(n.Level); err != nil || lv != p.Level {
			return false
		}
	}
	if p.Unit >= 0 {
		suf, err := strconv.Atoi(id[strings.LastIndex(id, "-")+1:])
		if err != nil || suf != p.Unit {
			return false
		}
	}
	loc := strings.ToLower(n.Location)
	for _, k := range p.Kinds {
		if !strings.Contains(loc, chatKindWords[k].loc) {
			return false
		}
	}
	return true
}

// chatResolveMetric: the metric a word means on one node (a temperature on an AC is room_temp, "aq" = its AQ metrics).
func chatResolveMetric(word string, have []string) []string {
	switch word {
	case "temp":
		if contains(have, "temp") {
			return []string{"temp"}
		}
		if contains(have, "room_temp") {
			return []string{"room_temp"}
		}
		return nil
	case "aq":
		var out []string
		for _, m := range []string{"co2", "pm25", "pm10"} {
			if contains(have, m) {
				out = append(out, m)
			}
		}
		return out
	case "wq":
		var out []string
		for _, m := range []string{"ph", "tds"} {
			if contains(have, m) {
				out = append(out, m)
			}
		}
		return out
	case "ac_on":
		if contains(have, "ac_on") {
			return []string{"ac_on"}
		}
		if contains(have, "ac_units_on") {
			return []string{"ac_units_on"}
		}
		return nil
	}
	if contains(have, word) {
		return []string{word}
	}
	return nil
}

type chatSensorPick struct {
	Node, Metric string
}

// chatPickSensors: the (node, metric) pairs q asks about. missing: metric words no sensor at the place measures.
// nodes: device nodes; metrics: chatMetricsOf(q).
func chatPickSensors(p chatPlace, metrics []string, dom string, nodes map[string]NodeInfo) (out []chatSensorPick, missing []string) {
	var ids []string
	for id := range nodes {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	var cand []string
	match := func(p chatPlace) {
		for _, id := range ids {
			n := nodes[id]
			if !chatNodeMatch(id, n, p) {
				continue
			}
			if dom != "" && n.Role != dom && !(dom == "weather" && p.Outdoor) {
				continue
			}
			cand = append(cand, id)
		}
	}
	// the place without its kind words: "tank" names the level sensor, but "flow aur tank level" also asks for flow
	var wide []string
	if len(p.Kinds) > 0 && p.Node == "" {
		q := p
		q.Kinds = nil
		if q.Building != "" || q.Level >= 0 || q.Unit >= 0 || len(metrics) > 0 {
			match(q)
			wide, cand = cand, nil
		}
	}
	match(p)
	if len(cand) == 0 && len(wide) > 0 && (p.Building != "" || p.Level >= 0 || p.Unit >= 0) {
		cand = wide // "energy meter in SB" is the SB feeder meter
	}
	// outdoor words: the outdoor sensors (weather station, outdoor air station) for the metrics they measure; a metric
	// no outdoor sensor has ("hot outside - is power demand going up?") keeps every sensor of the place
	var outd []string
	if p.Outdoor && p.Node == "" {
		for _, id := range cand {
			l := strings.ToLower(nodes[id].Location)
			if strings.Contains(l, "outdoor") || strings.Contains(l, "weather") || nodes[id].Role == "weather" {
				outd = append(outd, id)
			}
		}
		if len(metrics) == 0 {
			cand = outd
		}
	}
	if len(metrics) == 0 {
		if !p.Words || len(cand) > 3 {
			return nil, nil
		}
		for _, id := range cand {
			for _, m := range nodes[id].Metrics {
				out = append(out, chatSensorPick{id, m})
			}
		}
		return out, nil
	}
	for _, w := range metrics {
		found := false
		use := cand
		if len(wide) > 0 {
			ok := false
			for _, id := range cand {
				ok = ok || len(chatResolveMetric(w, nodes[id].Metrics)) > 0
			}
			if !ok {
				use = wide
			}
		}
		for _, id := range outd {
			if len(chatResolveMetric(w, nodes[id].Metrics)) > 0 {
				use = outd
				break
			}
		}
		for _, id := range use {
			for _, m := range chatResolveMetric(w, nodes[id].Metrics) {
				// an AC unit's own room temperature is the answer to "temperature on level 3", the level's
				// AC group (AC-KH03) and air sensor too: keep all, the answer names each
				out = append(out, chatSensorPick{id, m})
				found = true
			}
		}
		if !found {
			missing = append(missing, w)
		}
	}
	// "temperature" of a room with an air sensor and AC units: prefer what the words name (AC words -> AC sensors)
	return chatDedupPicks(out), missing
}

func chatDedupPicks(ps []chatSensorPick) []chatSensorPick {
	seen := map[string]bool{}
	var out []chatSensorPick
	for _, p := range ps {
		k := p.Node + "|" + p.Metric
		if !seen[k] {
			seen[k] = true
			out = append(out, p)
		}
	}
	return out
}

// ---------------------------------------------------------------- referents

// chatRef: what an earlier answer was about.
type chatRef struct {
	Kind    string         // "set" (incidents matching Filter), "incident" (ID), "sensors" (Picks)
	Filter  map[string]any // count/find arguments, time as from/to or preset
	When    string
	ID      string
	IDs     []string
	Picks   []chatSensorPick
	Place   string // node or place words of the sensors answer
	Tool    string
	Answer  string
	History int // index of the assistant message in history
}

// chatRefOf: the referent of the newest assistant answer that has one (looks back two answers).
func chatRefOf(history []ChatMsg) *chatRef {
	seen := 0
	for i := len(history) - 1; i >= 0 && seen < 2; i-- {
		m := history[i]
		if m.Role != "assistant" || m.Busy {
			continue
		}
		seen++
		if r := chatRefOfMsg(m); r != nil {
			r.History = i
			return r
		}
	}
	return nil
}

func chatRefOfMsg(m ChatMsg) *chatRef {
	ids := chatIDs(m.Text)
	for j := len(m.Tools) - 1; j >= 0; j-- {
		tl := m.Tools[j]
		var args map[string]any
		if json.Unmarshal([]byte(tl.Args), &args) != nil {
			continue
		}
		switch tl.Name {
		case "count_incidents", "find_incidents", "recent_incidents":
			f := chatCopyArgs(args)
			delete(f, "group_by")
			delete(f, "limit")
			r := &chatRef{Kind: "set", Filter: f, IDs: ids, Tool: tl.Name, Answer: m.Text}
			if tl.Name == "recent_incidents" {
				r.Kind = "list"
			}
			if len(ids) == 1 && tl.Name != "count_incidents" {
				r.ID = ids[0]
			}
			return r
		case "get_incident":
			id, _ := args["id"].(string)
			if id == "" && len(ids) == 1 {
				id = ids[0]
			}
			return &chatRef{Kind: "incident", ID: strings.ToUpper(id), IDs: ids, Tool: tl.Name, Answer: m.Text}
		case "open_incidents":
			if len(ids) == 1 {
				return &chatRef{Kind: "incident", ID: ids[0], IDs: ids, Tool: tl.Name, Answer: m.Text}
			}
			return &chatRef{Kind: "set", Filter: map[string]any{"workflow": wfNeeds}, IDs: ids, Tool: tl.Name, Answer: m.Text}
		case "current_levels", "get_sensor_history":
			r := &chatRef{Kind: "sensors", Tool: tl.Name, Answer: m.Text}
			if ps, ok := args["_picks"].([]any); ok {
				for _, x := range ps {
					if s, ok := x.(string); ok {
						if k := strings.SplitN(s, "|", 2); len(k) == 2 {
							r.Picks = append(r.Picks, chatSensorPick{k[0], k[1]})
						}
					}
				}
			}
			node, _ := args["node"].(string)
			metric, _ := args["metric"].(string)
			if len(r.Picks) == 0 && node != "" && metric != "" {
				r.Picks = []chatSensorPick{{node, metric}}
			}
			if loc, _ := args["location"].(string); loc != "" {
				r.Place = loc
			}
			if node != "" {
				r.Place = node
			}
			if len(r.Picks) > 0 || r.Place != "" {
				return r
			}
		}
	}
	if len(ids) == 1 {
		return &chatRef{Kind: "incident", ID: ids[0], IDs: ids, Answer: m.Text}
	}
	return nil
}

// chatIsFollowUp: q leans on the previous answer (pronoun, "and ...", or a short question without its own subject).
func chatIsFollowUp(q string, p chatPlace, metrics []string, span chatSpan) bool {
	if chatBackRefRe.MatchString(q) || chatFollowStRe.MatchString(q) {
		return true
	}
	return len(strings.Fields(q)) <= 4 && !p.Words && !span.Found()
}

// ---------------------------------------------------------------- the v25 router

type chatV25 struct {
	Text  string
	Tools []ChatTool
}

func chatToolRec(name string, args, res map[string]any) ChatTool {
	a, _ := json.Marshal(args)
	r, _ := json.Marshal(res)
	return ChatTool{Name: name, Args: string(a), Result: string(r)}
}

func (t chatTools) chatBuildings() []string {
	var out []string
	if t.r == nil || t.r.eng == nil {
		return out
	}
	seen := map[string]bool{}
	for _, n := range t.r.eng.Meta.Nodes {
		if n.Building != "" && !seen[n.Building] {
			seen[n.Building] = true
			out = append(out, n.Building)
		}
	}
	sort.Strings(out)
	return out
}

// chatRouteV25: answers q when its type is clear; ok false = the older routes / the model answer.
func (t chatTools) chatRouteV25(q string, history []ChatMsg) (chatV25, bool) {
	if t.r == nil {
		return chatV25{}, false
	}
	nodes := map[string]NodeInfo{}
	if t.r.eng != nil {
		nodes = t.r.eng.Meta.Nodes
	}
	place := chatPlaceOf(q, t.chatBuildings())
	metrics := chatMetricsOf(q)
	span := chatSpanOf(q, t.now)
	dom := chatDomainOf(q)
	if dom == "" && regexp.MustCompile(`(?i)\b(water|pani)\b`).MatchString(q) {
		dom = "water"
	}
	picks, missing := chatPickSensors(place, metrics, "", nodes)
	var sensorIDs []string
	for _, p := range picks {
		sensorIDs = append(sensorIDs, p.Node)
	}
	ref := chatRefOf(history)
	follow := ref != nil && chatIsFollowUp(q, place, metrics, span)
	intent := chatIntentOf(q, span, sensorIDs, metrics, follow || ref != nil)

	switch intent {
	case intInject:
		res, _ := t.run("open_incidents", map[string]any{})
		text := "I can't do that: I don't change my rules, switch modes or show my instructions, and my tools only read the device's data. " +
			"Changing thresholds, devices or incidents needs an operator on the dashboard."
		return chatV25{text, []ChatTool{chatToolRec("open_incidents", map[string]any{}, res)}}, true
	case intAction:
		if regexp.MustCompile(`(?i)^\s*(please\s+|pls\s+|can\s+you\s+|could\s+you\s+)?(book|schedule|order|send|email|call|reserve|cancel)\b`).MatchString(q) &&
			!regexp.MustCompile(`(?i)\b(sensors?|incidents?|inc-?\d+|alerts?|alarms?|ac|a/c|hvac|setpoint|valve|pumps?|thresholds?|devices?|meters?|units?|power|water|tanks?|readings?|data|maintenance)\b`).MatchString(q) {
			return chatV25{"That's outside what I can do: I only answer questions about the campus monitoring data on this device (sensors, readings and incidents), and I cannot book, send or schedule anything.", nil}, true
		}
		res, _ := t.run("open_incidents", map[string]any{})
		text := "I can't do that: my tools only read the device's data, so I cannot change a device, a setpoint, a threshold or an incident. An operator has to do it."
		if total, _ := res["total_pending_review"].(int); total > 0 && chatIncWordRe.MatchString(q) {
			text += fmt.Sprintf(" %s waiting for a decision; open each one under Incidents and approve or dismiss it there.", plural(total, "incident is", "incidents are"))
		}
		if len(picks) > 0 && t.r.eng != nil {
			if s := t.chatReadingLine(picks[0]); s != "" {
				text += " For reference, " + s + "."
			}
		}
		return chatV25{text, []ChatTool{chatToolRec("open_incidents", map[string]any{}, res)}}, true
	case intOOS:
		return chatV25{"Sorry, that's outside what I can help with: I only answer questions about the campus monitoring system on this device (sensor readings, incidents, alerts and sensor health).", nil}, true
	case intFuture:
		text := "I can't see the future: the device only stores past readings and incidents, and it has no forecast."
		var tools []ChatTool
		if len(picks) == 0 && (dom == "weather" || place.Outdoor) {
			picks, _ = chatPickSensors(chatPlace{Level: -1, Unit: -1, Kinds: []int{0}, Words: true}, metrics, "", nodes)
		}
		if len(picks) > 0 {
			if v, tl := t.chatValues(picks[:min(4, len(picks))], false); v != "" {
				text += " The latest readings: " + v
				tools = append(tools, tl)
			}
		}
		return chatV25{text, tools}, true
	case intScenario:
		return t.chatScenario(q, place, metrics, dom, nodes)
	}
	if r, ok := t.chatExplain(q, metrics, nodes); ok {
		return r, true
	}
	// one incident: its status / who approved it ("INC-0620 ka status kya hai, kisi ne approve kiya?")
	if ids := chatIDs(q); len(ids) == 1 && (chatWhoRe.MatchString(q) || regexp.MustCompile(`(?i)\bapprov\w*|\bdismiss\w*`).MatchString(q)) {
		return t.chatIncidentFacts(ids[0], q), true
	}
	// "if we switch off 5 of the AC units on level 3, what happens to the room temperature?": the fitted what_if
	if chatWhatIfV25Re.MatchString(q) {
		if r, ok := t.chatWhatIfUnits(q, place, nodes); ok {
			return r, true
		}
	}
	// "what if PM2.5 goes to 180": a target value of a metric with alert limits -> what the device would do at it
	if chatWhatIfV25Re.MatchString(q) {
		if r, ok := t.chatWhatIfLimit(q, place, metrics, nodes); ok {
			return r, true
		}
	}

	if place.Unknown != "" && intent != intModel {
		return chatV25{fmt.Sprintf("This device has no sensors in the %s building, so I have no readings or incidents for it. Buildings with sensors: %s.",
			place.Unknown, strings.Join(t.chatBuildings(), ", ")), nil}, true
	}
	// follow-ups keep the previous answer's referent
	if follow {
		if r, ok := t.chatFollowV25(q, ref, place, metrics, span, dom, nodes, intent); ok {
			return r, true
		}
	}
	switch intent {
	case intHealth:
		if len(picks) > 0 {
			return t.chatHealth(picks), true
		}
	case intValue:
		if len(missing) > 0 && len(picks) == 0 && place.Words {
			return t.chatMissing(place, missing, nodes), true
		}
		if len(picks) == 0 {
			return chatV25{}, false
		}
		if span.Found() && (chatTrendRe.MatchString(q) || span.From.Before(t.now.Add(-30*time.Minute))) {
			return t.chatHistory(picks, span), true
		}
		if span.Unparsed != "" {
			return chatV25{}, false // a period we cannot read: the model, with the note (chatGuard)
		}
		if regexp.MustCompile(`(?i)\b(trend|trending|rising|falling|going\s+up|going\s+down|changing|history|graph|plot)\b`).MatchString(q) {
			return t.chatHistory(picks, chatSpan{From: t.now.Add(-24 * time.Hour), To: t.now, Words: "in the last 24 hours"}), true
		}
		text, tl := t.chatValues(picks, true)
		if text == "" {
			return chatV25{}, false
		}
		text += t.chatJudge(q, picks)
		// "any sign of a leak?": the last 24 h of those readings too, so a drift shows
		if regexp.MustCompile(`(?i)\b(signs?|leak\w*|overflow\w*|drain\w*|dropping|rising)\b`).MatchString(q) {
			h := t.chatHistory(picks, chatSpan{From: t.now.Add(-24 * time.Hour), To: t.now, Words: "in the last 24 hours", now: t.now})
			text += " " + h.Text
			return chatV25{text, append([]ChatTool{tl}, h.Tools...)}, true
		}
		if len(missing) > 0 {
			text += " " + t.chatMissing(place, missing, nodes).Text
		}
		return chatV25{text, []ChatTool{tl}}, true
	case intIncident:
		return t.chatIncidents(q, place, metrics, span, dom, nodes, nil)
	}
	return chatV25{}, false
}

// chatFollowV25: a follow-up on the previous answer's referent.
func (t chatTools) chatFollowV25(q string, ref *chatRef, place chatPlace, metrics []string, span chatSpan, dom string, nodes map[string]NodeInfo, intent string) (chatV25, bool) {
	switch ref.Kind {
	case "incident":
		if ref.ID == "" {
			return chatV25{}, false
		}
		if chatHowLongRe.MatchString(q) || chatWhoRe.MatchString(q) {
			return t.chatIncidentFacts(ref.ID, q), true
		}
		return chatV25{}, false // the deploy23 incident follow-ups (why / real / what to do)
	case "set", "list":
		// "why did it happen?" after an answer naming one incident: that incident (the deploy23 follow-ups)
		if ref.ID != "" && regexp.MustCompile(`(?i)\b(it|this|that|this\s+one|that\s+one|iska|isko|uska|usko)\b`).MatchString(q) &&
			!regexp.MustCompile(`(?i)\b(those|them|these|they|unme|inme)\b`).MatchString(q) {
			if chatHowLongRe.MatchString(q) || chatWhoRe.MatchString(q) {
				return t.chatIncidentFacts(ref.ID, q), true
			}
			return chatV25{}, false
		}
		if ref.Kind == "list" && !chatBackRefRe.MatchString(q) {
			return chatV25{}, false
		}
		count := ref.Tool == "count_incidents" && !regexp.MustCompile(`(?i)\b(which|list|show|what\s+were|name)\b`).MatchString(q)
		if place.Words && len(metrics) > 0 && intent == intValue {
			return chatV25{}, false
		}
		f := chatCopyArgs(ref.Filter)
		if ref.Kind == "list" {
			f = map[string]any{"_ids": ref.IDs}
		}
		if chatOpenRe.MatchString(q) || chatPendRe.MatchString(q) || regexp.MustCompile(`(?i)\b(unresolved|not\s+(yet\s+)?resolved|sitting|abhi\s+bhi|ab\s+bhi)\b`).MatchString(q) {
			f["workflow"] = wfNeeds
		}
		if s := chatSeverities(q); len(s) > 0 {
			f["severity"] = s
		}
		if d := chatDomainOf(q); d != "" {
			f["domain"] = d
			delete(f, "metric")
		}
		if span.Found() {
			f["time"] = span.Args()
		}
		if chatHowLongRe.MatchString(q) && ref.ID != "" {
			return t.chatIncidentFacts(ref.ID, q), true
		}
		if count {
			f["_count"] = true
		}
		return t.chatIncidents(q, place, metrics, span, dom, nodes, f)
	case "sensors":
		picks := ref.Picks
		if len(metrics) > 0 {
			// the same place, another metric ("what about the humidity in that room")
			var np []chatSensorPick
			var miss []string
			pl := chatPlace{Level: -1, Unit: -1, Words: true}
			if len(ref.Picks) > 0 {
				n := nodes[ref.Picks[0].Node]
				pl.Building = n.Building
				if lv, err := strconv.Atoi(n.Level); err == nil {
					pl.Level = lv
				}
			}
			if place.Words {
				pl = place
			}
			np, miss = chatPickSensors(pl, metrics, "", nodes)
			if len(np) == 0 {
				return t.chatMissing(pl, miss, nodes), true
			}
			picks = np
		}
		if len(picks) == 0 {
			return chatV25{}, false
		}
		if intent == intIncident && !regexp.MustCompile(`(?i)\b(normal|high|low|ok|okay|theek|fine)\b`).MatchString(q) {
			// "any alerts on it?": incidents of the referred sensors
			f := map[string]any{"node": picks[0].Node}
			return t.chatIncidents(q, place, metrics, span, dom, nodes, f)
		}
		if intent == intHealth || chatHealthQRe.MatchString(q) {
			return t.chatHealth(picks), true
		}
		if span.Found() {
			return t.chatHistory(picks, span), true
		}
		if regexp.MustCompile(`(?i)\b(ago|pehle|earlier|before|was\s+it|same)\b`).MatchString(q) {
			return chatV25{}, false // an unread earlier time: the model
		}
		text, tl := t.chatValues(picks, true)
		if text == "" {
			return chatV25{}, false
		}
		// "then should the AC be on there?" after an occupancy answer: the judge also sees that occupancy reading
		judge := append([]chatSensorPick(nil), picks...)
		for _, p := range ref.Picks {
			if p.Metric == "occ" && !contains(metrics, "occ") {
				judge = append(judge, p)
			}
		}
		return chatV25{text + t.chatJudge(q, judge), []ChatTool{tl}}, true
	}
	return chatV25{}, false
}

// ---------------------------------------------------------------- readings answers

func (t chatTools) chatState(node, metric string) *SensorState {
	if t.r.eng == nil {
		return nil
	}
	_, states, _ := t.r.eng.Snapshot()
	for i := range states {
		if states[i].Node == node && states[i].Metric == metric {
			s := states[i]
			return &s
		}
	}
	return nil
}

// chatValueWord: a reading in words (an AC's on/off, a room's occupied/empty, others value + unit).
func chatValueWord(metric string, v float64, unit string) string {
	switch metric {
	case "ac_on":
		if v >= 0.5 {
			return "on"
		}
		return "off"
	case "occ":
		if v >= 0.5 {
			return "occupied"
		}
		return "empty (no one detected)"
	case "ac_units_on":
		return plural(int(math.Round(v)), "unit on", "units on")
	}
	return chatNum(chatRound(metric, v), unit)
}

// chatReadingLine: "CO2 at KH building, level 03, indoor air sensor 03 (SR-AQ-KH03-03): 438 ppm (normal; warning at 1000)".
func (t chatTools) chatReadingLine(p chatSensorPick) string {
	s := t.chatState(p.Node, p.Metric)
	if s == nil {
		return ""
	}
	name := chatMetricName(p.Metric)
	if p.Metric != "ph" && p.Metric != "pf" {
		name = strings.ToUpper(name[:1]) + name[1:]
	}
	line := fmt.Sprintf("%s at %s (%s): ", name, s.Location, s.Node)
	if s.Last == nil {
		// the newest stored reading (the live value is set at the next poll)
		if xs := t.r.eng.HistoryAt(p.Node, p.Metric, t.now.Unix()/bucketSec*bucketSec, 288); len(xs) > 0 {
			v := xs[len(xs)-1]
			s.Last = &v
		} else {
			return line + "no reading yet"
		}
	}
	faults := t.chatFaultsNow(t.incidents())
	st := chatLiveStatus(*s, faults)
	line += chatValueWord(p.Metric, *s.Last, s.Unit)
	if s.Updated > 0 {
		line += " (reading of " + chatTS(time.Unix(s.Updated, 0)) + ")"
	}
	switch {
	case st == "sensor_fault":
		line += ", but this sensor is flagged as faulty, so the value may not be real"
	case s.Quality == "stale":
		why := s.QualityWhy
		if why == "" {
			why = "no new readings"
		}
		line += fmt.Sprintf(", but the sensor is silent (%s), so this is the last value it sent", why)
	}
	if m, ok := Metrics[s.Role+"/"+s.Metric]; ok && m.HasLimits {
		dir := "above"
		if m.Dir == "low" {
			dir = "below"
		}
		if st == "sensor_fault" {
			line += fmt.Sprintf(" (alert limits: %s %s warning, %s critical)", dir, chatNum(m.Warn, s.Unit), chatNum(m.Crit, s.Unit))
		} else {
			line += fmt.Sprintf("; status %s (alerts %s %s warning, %s critical)", chatSevName(st), dir, chatNum(m.Warn, s.Unit), chatNum(m.Crit, s.Unit))
		}
	} else if p.Metric != "ac_on" && p.Metric != "occ" && p.Metric != "setpoint" && p.Metric != "ac_units_on" {
		line += "; no fixed alert limit for this metric (the device alerts on unusual patterns)"
	}
	return line
}

// chatValues: the current reading of each pick (at most 6), with today's range when asked "normal or high".
func (t chatTools) chatValues(picks []chatSensorPick, withRange bool) (string, ChatTool) {
	if len(picks) > 6 {
		picks = picks[:6]
	}
	var lines []string
	var keys []any
	items := []map[string]any{}
	for _, p := range picks {
		l := t.chatReadingLine(p)
		if l == "" {
			continue
		}
		res, err := t.run("current_levels", map[string]any{"metric": p.Metric, "location": p.Node})
		if err == nil {
			if it, _ := res["items"].([]map[string]any); len(it) > 0 {
				for _, x := range it {
					if x["node"] == p.Node {
						items = append(items, x)
						if td, ok := x["today"].(map[string]any); ok && withRange && p.Metric != "ac_on" && p.Metric != "occ" {
							s := t.chatState(p.Node, p.Metric)
							l += fmt.Sprintf("; today %s to %s (mean %s)", chatNum(td["min"], ""), chatNum(td["max"], s.Unit), chatNum(td["mean"], s.Unit))
						}
					}
				}
			}
		}
		lines = append(lines, l)
		keys = append(keys, p.Node+"|"+p.Metric)
	}
	if len(lines) == 0 {
		return "", ChatTool{}
	}
	args := map[string]any{"_picks": keys}
	if len(picks) > 0 {
		args["location"] = picks[0].Node
		args["metric"] = picks[0].Metric
	}
	return strings.Join(lines, ". ") + ".", chatToolRec("current_levels", args, map[string]any{"items": items})
}

// chatMissing: the place has no sensor of the metric asked; name where that metric is measured.
func (t chatTools) chatMissing(p chatPlace, missing []string, nodes map[string]NodeInfo) chatV25 {
	var parts []string
	var tools []ChatTool
	for _, w := range missing {
		name := chatMetricName(w)
		if w == "aq" {
			name = "air quality"
		} else if w == "wq" {
			name = "water quality"
		}
		where := chatPlaceWords(p)
		elsewhere, _ := chatPickSensors(chatPlace{Level: -1, Unit: -1}, []string{w}, "", nodes)
		if len(elsewhere) == 0 {
			parts = append(parts, fmt.Sprintf("No sensor on this device measures %s.", name))
			continue
		}
		s := fmt.Sprintf("There is no %s sensor %s.", name, where)
		if len(elsewhere) <= 3 {
			v, tl := t.chatValues(elsewhere, false)
			if v != "" {
				s += " The device measures it here: " + v
				tools = append(tools, tl)
			}
		}
		parts = append(parts, s)
	}
	return chatV25{strings.Join(parts, " "), tools}
}

func chatPlaceWords(p chatPlace) string {
	if p.Node != "" {
		return "on " + p.Node
	}
	var w []string
	if p.Building != "" {
		w = append(w, p.Building+" building")
	}
	if p.Level >= 0 {
		w = append(w, fmt.Sprintf("level %d", p.Level))
	}
	if p.Unit >= 0 {
		w = append(w, fmt.Sprintf("unit %d", p.Unit))
	}
	if len(w) == 0 {
		return "at that place"
	}
	return "at " + strings.Join(w, ", ")
}

// chatHistory: readings of each pick over a past span (start, end, min, max, mean, direction).
func (t chatTools) chatHistory(picks []chatSensorPick, sp chatSpan) chatV25 {
	if len(picks) > 4 {
		picks = picks[:4]
	}
	var lines []string
	var tools []ChatTool
	for _, p := range picks {
		args := map[string]any{"node": p.Node, "metric": p.Metric, "time": sp.Args()}
		res, err := t.run("get_sensor_history", args)
		if err != nil {
			lines = append(lines, fmt.Sprintf("%s %s: %v", p.Node, chatMetricName(p.Metric), err))
			continue
		}
		args["_picks"] = []any{p.Node + "|" + p.Metric}
		tools = append(tools, chatToolRec("get_sensor_history", args, res))
		s := t.chatState(p.Node, p.Metric)
		end, n := t.chatWindow(sp.From, sp.To)
		var xs []float64
		if n > 0 {
			xs = t.r.eng.HistoryAt(p.Node, p.Metric, end, n)
		}
		name := chatMetricName(p.Metric)
		if len(xs) == 0 {
			l := fmt.Sprintf("No %s readings from %s are stored %s", name, p.Node, sp.Describe())
			if s.Quality == "stale" && s.Last != nil {
				l += fmt.Sprintf(": the sensor is silent, its last value was %s", chatValueWord(p.Metric, *s.Last, s.Unit))
				if s.Updated > 0 {
					l += " (" + chatTS(time.Unix(s.Updated, 0)) + ")"
				}
			}
			lines = append(lines, l)
			continue
		}
		mn, mx, sum := xs[0], xs[0], 0.0
		for _, x := range xs {
			mn, mx, sum = math.Min(mn, x), math.Max(mx, x), sum+x
		}
		first, last := xs[0], xs[len(xs)-1]
		unit := s.Unit
		d := last - first
		dir := "stayed about the same"
		if span := mx - mn; span > 0 && math.Abs(d) > 0.2*span && math.Abs(d) > 1e-9 {
			if d > 0 {
				dir = "rose"
			} else {
				dir = "fell"
			}
		}
		if p.Metric == "ac_on" || p.Metric == "occ" {
			on := 0
			for _, x := range xs {
				if x >= 0.5 {
					on++
				}
			}
			lines = append(lines, fmt.Sprintf("%s at %s %s: %s in %d of %d readings; now %s", strings.ToUpper(name[:1])+name[1:], s.Location, sp.Describe(),
				map[string]string{"ac_on": "on", "occ": "occupied"}[p.Metric], on, len(xs), chatValueWord(p.Metric, last, unit)))
			continue
		}
		lines = append(lines, fmt.Sprintf("%s at %s (%s) %s: %s from %s to %s (min %s, max %s, mean %s; %d readings)", strings.ToUpper(name[:1])+name[1:], s.Location, p.Node,
			sp.Describe(), dir, chatNum(chatRound(p.Metric, first), unit), chatNum(chatRound(p.Metric, last), unit), chatNum(chatRound(p.Metric, mn), unit),
			chatNum(chatRound(p.Metric, mx), unit), chatNum(chatRound(p.Metric, sum/float64(len(xs))), unit), len(xs)))
	}
	return chatV25{strings.Join(lines, ". ") + ".", tools}
}

// chatHealth: is a sensor working? live fault flag, silence, the latest reading and its recent sensor-fault incidents.
func (t chatTools) chatHealth(picks []chatSensorPick) chatV25 {
	if len(picks) > 4 {
		picks = picks[:4]
	}
	faults := t.chatFaultsNow(t.incidents())
	a := t.now.Add(-7 * 24 * time.Hour)
	var lines []string
	var tools []ChatTool
	for _, p := range picks {
		s := t.chatState(p.Node, p.Metric)
		if s == nil {
			continue
		}
		name := chatMetricName(p.Metric)
		st := chatLiveStatus(*s, faults)
		var l string
		switch {
		case st == "sensor_fault":
			l = fmt.Sprintf("The %s sensor %s (%s) is flagged as faulty right now", name, p.Node, s.Location)
		case s.Quality == "stale":
			why := s.QualityWhy
			if why == "" {
				why = "no new readings"
			}
			l = fmt.Sprintf("The %s sensor %s (%s) is not flagged as faulty, but it is silent (%s): it is not sending new readings", name, p.Node, s.Location, why)
		case s.Last == nil:
			l = fmt.Sprintf("The %s sensor %s (%s) has no reading yet", name, p.Node, s.Location)
		default:
			l = fmt.Sprintf("The %s sensor %s (%s) looks healthy: no live fault and its readings are arriving", name, p.Node, s.Location)
		}
		if s.Last != nil {
			l += "; last value " + chatValueWord(p.Metric, *s.Last, s.Unit)
		}
		args := map[string]any{"node": p.Node, "metric": p.Metric, "time": map[string]any{"from": a.In(IST).Format("2006-01-02T15:04"), "to": t.now.Add(time.Minute).In(IST).Format("2006-01-02T15:04")}}
		res, err := t.run("find_incidents", chatCopyArgs(map[string]any{"node": p.Node, "metric": p.Metric, "time": args["time"], "severity": []any{"sensor_fault"}, "limit": 3.0}))
		if err == nil {
			tools = append(tools, chatToolRec("find_incidents", map[string]any{"node": p.Node, "metric": p.Metric, "time": args["time"], "severity": []any{"sensor_fault"}, "_picks": []any{p.Node + "|" + p.Metric}}, res))
			total, _ := res["total"].(int)
			if total == 0 {
				l += ". No sensor-fault incident for it in the last 7 days"
			} else {
				items, _ := res["items"].([]map[string]any)
				l += fmt.Sprintf(". %s in the last 7 days, newest [%s] (%s)", plural(total, "sensor-fault incident", "sensor-fault incidents"), items[0]["id"], items[0]["time"])
			}
		}
		lines = append(lines, l)
	}
	if len(lines) == 0 {
		return chatV25{}
	}
	return chatV25{strings.Join(lines, ". ") + ".", tools}
}

// ---------------------------------------------------------------- incidents answers

// chatIncFilter: the find/count filter for q (pre: a follow-up's inherited filter).
func (t chatTools) chatIncFilter(q string, place chatPlace, metrics []string, span chatSpan, dom string, nodes map[string]NodeInfo, pre map[string]any) (map[string]any, string, bool) {
	f := map[string]any{}
	if pre != nil {
		f = chatCopyArgs(pre)
	}
	if pre == nil || span.Found() {
		switch {
		case span.Found():
			f["time"] = span.Args()
		case span.Unparsed != "":
			return nil, "", false // a period we cannot read: never answer for another one
		}
	}
	if pre == nil {
		if d := dom; d != "" {
			f["domain"] = d
		}
		if s := chatSeverities(q); len(s) > 0 {
			f["severity"] = s
		}
		if place.Words {
			picks, _ := chatPickSensors(place, nil, "", nodes)
			ids := map[string]bool{}
			for _, p := range picks {
				ids[p.Node] = true
			}
			switch {
			case place.Node != "":
				f["node"] = place.Node
			case len(ids) == 1:
				for id := range ids {
					f["node"] = id
				}
			case place.Building != "" && place.Level >= 0:
				f["node"] = fmt.Sprintf("%s%02d", place.Building, place.Level)
			case place.Building != "":
				f["node"] = place.Building
			case len(ids) > 1:
				// several nodes of one kind (e.g. the AC units): their common domain
				if d := chatCommonRole(ids, nodes); d != "" && f["domain"] == nil {
					f["domain"] = d
				}
			}
		}
		if f["domain"] == nil && f["node"] == nil {
			for _, m := range metrics {
				if m == "aq" {
					f["domain"] = "air_quality"
					break
				}
				if m == "wq" {
					f["domain"] = "water"
					break
				}
				if m != "temp" && contains(chatMetricEnum, m) {
					f["metric"] = m
					break
				}
			}
		}
		if f["node"] != nil {
			delete(f, "domain") // the node says where ("outdoor air station" is not the weather domain)
		}
		if f["node"] != nil && len(metrics) == 1 && metrics[0] != "temp" && metrics[0] != "aq" && metrics[0] != "wq" && contains(chatMetricEnum, metrics[0]) {
			f["metric"] = metrics[0]
		}
		if regexp.MustCompile(`(?i)\bdismiss\w*|\bfalse\s+alarms?\b`).MatchString(q) {
			f["approval"] = "dismissed"
		} else if regexp.MustCompile(`(?i)\bapproved\b`).MatchString(q) {
			f["approval"] = "approved"
		} else if chatOpenRe.MatchString(q) || regexp.MustCompile(`(?i)\bunresolved\b`).MatchString(q) {
			f["workflow"] = wfNeeds
		}
	}
	if f["time"] == nil {
		if pre != nil {
			return f, "", true
		}
		return nil, "", false
	}
	if span.Found() && (pre == nil || f["time"] != nil) {
		if tv, ok := f["time"].(map[string]any); ok && tv["from"] == span.Args()["from"] {
			return f, span.Describe(), true
		}
	}
	return f, chatSpanWords(t, f), true
}

func chatCommonRole(ids map[string]bool, nodes map[string]NodeInfo) string {
	r := ""
	for id := range ids {
		if r != "" && nodes[id].Role != r {
			return ""
		}
		r = nodes[id].Role
	}
	return r
}

// chatSpanWords: the period of a filter in words with its from/to.
func chatSpanWords(t chatTools, f map[string]any) string {
	tv, _ := f["time"].(map[string]any)
	if tv == nil {
		return "on this device"
	}
	a, b, err := t.span(tv, true)
	if err != nil {
		return ""
	}
	if b.After(t.now) && t.now.After(a) {
		b = t.now
	}
	if p, _ := tv["preset"].(string); p != "" {
		w := chatPeriodWords[p]
		if w == "" {
			w = strings.ReplaceAll(p, "_", " ")
		}
		return fmt.Sprintf("%s (%s to %s)", w, chatTS(a), chatTS(b))
	}
	return fmt.Sprintf("from %s to %s", chatTS(a), chatTS(b))
}

// chatIncidents: incidents over a span (count / list / exists / per group / longest waiting / worst).
func (t chatTools) chatIncidents(q string, place chatPlace, metrics []string, span chatSpan, dom string, nodes map[string]NodeInfo, pre map[string]any) (chatV25, bool) {
	var ids []string
	forceCount := false
	prevGroup := "" // the grouping of the answer a follow-up refers to ("what about the one with the fewest")
	if pre != nil {
		pre = chatCopyArgs(pre)
		prevGroup, _ = pre["_group"].(string)
		delete(pre, "_group")
		if x, ok := pre["_ids"].([]string); ok {
			ids = x
			if ids == nil {
				ids = []string{}
			}
		}
		forceCount, _ = pre["_count"].(bool)
		delete(pre, "_ids")
		delete(pre, "_count")
	}
	f, when, ok := t.chatIncFilter(q, place, metrics, span, dom, nodes, pre)
	if !ok {
		// no period: the longest-waiting / worst pending incident needs none
		if chatOldestRe.MatchString(q) && (chatOpenRe.MatchString(q) || chatPendRe.MatchString(q)) {
			f = map[string]any{"workflow": wfNeeds}
			if dom != "" {
				f["domain"] = dom
			}
			when = "on this device"
		} else {
			return chatV25{}, false
		}
	}
	if when == "" {
		when = chatSpanWords(t, f)
	}
	// a summary of a period read here ("this week" = since Monday, not the last 7 days): the deploy24 summary answer
	if pre == nil && chatSummaryRe.MatchString(q) && span.Found() && !chatCountQRe.MatchString(q) {
		args := map[string]any{"time": span.Args()}
		if dom != "" {
			args["domain"] = dom
		}
		rt := chatRoute{Tool: "count_incidents", Args: args, Act: "summary", When: span.Describe()}
		if res, err := t.chatSummary(args); err == nil {
			return chatV25{chatSayV24(rt, res, 0), []ChatTool{chatToolRec("count_incidents", args, res)}}, true
		}
	}
	// "how many were dismissed this week, and how many approved?": both operator decisions in one answer
	if pre == nil && chatApprBothRe[0].MatchString(q) && chatApprBothRe[1].MatchString(q) {
		fa := chatCopyArgs(f)
		delete(fa, "approval")
		delete(fa, "workflow")
		if incs, _, _, err := t.filter(fa, false); err == nil {
			n := map[string]int{}
			for _, ci := range incs {
				n[ci.inc.Approval]++
			}
			subj := chatIncSubject(fa)
			text := fmt.Sprintf("Of the %s %s, %d %s dismissed and %d approved by an operator.", plural(len(incs), strings.TrimSpace(subj+" incident"), strings.TrimSpace(subj+" incidents")),
				when, n["dismissed"], map[bool]string{true: "was", false: "were"}[n["dismissed"] == 1], n["approved"])
			if len(incs) == 0 {
				text = fmt.Sprintf("No %s %s, so none was dismissed or approved.", strings.TrimSpace(subj+" incident"), when)
			} else if rest := len(incs) - n["dismissed"] - n["approved"]; rest > 0 {
				text += fmt.Sprintf(" %s no decision yet.", plural(rest, "has", "have"))
			}
			ga := chatCopyArgs(fa)
			ga["group_by"] = "approval"
			return chatV25{text, []ChatTool{chatToolRec("count_incidents", ga, map[string]any{"total": len(incs), "dismissed": n["dismissed"], "approved": n["approved"]})}}, true
		}
	}
	if pre == nil && (chatSummaryRe.MatchString(q) || regexp.MustCompile(`(?i)\band\s+how\s+many\b`).MatchString(q) || strings.Count(strings.ToLower(q), "how many") > 1) {
		return chatV25{}, false // summaries (chat_router_v24.go) and two questions in one: the older routes / the model
	}
	if chatCompareRe.MatchString(q) && pre == nil {
		return chatV25{}, false // comparisons of two periods: the model (it gets both spans as a hint)
	}
	// "did HVAC and power alerts happen together?": incidents of two domains within an hour of each other
	if doms := chatDomainsOf(q); pre == nil && len(doms) == 2 && chatTogetherRe.MatchString(q) {
		return t.chatTogether(f, when, doms), true
	}
	all := chatCopyArgs(f)
	all["limit"] = 10.0
	if all["time"] == nil {
		all["time"] = map[string]any{"preset": "all"}
	}
	res, err := t.run("find_incidents", all)
	if err != nil {
		return chatV25{fmt.Sprintf("I could not read the incidents: %v.", err), nil}, true
	}
	// every match (find_incidents shows 10): the same filter on the store
	incs, _, _, _ := t.filter(f, false)
	if ids != nil {
		keep := map[string]bool{}
		for _, id := range ids {
			keep[id] = true
		}
		var x []chatInc
		for _, ci := range incs {
			if keep[ci.inc.ID] {
				x = append(x, ci)
			}
		}
		incs = x
	}
	subj := chatIncSubject(f)
	pend := ""
	if f["workflow"] == wfNeeds {
		pend = " still waiting for a decision"
	}
	if ap, _ := f["approval"].(string); ap != "" {
		pend = " " + ap + " by an operator"
	}
	if n, _ := f["node"].(string); n != "" {
		pend = " involving " + n + pend
	}
	one, many := strings.TrimSpace(subj+" incident"), strings.TrimSpace(subj+" incidents")
	tool := chatToolRec("find_incidents", f, res)
	line := func(ci chatInc) string {
		return fmt.Sprintf("[%s] %s (%s, %s, %s)", ci.inc.ID, ci.inc.Title, chatSevName(normSeverity(ci.inc.Severity)), chatTS(ci.at), chatWfWords(wfOf(ci.inc)))
	}
	// grouping: per domain / severity / building / node / day
	key := ""
	if g := chatGroupRe.FindStringSubmatch(q); g != nil && !(chatWorstRe.MatchString(q) && pre != nil) {
		key = strings.ToLower(g[1] + g[2] + g[3])
	} else if prevGroup != "" && chatRankWordRe.MatchString(q) && !chatWorstRe.MatchString(q) {
		key = prevGroup // the same grouping, another end of it
	}
	if key != "" {
		cnt := map[string]int{}
		for _, ci := range incs {
			ks := map[string]bool{}
			switch key {
			case "severity", "type", "category":
				ks[chatSevName(normSeverity(ci.inc.Severity))] = true
			case "building":
				for _, s := range ci.sensors {
					if b := nodes[s.Node].Building; b != "" {
						ks[b] = true
					}
				}
			case "sensor", "node":
				for _, s := range ci.sensors {
					ks[s.Node] = true
				}
			case "metric":
				for _, s := range ci.sensors {
					ks[chatMetricName(s.Metric)] = true
				}
			case "day":
				ks[ci.at.In(IST).Format("Mon 2 Jan")] = true
			default:
				for _, d := range ci.domains {
					if d != "" {
						ks[chatDomainName(d)] = true
					}
				}
			}
			for k := range ks {
				cnt[k]++
			}
		}
		type kv struct {
			k string
			n int
		}
		var kvs []kv
		for k, n := range cnt {
			kvs = append(kvs, kv{k, n})
		}
		sort.Slice(kvs, func(i, j int) bool {
			if kvs[i].n != kvs[j].n {
				return kvs[i].n > kvs[j].n
			}
			return kvs[i].k < kvs[j].k
		})
		if len(incs) == 0 {
			return chatV25{fmt.Sprintf("No %s%s %s, so there is nothing to split by %s.", one, pend, when, key), []ChatTool{tool}}, true
		}
		var ps []string
		for _, x := range kvs {
			ps = append(ps, fmt.Sprintf("%s %d", x.k, x.n))
		}
		text := fmt.Sprintf("%s%s %s. By %s: %s.", plural(len(incs), one, many), pend, when, key, strings.Join(ps, ", "))
		ga := chatCopyArgs(f)
		ga["_group"] = key // a follow-up ("and the fewest?") keeps the grouping
		tool = chatToolRec("count_incidents", ga, res)
		if regexp.MustCompile(`(?i)\b(fewest|least|lowest|sabse\s+kam)\b`).MatchString(q) {
			last := kvs[len(kvs)-1].n
			var low []string
			for _, x := range kvs {
				if x.n == last {
					low = append(low, x.k)
				}
			}
			if len(low) > 1 {
				text += fmt.Sprintf(" Fewest: a tie between %s (%d each); groups with no incident are not listed.", strings.Join(low, " and "), last)
			} else {
				text += fmt.Sprintf(" Fewest: %s (%d); groups with no incident are not listed.", low[0], last)
			}
		} else if regexp.MustCompile(`(?i)\b(most|highest|top)\b`).MatchString(q) {
			var top []string
			for _, x := range kvs {
				if x.n == kvs[0].n {
					top = append(top, x.k)
				}
			}
			if len(top) > 1 {
				text += fmt.Sprintf(" Most: a tie between %s (%d each).", strings.Join(top, " and "), kvs[0].n)
			} else {
				text += fmt.Sprintf(" Most: %s (%d).", kvs[0].k, kvs[0].n)
			}
		}
		return chatV25{text, []ChatTool{tool}}, true
	}
	// the longest-waiting / worst one
	if (chatOldestRe.MatchString(q) || chatWorstRe.MatchString(q)) && !chatCountQRe.MatchString(q) {
		if len(incs) == 0 {
			return chatV25{fmt.Sprintf("No %s%s %s.", one, pend, when), []ChatTool{tool}}, true
		}
		best := incs[0]
		for _, ci := range incs[1:] {
			if chatWorstRe.MatchString(q) {
				si, sb := chatSevOrder[normSeverity(ci.inc.Severity)], chatSevOrder[normSeverity(best.inc.Severity)]
				if si < sb || (si == sb && ci.at.After(best.at)) {
					best = ci
				}
			} else if ci.at.Before(best.at) {
				best = ci
			}
		}
		var text string
		if chatWorstRe.MatchString(q) {
			text = fmt.Sprintf("The most serious of the %s is %s.", plural(len(incs), one, many), line(best))
		} else {
			text = fmt.Sprintf("The one waiting longest of the %s%s is %s, raised %s ago.", plural(len(incs), one, many), pend, line(best), chatAge(t.now.Sub(best.at)))
		}
		tool = chatToolRec("find_incidents", f, map[string]any{"items": []map[string]any{{"id": best.inc.ID}}, "total": len(incs)})
		return chatV25{text + " Ask why, or what to do, for its details.", []ChatTool{tool}}, true
	}
	if chatCountQRe.MatchString(q) || forceCount {
		text := fmt.Sprintf("%s%s %s.", plural(len(incs), one, many), pend, when)
		if len(incs) > 0 && len(incs) <= 3 {
			var ps []string
			for _, ci := range incs {
				ps = append(ps, line(ci))
			}
			text += " " + strings.Join(ps, "; ") + "."
		}
		tool.Name = "count_incidents"
		return chatV25{text, []ChatTool{tool}}, true
	}
	if len(incs) == 0 {
		return chatV25{fmt.Sprintf("No %s%s %s.", one, pend, when), []ChatTool{tool}}, true
	}
	var ps []string
	for _, ci := range incs[:min(8, len(incs))] {
		ps = append(ps, line(ci))
	}
	text := fmt.Sprintf("%s%s %s, newest first: %s.", plural(len(incs), one, many), pend, when, strings.Join(ps, "; "))
	if len(incs) > 8 {
		text += fmt.Sprintf(" (%d more not shown.)", len(incs)-8)
	}
	return chatV25{text, []ChatTool{tool}}, true
}

func chatWfWords(wf string) string {
	if w, ok := map[string]string{wfNeeds: "waiting for decision", wfInProgress: "approved, in progress", wfResolved: "back to normal",
		wfClosed: "closed", wfAnalysing: "AI analysing", wfInterrupted: "analysis interrupted"}[wf]; ok {
		return w
	}
	return wf
}

func chatAge(d time.Duration) string {
	switch {
	case d < time.Hour:
		return plural(int(d.Minutes()), "minute", "minutes")
	case d < 48*time.Hour:
		return fmt.Sprintf("%.1f hours", d.Hours())
	}
	return fmt.Sprintf("%.1f days", d.Hours()/24)
}

// chatIncidentFacts: how long one incident has been open / who acted on it.
func (t chatTools) chatIncidentFacts(id, q string) chatV25 {
	res, err := t.run("get_incident", map[string]any{"id": id})
	if err != nil || res["error"] != nil {
		return chatV25{fmt.Sprintf("There is no %s on this device.", id), nil}
	}
	tool := chatToolRec("get_incident", map[string]any{"id": id}, res)
	var inc *Incident
	t.r.mu.RLock()
	for _, p := range t.r.incidents {
		if p.ID == id {
			inc = p
		}
	}
	t.r.mu.RUnlock()
	if inc == nil {
		return chatV25{fmt.Sprintf("There is no %s on this device.", id), nil}
	}
	at := time.Unix(inc.CreatedSim, 0)
	wf := wfOf(inc)
	var text string
	if chatHowLongRe.MatchString(q) {
		if wf == wfNeeds || wf == wfAnalysing {
			text = fmt.Sprintf("[%s] was raised at %s and has been open for %s (device time %s); it is %s.", id, chatTS(at), chatAge(t.now.Sub(at)), chatTS(t.now), chatWfWords(wf))
		} else {
			text = fmt.Sprintf("[%s] was raised at %s; it is no longer open (%s).", id, chatTS(at), chatWfWords(wf))
		}
	}
	if chatWhoRe.MatchString(q) || regexp.MustCompile(`(?i)\bapprov\w*|\bdismiss\w*|\bstatus\b`).MatchString(q) {
		if !chatHowLongRe.MatchString(q) {
			text = fmt.Sprintf("[%s] %s (%s, %s): %s.", id, inc.Title, chatSevName(normSeverity(inc.Severity)), chatTS(at), chatWfWords(wf))
		}
		var who []string
		for _, st := range inc.Steps {
			if st.By != "" && st.State != "open" {
				who = append(who, fmt.Sprintf("%s %s by %s", st.Action, st.State, st.By))
			}
		}
		switch {
		case inc.Approval == "approved" || inc.Approval == "dismissed":
			s := fmt.Sprintf(" An operator %s it", inc.Approval)
			if len(who) > 0 {
				s += "; steps: " + strings.Join(who, "; ")
			}
			text += s + ". The device does not store operator names beyond what the steps record."
		case len(who) > 0:
			text += " Steps done: " + strings.Join(who, "; ") + "."
		default:
			text += " Nobody has approved or dismissed it yet (approval pending)."
		}
	}
	return chatV25{strings.TrimSpace(text), []ChatTool{tool}}
}

// ---------------------------------------------------------------- scenarios

// chatScenario: "suppose the tank inlet valve fails - what would the sensors show and how fast would we know?": the
// sensors that watch that part, their readings and alert rules, and the device's detection timing (engine.go gates).
func (t chatTools) chatScenario(q string, place chatPlace, metrics []string, dom string, nodes map[string]NodeInfo) (chatV25, bool) {
	if dom == "" {
		for _, w := range []struct{ re, d string }{{`(?i)\b(valve|tank|pipe|pump|leak\w*|water)\b`, "water"}, {`(?i)\b(feeder|breaker|transformer|power|outage|blackout|trips?)\b`, "power"},
			{`(?i)\b(ac|hvac|chiller|compressor|cooling)\b`, "hvac"}, {`(?i)\b(fan|ventilation|exhaust|filter)\b`, "air_quality"}} {
			if regexp.MustCompile(w.re).MatchString(q) {
				dom = w.d
				break
			}
		}
	}
	if dom == "" {
		return chatV25{}, false
	}
	var picks []chatSensorPick
	var ids []string
	for id := range nodes {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		n := nodes[id]
		if n.Role != dom || (place.Building != "" && n.Building != place.Building) {
			continue
		}
		for _, m := range n.Metrics {
			if dom == "hvac" && m != "room_temp" && m != "ac_on" {
				continue
			}
			picks = append(picks, chatSensorPick{id, m})
		}
	}
	if len(picks) == 0 {
		return chatV25{}, false
	}
	text := fmt.Sprintf("I can't simulate that failure, but this is what the device would see. The %s sensors that would show it: ", chatDomainName(dom))
	v, tl := t.chatValues(picks, false)
	text += v
	text += fmt.Sprintf(" The device reads every sensor every 5 minutes. A reading beyond a CRITICAL limit opens an incident after %d readings (about %d minutes); "+
		"other abnormal patterns (a steady drop, a flat line, a step) are reported after %d abnormal readings (about %d minutes), and the AI report follows.",
		trigRules().FastReadings, trigRules().FastReadings*5, trigRules().PersistReadings, trigRules().PersistReadings*5)
	if dom == "water" || dom == "power" {
		text += " Water level, flow and power have no fixed limits, so for them the pattern rule applies."
	}
	return chatV25{text, []ChatTool{tl}}, true
}

// chatWhatIfLimit: "what if outdoor PM2.5 goes to 180 (tomorrow)?" - the target against the device's alert limits and
// the current reading. Only metrics with limits; the data-fitted what_if (other readings) stays with the older route.
func (t chatTools) chatWhatIfLimit(q string, place chatPlace, metrics []string, nodes map[string]NodeInfo) (chatV25, bool) {
	m := chatToValRe.FindStringSubmatchIndex(q)
	// only when the question is about alerts or a decision (the fitted what_if answers "what happens to the others")
	if m == nil || len(metrics) == 0 || !regexp.MustCompile(`(?i)\b(should\s+(we|i)|cancel\w*|safe|unsafe|danger\w*|alert\w*|alarm\w*|critical|warning|tomorrow|kal)\b`).MatchString(q) {
		return chatV25{}, false
	}
	to, err := strconv.ParseFloat(q[m[2]:m[3]], 64)
	if err != nil {
		return chatV25{}, false
	}
	// the metric named before the target
	word := ""
	for _, w := range chatMetricWords {
		if ix := w.re.FindStringIndex(q); ix != nil && ix[0] < m[0] && contains(metrics, w.metric) {
			word = w.metric
		}
	}
	if word == "" {
		return chatV25{}, false
	}
	picks, _ := chatPickSensors(place, []string{word}, "", nodes)
	if len(picks) == 0 {
		return chatV25{}, false
	}
	// one metric definition (role) for all picks
	role := nodes[picks[0].Node].Role
	met, ok := Metrics[role+"/"+picks[0].Metric]
	if !ok || !met.HasLimits {
		return chatV25{}, false
	}
	for _, p := range picks[1:] {
		if nodes[p.Node].Role != role || p.Metric != picks[0].Metric {
			return chatV25{}, false
		}
	}
	st := chatLimitStatus(role, picks[0].Metric, to)
	name := chatMetricName(picks[0].Metric)
	text := fmt.Sprintf("If %s reached %s, the device would rate it %s", name, chatNum(to, met.Unit), strings.ToUpper(chatSevName(st)))
	dir := "above"
	if met.Dir == "low" {
		dir = "below"
	}
	text += fmt.Sprintf(" (its alert limits are %s %s warning and %s critical)", dir, chatNum(met.Warn, met.Unit), chatNum(met.Crit, met.Unit))
	switch st {
	case "critical":
		text += fmt.Sprintf(" and open a critical incident after %d readings (about %d minutes).", trigRules().FastReadings, trigRules().FastReadings*5)
	case "warning":
		text += fmt.Sprintf(" and report a warning after %d abnormal readings (about %d minutes).", trigRules().PersistReadings, trigRules().PersistReadings*5)
	default:
		text += ", so no alert would be raised."
	}
	if v, tl := t.chatValues(picks[:min(2, len(picks))], false); v != "" {
		text += " Now: " + v
		if regexp.MustCompile(`(?i)\b(should\s+(we|i)|cancel|allow|safe)\b`).MatchString(q) {
			text += " Whether to cancel or change activities is a decision for the operator or campus policy; the device only reports the level against its limits."
		}
		return chatV25{text, []ChatTool{tl}}, true
	}
	return chatV25{text, nil}, true
}

// ---------------------------------------------------------------- explanations

// chatGlossary: what each measured quantity means, in plain words (blind sweep: "explain power factor in simple words"
// was declined as out of scope).
var chatGlossary = map[string]string{
	"pf":          "Power factor is how much of the current drawn from the supply does useful work: 1.0 is perfect; lower values mean extra current flows without doing work (typical of motors and AC compressors), which heats cables and can be penalised by the utility.",
	"power_kw":    "Power (kW) is the rate at which electricity is being used right now; energy (kWh) is that power added up over time.",
	"co2":         "CO2 (ppm) indoors mostly comes from people breathing; high values mean the room is crowded or poorly ventilated, and above about 1000 ppm people feel stuffy and sleepy.",
	"pm25":        "PM2.5 is the amount of very fine dust and smoke particles (smaller than 2.5 micrometres) in the air, in micrograms per cubic metre; they reach deep into the lungs, so high values are a health risk.",
	"pm10":        "PM10 is the amount of coarser dust particles (smaller than 10 micrometres) in the air, in micrograms per cubic metre.",
	"rh":          "Relative humidity (%) is how much water vapour the air holds compared with the most it could hold at that temperature.",
	"temp":        "Temperature is measured in degrees Celsius.",
	"room_temp":   "Room temperature is the temperature an AC unit measures in the room it serves.",
	"setpoint":    "The setpoint is the temperature an AC unit is told to hold.",
	"ac_on":       "AC on is the unit's on/off state: 1 = running, 0 = off.",
	"tds":         "TDS (total dissolved solids, ppm) is how much dissolved salt and mineral is in the water; drinking water should stay below about 500 ppm.",
	"ph":          "pH tells whether water is acidic (below 7) or alkaline (above 7); drinking water should be between 6.5 and 8.5.",
	"level":       "Tank level is how full the water tank is.",
	"flow":        "Flow (m3/h) is how much water passes the meter per hour.",
	"occ":         "Occupancy is a presence sensor: 1 = someone is in the room, 0 = empty.",
	"wind":        "Wind speed is measured in metres per second at the rooftop weather station.",
	"ac_units_on": "AC units on is how many AC units on that floor are running.",
}

var chatExplainRe = regexp.MustCompile(`(?i)\b(explain|meaning\s+of|what\s+does\s+.{1,30}\s+mean|what\s+is\s+(a\s+|the\s+)?(meaning|definition)|define|matlab|samjha\w*|in\s+simple\s+(words|terms)|what\s+is\s+(a\s+)?(power\s+factor|pf|tds|ph|pm\s*2\.?5|pm25|pm10|co2|setpoint|occupancy|humidity)\s*\??$)`)

// chatExplain: a plain-words explanation of a measured quantity, its alert limits and where the device measures it.
func (t chatTools) chatExplain(q string, metrics []string, nodes map[string]NodeInfo) (chatV25, bool) {
	if !chatExplainRe.MatchString(q) || len(metrics) == 0 {
		return chatV25{}, false
	}
	var parts []string
	var picks []chatSensorPick
	for _, w := range metrics {
		ms := []string{w}
		if w == "aq" {
			ms = []string{"co2", "pm25", "pm10"}
		} else if w == "wq" {
			ms = []string{"ph", "tds"}
		}
		for _, m := range ms {
			g, ok := chatGlossary[m]
			if !ok {
				continue
			}
			parts = append(parts, g)
			for _, role := range []string{"air_quality", "water", "power", "weather", "occupancy", "hvac"} {
				if mt, ok := Metrics[role+"/"+m]; ok && mt.HasLimits {
					dir := "above"
					if mt.Dir == "low" {
						dir = "below"
					}
					parts = append(parts, fmt.Sprintf("The device warns %s %s and raises a critical alert %s %s.", dir, chatNum(mt.Warn, mt.Unit), dir, chatNum(mt.Crit, mt.Unit)))
					break
				}
			}
			ps, _ := chatPickSensors(chatPlace{Level: -1, Unit: -1}, []string{m}, "", nodes)
			picks = append(picks, ps...)
		}
	}
	if len(parts) == 0 {
		return chatV25{}, false
	}
	text := strings.Join(parts, " ")
	var tools []ChatTool
	if len(picks) > 0 && len(picks) <= 3 {
		if v, tl := t.chatValues(picks, false); v != "" {
			text += " On this campus: " + v
			tools = append(tools, tl)
		}
	}
	return chatV25{text, tools}, true
}

var chatTogetherRe = regexp.MustCompile(`(?i)\b(together|same\s+time|at\s+once|simultaneous\w*|overlap\w*|ek\s+saath|saath\s+mein|coincid\w*|both)\b`)

// chatDomainsOf: every domain q names, in order.
func chatDomainsOf(q string) []string {
	type hit struct {
		at  int
		dom string
	}
	var hs []hit
	for _, d := range chatDomainWords {
		if ix := d.re.FindStringIndex(q); ix != nil {
			hs = append(hs, hit{ix[0], d.dom})
		}
	}
	sort.Slice(hs, func(i, j int) bool { return hs[i].at < hs[j].at })
	var out []string
	for _, h := range hs {
		if !contains(out, h.dom) {
			out = append(out, h.dom)
		}
	}
	return out
}

// chatTogether: pairs of incidents of two domains raised within an hour of each other in the period.
func (t chatTools) chatTogether(f map[string]any, when string, doms []string) chatV25 {
	var sets [2][]chatInc
	var tools []ChatTool
	for i, d := range doms[:2] {
		g := chatCopyArgs(f)
		g["domain"] = d
		incs, _, _, err := t.filter(g, false)
		if err != nil {
			return chatV25{fmt.Sprintf("I could not read the incidents: %v.", err), nil}
		}
		sets[i] = incs
		g["limit"] = 10.0
		if res, err := t.run("find_incidents", g); err == nil {
			tools = append(tools, chatToolRec("find_incidents", g, res))
		}
	}
	a, b := chatDomainName(doms[0]), chatDomainName(doms[1])
	var pairs []string
	for _, x := range sets[0] {
		for _, y := range sets[1] {
			if x.inc.ID == y.inc.ID {
				pairs = append(pairs, fmt.Sprintf("[%s] involved both (%s)", x.inc.ID, chatTS(x.at)))
				continue
			}
			if d := x.at.Sub(y.at); d < time.Hour && d > -time.Hour {
				pairs = append(pairs, fmt.Sprintf("[%s] %s (%s) and [%s] %s (%s)", x.inc.ID, a, chatTS(x.at), y.inc.ID, b, chatTS(y.at)))
			}
		}
	}
	head := fmt.Sprintf("%s: %s and %s %s.", strings.TrimSpace(when), plural(len(sets[0]), a+" incident", a+" incidents"), plural(len(sets[1]), b+" incident", b+" incidents"), "")
	head = strings.Replace(head, " .", ".", 1)
	if len(pairs) == 0 {
		return chatV25{head + fmt.Sprintf(" None of them came within an hour of each other, so %s and %s alerts did not happen together.", a, b), tools}
	}
	if len(pairs) > 5 {
		pairs = append(pairs[:5], fmt.Sprintf("%d more", len(pairs)-5))
	}
	return chatV25{head + fmt.Sprintf(" These came within an hour of each other: %s.", strings.Join(pairs, "; ")), tools}
}

var chatUnitsOffRe = regexp.MustCompile(`(?i)\b(switch|turn|shut|band)\w*\s+(off|on|down|kar\w*)?\s*(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|all|half)\b[^?.!]*\b(ac|a/c|acs|air\s*con\w*)\b|\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|all|half)\s+(of\s+the\s+)?(ac|a/c|acs)\b[^?.!]*\b(off|on|band|chalu)\b`)

// chatWhatIfUnits: a what-if about switching N AC units off (or on) -> the fitted what_if on the floor's "AC units on"
// count (chat_tools_v3.go), answered like the deploy23 what-if.
func (t chatTools) chatWhatIfUnits(q string, place chatPlace, nodes map[string]NodeInfo) (chatV25, bool) {
	m := chatUnitsOffRe.FindStringSubmatch(q)
	if m == nil {
		return chatV25{}, false
	}
	word := strings.ToLower(m[3] + m[5])
	on := regexp.MustCompile(`(?i)\b(on|chalu)\b`).MatchString(m[0]) && !regexp.MustCompile(`(?i)\b(off|band|down)\b`).MatchString(m[0])
	// the floor's AC group sensor
	pl := place
	pl.Kinds, pl.Unit = nil, -1
	picks, _ := chatPickSensors(pl, []string{"ac_on"}, "", nodes)
	node := ""
	for _, p := range picks {
		if p.Metric == "ac_units_on" {
			node = p.Node
		}
	}
	if node == "" {
		return chatV25{}, false
	}
	s := t.chatState(node, "ac_units_on")
	args := map[string]any{"driver": "ac_units_on", "location": node}
	switch {
	case word == "all":
		args["change_pct"] = -100.0
	case word == "half":
		args["change_pct"] = -50.0
	default:
		n := chatNumOf(word)
		if n <= 0 {
			return chatV25{}, false
		}
		d := float64(n)
		if !on {
			d = -d
		}
		args["change_abs"] = d
	}
	if on && args["change_pct"] != nil {
		return chatV25{}, false
	}
	res, err := t.run("what_if", args)
	if err != nil {
		return chatV25{fmt.Sprintf("I can't estimate that from the device's data (%v).", err), nil}, true
	}
	text := chatSayWhatIf(chatRoute{Tool: "what_if", Args: args}, res, 0)
	if s != nil && s.Last != nil {
		text += fmt.Sprintf(" (%s units are on there now, by the latest reading.)", chatNum(chatRound("ac_units_on", *s.Last), ""))
	}
	return chatV25{text + " This is an estimate; I cannot switch the units myself.", []ChatTool{chatToolRec("what_if", args, res)}}, true
}

var chatNormalQRe = regexp.MustCompile(`(?i)\b(normal|usual|typical|high|low|ok|okay|theek|thik|fine|too\s+much|zyada|kam|wasting|waste|should|need\w*|chahiye)\b`)

// chatJudge: "is that normal or high?" for readings without fixed limits: the latest value against the sensor's own
// last 7 days (10th-90th percentile); and an AC that runs in an empty room. "" = nothing to add.
func (t chatTools) chatJudge(q string, picks []chatSensorPick) string {
	if !chatNormalQRe.MatchString(q) || t.r.eng == nil {
		return ""
	}
	var out []string
	var acOn, empty []string
	for _, p := range picks {
		s := t.chatState(p.Node, p.Metric)
		if s == nil || s.Last == nil {
			continue
		}
		switch p.Metric {
		case "ac_on":
			if *s.Last >= 0.5 {
				acOn = append(acOn, p.Node)
			}
			continue
		case "occ":
			if *s.Last < 0.5 {
				empty = append(empty, p.Node)
			}
			continue
		case "setpoint", "ac_units_on":
			continue
		}
		if m, ok := Metrics[s.Role+"/"+p.Metric]; ok && m.HasLimits {
			continue // judged against its limits already
		}
		xs := t.r.eng.HistoryAt(p.Node, p.Metric, t.now.Unix()/bucketSec*bucketSec, 2016)
		if len(xs) < 48 {
			continue
		}
		ys := append([]float64(nil), xs...)
		sort.Float64s(ys)
		lo, hi := ys[len(ys)/10], ys[len(ys)*9/10]
		v := *s.Last
		word := "within its usual range"
		switch {
		case v > hi:
			word = "higher than usual"
		case v < lo:
			word = "lower than usual"
		}
		out = append(out, fmt.Sprintf("%s %s is %s: over the last 7 days it was mostly between %s and %s",
			chatMetricName(p.Metric), chatNum(chatRound(p.Metric, v), s.Unit), word, chatNum(chatRound(p.Metric, lo), s.Unit), chatNum(chatRound(p.Metric, hi), s.Unit)))
	}
	if len(acOn) > 0 && len(empty) > 0 {
		out = append(out, "The AC is on while the room's occupancy sensor shows nobody there, so it is likely cooling an empty room (worth checking its schedule)")
	} else if len(acOn) > 0 && len(empty) == 0 && regexp.MustCompile(`(?i)\b(wast\w*|should|need\w*)\b`).MatchString(q) {
		for _, p := range picks {
			if p.Metric == "occ" {
				out = append(out, "The AC is on and the room is occupied, so it is not obviously wasting energy")
				break
			}
		}
	}
	if len(out) == 0 {
		return ""
	}
	return " " + strings.Join(out, ". ") + "."
}
