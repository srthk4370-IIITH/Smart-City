package main

// v2 agent plumbing in the engine and the reasoner (all behind agentV2(), agentversion.go):
// per-unit HVAC sensors (D1), the HVAC context of a window, and the agent prompt for a sensor at its
// window length (the ladder in features_v2.go).

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// hvacUnitInfo is a unit's usual schedule from TRAIN months (hvac.load_hvac_series): ctx duty/hour_on.
type hvacUnitInfo struct {
	Duty   string    `json:"duty"`
	HourOn []float64 `json:"hour_on"`
	Mode   int       `json:"mode"`
}

var hvacUnits = map[string]hvacUnitInfo{}

func init() {
	// v2 causes in the cause -> report label taxonomy (the v1 agent never emits them)
	for c, l := range map[string]string{
		"tank_overflow_risk": "water_supply_issue", "fill_valve_stuck": "water_supply_issue",
		"normal_operation": "normal_operation", "scheduled_off": "normal_operation",
		"high_heat_load": "hvac_or_thermal_issue", "ac_not_cooling": "hvac_or_thermal_issue", "overcooling": "hvac_or_thermal_issue",
		"ac_off_heat_gain": "hvac_or_thermal_issue", "short_cycling_control": "hvac_or_thermal_issue",
		"schedule_or_control_fault": "hvac_or_thermal_issue", "unit_not_starting": "hvac_or_thermal_issue",
		"unoccupied_running": "hvac_or_thermal_issue", "unit_alarm": "hvac_or_thermal_issue",
	} {
		if _, ok := causeToLabel[c]; !ok {
			causeToLabel[c] = l
		}
	}
	nice["setpoint"], nice["ac_on"] = "AC setpoint", "AC running" // per-unit HVAC sensors only exist in v2
	if nice["room_temp"] == "" {
		nice["room_temp"] = "Room temperature" // v2 HVAC unit titles read " judged normal: ..." without it
	}
}

// loadHVACUnitsV2 reads data/sensors_hvac_v2.json: the per-unit HVAC sensors (room_temp, setpoint, ac_on)
// and each unit's schedule. Missing file: no units (the v2 agent then runs the v1 roles only).
func loadHVACUnitsV2(dir string) ([]*SimSensor, error) {
	b, err := os.ReadFile(filepath.Join(dir, "data", "sensors_hvac_v2.json"))
	if err != nil {
		return nil, nil
	}
	var f struct {
		Sensors []SimSensor             `json:"sensors"`
		Units   map[string]hvacUnitInfo `json:"units"`
	}
	if err := json.Unmarshal(b, &f); err != nil {
		return nil, fmt.Errorf("sensors_hvac_v2.json: %w", err)
	}
	out := make([]*SimSensor, 0, len(f.Sensors))
	for i := range f.Sensors {
		s := f.Sensors[i]
		if s.Max <= s.Min || s.Node == "" || s.Metric == "" || s.Role != "hvac" || !isHVACUnit(s.Node) {
			return nil, fmt.Errorf("sensors_hvac_v2.json: bad entry %d (%s %s)", i, s.Node, s.Metric)
		}
		s.Unit = map[string]string{"room_temp": "C", "setpoint": "C", "ac_on": "0/1"}[s.Metric]
		s.Default, s.Source = s.Value, "default"
		out = append(out, &s)
	}
	for k, v := range f.Units {
		hvacUnits[k] = v
	}
	return out, nil
}

// historyLocked is HistoryAt for a caller that holds e.mu.
func (e *Engine) historyLocked(node, metric string, end int64, n int) []float64 {
	s := e.series[key(node, metric)]
	if s == nil || end > e.sim {
		return nil
	}
	if _, ok := s[end]; !ok {
		return nil
	}
	rev := make([]float64, 0, n) // newest first
	gap := 0
	for i := 0; i < n; i++ {
		v, ok := s[end-int64(i)*bucketSec]
		if !ok {
			if gap++; gap > 3 {
				break
			}
			continue
		}
		for ; gap > 0; gap-- {
			rev = append(rev, v)
		}
		rev = append(rev, v)
	}
	xs := make([]float64, len(rev))
	for i, v := range rev {
		xs[len(rev)-1-i] = v
	}
	return xs
}

