package main

// Spec cards (V3_DESIGN §2.1). Python reference: proofs/2026-11-13_v3_data/core/cards.py. The cards of today's metrics
// are exported from cards.existing_cards() into cards_existing.json (make_fixtures.py) and embedded, so their numbers can
// never drift from the training data; the renderers below are byte-identical to render_full / render_line
// (TestCardRenderParity) and ValidateCard returns the same messages as validate_card (TestCardValidateParity).
// The site config (site.go) can override or add cards; the agt_v3 prompt builder (features_v3.go) reads them.

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"
)

//go:embed cards_existing.json
var cardsExistingJSON []byte

type CardLim struct {
	Dir  string   `json:"dir"`
	At   *float64 `json:"at,omitempty"`
	Low  *float64 `json:"low,omitempty"`
	High *float64 `json:"high,omitempty"`
}

type CardImp struct {
	Below *float64 `json:"below"`
	Above *float64 `json:"above"`
}

type CardRate struct {
	AbruptWarn  float64  `json:"abrupt_warn"`
	AbruptCrit  float64  `json:"abrupt_crit"`
	GradualWarn float64  `json:"gradual_warn"`
	GradualCrit *float64 `json:"gradual_crit"`
	Osc         string   `json:"osc"`
}

type CardTank struct {
	High     float64 `json:"high"`
	Overflow float64 `json:"overflow"`
	FillMin  float64 `json:"fill_min"`
}

// Card is one spec card. Rules (cause_action, routines, legacy_key, ...) stays raw: only validation reads it.
type Card struct {
	CardID     string         `json:"card_id"`
	Quantity   string         `json:"quantity"`
	Unit       string         `json:"unit"`
	Kind       string         `json:"kind"`
	Domain     string         `json:"domain"`
	Decimals   int            `json:"decimals"`
	Context    string         `json:"context"`
	Normal     []float64      `json:"normal"`
	Warning    *CardLim       `json:"warning"`
	Critical   *CardLim       `json:"critical"`
	Impossible *CardImp       `json:"impossible"`
	Noise      *float64       `json:"noise"`
	Floor      *float64       `json:"floor"`
	MaxStep    *float64       `json:"max_step"`
	RateRules  *CardRate      `json:"rate_rules"`
	Dynamics   string         `json:"dynamics"`
	Cycle      string         `json:"cycle"`
	Causes     []string       `json:"causes"`
	Actions    []string       `json:"actions"`
	Faults     []string       `json:"faults"`
	Tank       *CardTank      `json:"tank"`
	Rules      map[string]any `json:"rules"`
	Short      string         `json:"short,omitempty"`
	LineHint   string         `json:"line_hint,omitempty"`
}

var cardKeys = []string{"card_id", "quantity", "unit", "kind", "domain", "decimals", "context", "normal", "warning", "critical",
	"impossible", "noise", "floor", "max_step", "rate_rules", "dynamics", "cycle", "causes", "actions", "faults", "tank", "rules"}

var (
	cardKinds       = []string{"continuous", "binary_state", "count", "hvac_unit"}
	cardDomainNames = map[string]string{}
	cardBaseActions []string
	cardFaultsAll   []string
	existingCards   = map[string]Card{}
	existingCardRaw = map[string]map[string]any{}
)

func init() {
	var f struct {
		Cards       map[string]json.RawMessage `json:"cards"`
		DomainNames map[string]string          `json:"domain_names"`
		BaseActions []string                   `json:"base_actions"`
		FaultsAll   []string                   `json:"faults_all"`
	}
	if err := json.Unmarshal(cardsExistingJSON, &f); err != nil {
		panic("cards_existing.json: " + err.Error())
	}
	cardDomainNames, cardBaseActions, cardFaultsAll = f.DomainNames, f.BaseActions, f.FaultsAll
	for id, raw := range f.Cards {
		var c Card
		if err := json.Unmarshal(raw, &c); err != nil {
			panic("card " + id + ": " + err.Error())
		}
		existingCards[id] = c
		var m map[string]any
		_ = json.Unmarshal(raw, &m)
		existingCardRaw[id] = m
	}
}