// hvacWindowLocked: a unit's room-temperature window of n readings ending at end, its HVAC context and
// the room-temperature history (<= 144 readings). Caller holds e.mu. The engine has no thermostat-demand,
// alarm or room-occupancy feed for a unit, so thermo and occupancy are n/a and alarms are off (D9:
// "occupancy n/a" is a trained prompt form).
func (e *Engine) hvacWindowLocked(node string, end int64, n int) ([]float64, HVACCtx, []float64, bool) {
	hist := e.historyLocked(node, "room_temp", end, v2Hist)
	if len(hist) < n {
		return nil, HVACCtx{}, nil, false
	}
	xs := hist[len(hist)-n:]
	temp, sps, ons := e.series[key(node, "room_temp")], e.series[key(node, "setpoint")], e.series[key(node, "ac_on")]
	info := hvacUnits[node]
	c := HVACCtx{SP: make([]float64, n), On: make([]int, n), Alarm: make([]int, n), Missing: make([]bool, n),
		Mode: 1, Malf: 1, Duty: info.Duty, HourOn: info.HourOn, End: end}
	if info.Mode != 0 {
		c.Mode = info.Mode
	}
	lastSP, lastOn := 24.0, 0
	for i := 0; i < n; i++ { // setpoint forward-filled, missing state = off (hvac.hvac_windows)
		b := end - int64(n-1-i)*bucketSec
		if v, ok := sps[b]; ok {
			lastSP = v
		}
		c.SP[i] = lastSP
		if v, ok := ons[b]; ok {
			lastOn = 0
			if v >= 0.5 {
				lastOn = 1
			}
			c.On[i] = lastOn
		}
		_, ok := temp[b]
		c.Missing[i] = !ok
	}
	return xs, c, hist, true
}

// HVACAt is hvacWindowLocked for callers outside the engine lock (reasoner, refinements).
func (e *Engine) HVACAt(node string, end int64, n int) ([]float64, HVACCtx, []float64, bool) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.hvacWindowLocked(node, end, n)
}

// hvacUnitFinding: the HVAC rule finding of a unit at end on its 4 h window (event gate, refinements).
func (e *Engine) hvacUnitFinding(node string, end int64) ([]float64, Finding, bool) {
	xs, c, _, ok := e.hvacWindowLocked(node, end, Window)
	if !ok {
		return nil, Finding{}, false
	}
	return xs, HVACRuleFinding(xs, c), true
}

// HVACUnitFindingAt is hvacUnitFinding outside the engine lock.
func (e *Engine) HVACUnitFindingAt(node string, end int64) ([]float64, Finding, bool) {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.hvacUnitFinding(node, end)
}

// hvacAgentSensor: a sensor the v2 HVAC agent analyses (a unit's room temperature).
func hvacAgentSensor(role, node, metric string) bool {
	return agentV2() && role == "hvac" && metric == "room_temp" && isHVACUnit(node)
}

var promptEvRe = regexp.MustCompile(`(?m)^(E\d+) `)

// promptEvidenceIDs: the evidence ids a prompt shows the agent (its EVIDENCE lines).
func promptEvidenceIDs(prompt string) map[string]bool {
	out := map[string]bool{}
	i := strings.Index(prompt, "\nEVIDENCE:\n")
	if i < 0 {
		return out
	}
	body := prompt[i:]
	if j := strings.Index(body, "<|eot_id|>"); j >= 0 {
		body = body[:j]
	}
	for _, m := range promptEvRe.FindAllStringSubmatch(body, -1) {
		out[m[1]] = true
	}
	return out
}

// agentPrompt is the prompt the NPU agent gets for s: the v1 prompt (4 h, byte-identical to the deployed
// model's training), or with the v2 agent the v2 prompt at s.WinN readings (0 = the 4 h alert window)
// with its 12 h history. ok is false when no prompt can be built (an HVAC unit without a window).
func (r *Reasoner) agentPrompt(s SensorRef) (AgentInput, bool) {
	if !agentV2() {
		return BuildAgentPrompt(s.Role, s.Node, s.Location, s.Metric, s.Xs, s.End), true
	}
	n := s.WinN
	if n == 0 {
		n = LadderAlert
	}
	if s.Role == "hvac" {
		if r.eng == nil || !isHVACUnit(s.Node) {
			return AgentInput{}, false
		}
		for ; n >= v2MinN; n -= v2StepN { // the longest ladder window the history holds
			if xs, c, hist, ok := r.eng.HVACAt(s.Node, s.End, n); ok {
				ai := BuildHVACPromptV2(s.Node, s.Location, xs, c, hist).AgentInput
				hf := HVACRuleFinding(xs, c)
				ai.HVRule = &hf
				return ai, true
			}
		}
		return AgentInput{}, false
	}
	hist := s.Hist
	if hist == nil && r.eng != nil {
		hist = r.eng.HistoryAt(s.Node, s.Metric, s.End, v2Hist)
	}
	if len(hist) < v2MinN {
		hist = s.Xs
	}
	n = ValidV2N(n, len(hist))
	return BuildAgentPromptV2(s.Role, s.Node, s.Location, s.Metric, hist[len(hist)-n:], s.End, hist).AgentInput, true
}

// applyV2Evidence: with the v2 agent a flagged sensor's evidence is the agent's own (E1..E10 at its
// window length), so the agent, the policy gate, the reasoner and the dashboard cite the same lines.
// No-op with the v1 agent.
func (r *Reasoner) applyV2Evidence(sr *SensorRef) {
	if !agentV2() || sr.Context {
		return
	}
	ai, ok := r.agentPrompt(*sr)
	if !ok {
		return
	}
	sr.Evidence, sr.GlobalEv = ai.Evidence, nil
	for _, e := range ai.Evidence {
		sr.GlobalEv = append(sr.GlobalEv, fmt.Sprintf("ev:%s:%s:%s:%d", sr.Node, sr.Metric, e.Stat, sr.End))
	}
}