// CardPatterns: the pattern list of a card's kind (ContPatterns 12, OccPatterns 6, HVAC 21).
func CardPatterns(c Card) []string {
	switch c.Kind {
	case "binary_state":
		return OccPatterns
	case "hvac_unit":
		return cardHVACPatterns
	}
	return ContPatterns
}

var cardHVACPatterns = []string{"stable", "normal_cycling", "pull_down", "setback_drift", "too_hot", "too_cold", "slow_recovery",
	"no_cooling_effect", "short_cycling", "stuck_on", "stuck_off", "running_empty_room", "unit_alarm",
	"flatline", "erratic", "bias_jump", "biased_reading", "calibration_drift", "dropout", "saturation", "quantised"}

// cardNum mirrors cards.num: integers without a point, others the shortest %.6f text.
func cardNum(v float64) string {
	if v == math.Trunc(v) && math.Abs(v) < 1e15 {
		return strconv.FormatInt(int64(v), 10)
	}
	s := strconv.FormatFloat(v, 'f', 6, 64)
	s = strings.TrimRight(s, "0")
	return strings.TrimRight(s, ".")
}

func pnum(p *float64) string {
	if p == nil {
		return ""
	}
	return cardNum(*p)
}

func cardLimText(l *CardLim, which string) string {
	if l == nil {
		return ""
	}
	if l.Dir == "both" {
		return fmt.Sprintf("%s below %s or above %s", which, pnum(l.Low), pnum(l.High))
	}
	rel := "below"
	if l.Dir == "high" {
		rel = "above"
	}
	return fmt.Sprintf("%s %s %s", which, rel, pnum(l.At))
}

func cardImpText(c Card) string {
	if c.Impossible == nil {
		return ""
	}
	a, b := c.Impossible.Below, c.Impossible.Above
	switch {
	case a != nil && b != nil:
		return "impossible below " + cardNum(*a) + " or above " + cardNum(*b)
	case a != nil:
		return "impossible below " + cardNum(*a)
	case b != nil:
		return "impossible above " + cardNum(*b)
	}
	return ""
}

func pyRoundPct(x float64) string { return cardNum(pyRound(x * 100)) }

// pyRound: Python 3 round() to an integer (banker's rounding on exact halves).
func pyRound(x float64) float64 { return math.RoundToEven(x) }

func cardRateText(rr *CardRate) string {
	var a string
	if rr.AbruptWarn <= 0 {
		a = "step, spike, dip or fast rise = warning, critical above " + pyRoundPct(rr.AbruptCrit) + "%"
	} else {
		a = "step, spike, dip or fast rise warning above " + pyRoundPct(rr.AbruptWarn) + "%, critical above " + pyRoundPct(rr.AbruptCrit) + "%"
	}
	g := "gradual change warning above " + pyRoundPct(rr.GradualWarn) + "%"
	if rr.GradualCrit != nil && *rr.GradualCrit != 0 {
		g += ", critical above " + pyRoundPct(*rr.GradualCrit) + "%"
	}
	osc := rr.Osc
	if osc == "" {
		osc = "normal"
	}
	return "rate rule (change = max - min vs first-hour mean): " + a + "; " + g + "; cycling " + osc
}

func cardUnitShown(c Card) string {
	if c.Unit == "" {
		return "ratio"
	}
	return c.Unit
}

// RenderCardFull mirrors cards.render_full (agent CARD block). place "" = None.
func RenderCardFull(c Card, place string) string {
	head := fmt.Sprintf("CARD: %s [%s], %s, %s", c.Quantity, cardUnitShown(c), c.Kind, c.Context)
	if place != "" {
		head += " (" + place + ")"
	}
	var parts []string
	if len(c.Normal) == 2 {
		parts = append(parts, "normal "+cardNum(c.Normal[0])+"-"+cardNum(c.Normal[1]))
	}
	w, cr := cardLimText(c.Warning, "warning"), cardLimText(c.Critical, "critical")
	if w != "" {
		parts = append(parts, w)
	}
	if cr != "" {
		parts = append(parts, cr)
	}
	if w == "" && cr == "" {
		parts = append(parts, "no fixed limits")
	}
	if it := cardImpText(c); it != "" {
		parts = append(parts, it)
	}
	if c.Noise != nil {
		parts = append(parts, "noise "+cardNum(*c.Noise))
	}
	if c.MaxStep != nil && *c.MaxStep != 0 {
		parts = append(parts, "max 5-min change "+cardNum(*c.MaxStep))
	}
	lines := []string{head, "  " + strings.Join(parts, " | ")}
	if c.RateRules != nil {
		lines = append(lines, "  "+cardRateText(c.RateRules))
	}
	if c.Tank != nil {
		t := c.Tank
		lines = append(lines, fmt.Sprintf("  tank: high level above %s, overflow risk above %s; usual fill up to %s min",
			cardNum(t.High), cardNum(t.Overflow), cardNum(t.FillMin)))
	}
	if c.Dynamics != "" {
		lines = append(lines, "  dynamics: "+c.Dynamics)
	}
	if c.Cycle != "" {
		lines = append(lines, "  cycle: "+c.Cycle)
	}
	return strings.Join(lines, "\n")
}

// RenderCardLine mirrors cards.render_line (reasoner one-line card).
func RenderCardLine(c Card) string {
	u := c.Unit
	if u == "" {
		u = "ratio"
	}
	short := c.Short
	if short == "" {
		short = c.Quantity
	}
	parts := []string{"card: " + short + " " + u}
	if c.Kind == "binary_state" || c.Kind == "hvac_unit" {
		parts = append(parts, c.Kind)
	}
	if len(c.Normal) == 2 {
		parts = append(parts, "normal "+cardNum(c.Normal[0])+"-"+cardNum(c.Normal[1]))
	}
	for _, x := range []struct {
		l   *CardLim
		tag string
	}{{c.Warning, "warn"}, {c.Critical, "crit"}} {
		if x.l == nil {
			continue
		}
		if x.l.Dir == "both" {
			parts = append(parts, fmt.Sprintf("%s <%s or >%s", x.tag, pnum(x.l.Low), pnum(x.l.High)))
		} else {
			op := "<"
			if x.l.Dir == "high" {
				op = ">"
			}
			parts = append(parts, x.tag+" "+op+pnum(x.l.At))
		}
	}
	if c.RateRules != nil {
		parts = append(parts, "no fixed limit | warn: abrupt change | crit +"+pyRoundPct(c.RateRules.AbruptCrit)+"% vs first hour")
	}
	if c.Impossible != nil {
		if c.Impossible.Below != nil {
			parts = append(parts, "impossible <"+cardNum(*c.Impossible.Below))
		} else if c.Impossible.Above != nil {
			parts = append(parts, "impossible >"+cardNum(*c.Impossible.Above))
		}
	}
	if c.LineHint != "" {
		parts = append(parts, c.LineHint)
	}
	return strings.Join(parts, " | ")
}

// MetricToCard mirrors cards.metric_to_card: today's (role, metric, node, location) -> card id.
func MetricToCard(role, metric, node, location string) string {
	switch role {
	case "air_quality":
		if metric == "pm25" || metric == "pm10" {
			if strings.HasPrefix(node, "AQ-") || strings.Contains(location, "outdoor") {
				return metric + "_outdoor"
			}
			return metric + "_indoor"
		}
		return map[string]string{"co2": "co2_indoor", "temp": "temp_indoor", "rh": "rh_indoor"}[metric]
	case "water":
		return map[string]string{"level": "tank_level", "flow": "water_flow", "tds": "water_tds", "ph": "water_ph"}[metric]
	case "power":
		if metric == "pf" {
			return "power_pf"
		}
		if strings.HasPrefix(node, "SL-") {
			return "power_solar"
		}
		return "power_load"
	case "weather":
		return "weather_" + metric
	case "occupancy":
		return "occupancy"
	case "hvac":
		if metric == "ac_units_on" {
			return "ac_units_on"
		}
		return "hvac_unit"
	}
	return ""
}

// ---------------------------------------------------------------- validation (cards.validate_card)

func rawF(v any) (float64, bool) {
	f, ok := v.(float64)
	return f, ok
}

func rawStrs(v any) []string {
	a, _ := v.([]any)
	out := make([]string, 0, len(a))
	for _, x := range a {
		if s, ok := x.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// ValidateCardRaw: the problems of a card given as decoded JSON (empty = ok). Same messages as validate_card.
func ValidateCardRaw(c map[string]any) []string {
	var bad []string
	for _, k := range cardKeys {
		if _, ok := c[k]; !ok {
			bad = append(bad, "missing "+k)
		}
	}
	if len(bad) > 0 {
		return bad
	}
	kind, _ := c["kind"].(string)
	if !contains(cardKinds, kind) {
		bad = append(bad, "kind")
	}
	if d, _ := c["domain"].(string); cardDomainNames[d] == "" {
		bad = append(bad, "domain")
	}
	lims := map[string]map[string]any{}
	for _, which := range []string{"warning", "critical"} {
		l, _ := c[which].(map[string]any)
		if l == nil {
			continue
		}
		lims[which] = l
		dir, _ := l["dir"].(string)
		if dir != "high" && dir != "low" && dir != "both" {
			bad = append(bad, which+".dir")
		}
		_, hl := l["low"]
		_, hh := l["high"]
		_, ha := l["at"]
		if dir == "both" && !(hl && hh) {
			bad = append(bad, which+" both needs low/high")
		}
		if dir != "both" && !ha {
			bad = append(bad, which+".at")
		}
	}
	w, cr := lims["warning"], lims["critical"]
	if w != nil && cr != nil && w["dir"] == cr["dir"] {
		g := func(m map[string]any, k string) float64 { f, _ := rawF(m[k]); return f }
		switch w["dir"] {
		case "high":
			if !(g(cr, "at") > g(w, "at")) {
				bad = append(bad, "critical must be above warning")
			}
		case "low":
			if !(g(cr, "at") < g(w, "at")) {
				bad = append(bad, "critical must be below warning")
			}
		case "both":
			if !(g(cr, "low") < g(w, "low") && g(cr, "high") > g(w, "high")) {
				bad = append(bad, "both: critical outside warning")
			}
		}
	}
	if (w == nil) != (cr == nil) {
		bad = append(bad, "warning/critical must both be set or both null")
	}
	rules, _ := c["rules"].(map[string]any)
	if rules == nil {
		rules = map[string]any{}
	}
	rr, _ := c["rate_rules"].(map[string]any)
	routines, _ := rules["routines"].([]any)
	if kind == "continuous" && w == nil && len(rr) == 0 && len(routines) == 0 {
		bad = append(bad, "no limits and no rate rule")
	}
	imp, _ := c["impossible"].(map[string]any)
	normal, _ := c["normal"].([]any)
	if len(normal) == 2 && imp != nil {
		n0, _ := rawF(normal[0])
		n1, _ := rawF(normal[1])
		if b, ok := rawF(imp["below"]); ok && b > n0 {
			bad = append(bad, "impossible.below above normal low")
		}
		if a, ok := rawF(imp["above"]); ok && a < n1 {
			bad = append(bad, "impossible.above below normal high")
		}
	}
	causes := rawStrs(c["causes"])
	if len(causes) == 0 || !contains(causes, "sensor_fault") && kind != "binary_state" {
		bad = append(bad, "causes must include sensor_fault")
	}
	for _, a := range rawStrs(c["actions"]) {
		if !contains(cardBaseActions, a) && a != "switch_off_ac" {
			bad = append(bad, "action "+a)
		}
	}
	for _, f := range rawStrs(c["faults"]) {
		if !contains(cardFaultsAll, f) {
			bad = append(bad, "fault "+f)
		}
	}
	ca, _ := rules["cause_action"].(map[string]any)
	for _, cause := range causes {
		if _, ok := ca[cause]; !ok {
			bad = append(bad, "cause_action missing "+cause)
		}
	}
	return bad
}

// ValidateCard validates a typed card (round-trips it through JSON).
func ValidateCard(c Card) []string {
	b, _ := json.Marshal(c)
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	// typed cards always marshal every key; keep a nil normal / limits as JSON null
	return ValidateCardRaw(m)
}
