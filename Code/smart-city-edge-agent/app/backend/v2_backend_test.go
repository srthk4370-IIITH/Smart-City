package main

import (
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
)

// v2 backend support (agentversion.go): the switch, the per-unit HVAC agents, the policy gate's v2
// whitelists and the refinement window ladder, on the real engine and pipeline with a scripted NPU.

func withAgentVersion(t *testing.T, v string) {
	t.Helper()
	old, oldUnits := agentVer, hvacUnits
	agentVer = v
	hvacUnits = map[string]hvacUnitInfo{}
	t.Cleanup(func() { agentVer, hvacUnits = old, oldUnits })
}

func TestAgentVersionSwitch(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SCE_AGENT_VERSION", "")
	if readAgentVersion(dir) != "v1" {
		t.Fatal("default must be v1")
	}
	os.WriteFile(filepath.Join(dir, "agent_version"), []byte("v2\n"), 0o644)
	if readAgentVersion(dir) != "v2" {
		t.Fatal("state file v2 not read")
	}
	os.WriteFile(filepath.Join(dir, "agent_version"), []byte("v3"), 0o644)
	if readAgentVersion(dir) != "v1" {
		t.Fatal("unknown version must fall back to v1")
	}
	t.Setenv("SCE_AGENT_VERSION", "v2")
	if readAgentVersion(dir) != "v2" {
		t.Fatal("env override")
	}
	withAgentVersion(t, "v1")
	if htpdAgentStreams() != 13 || htpdAgentCtx() != 768 || len(agentCauses("water")) != 9 || contains(agentPatterns("hvac"), "too_hot") {
		t.Fatal("v1 sizing / whitelists changed")
	}
	agentVer = "v2"
	if htpdAgentStreams() != 10 || htpdAgentCtx() != 1280 || !contains(agentCauses("water"), "fill_valve_stuck") || !contains(agentPatterns("hvac"), "too_hot") {
		t.Fatal("v2 sizing / whitelists")
	}
}

func TestV1EngineHasNoHVACUnits(t *testing.T) {
	withAgentVersion(t, "v1")
	eng, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	for k := range eng.states {
		if strings.HasPrefix(k, "SR-AC-") {
			t.Fatalf("v1 engine loaded a v2 HVAC unit %s", k)
		}
	}
	if eng.Meta.History != Window+12 {
		t.Fatalf("v1 history %d", eng.Meta.History)
	}
}

func TestV2HVACUnitAgent(t *testing.T) {
	withAgentVersion(t, "v2")
	eng, err := NewEngine("../device")
	if err != nil {
		t.Fatal(err)
	}
	eng.NoiseScale = 0
	unit := "SR-AC-KH03-15"
	if eng.states[key(unit, "room_temp")] == nil || eng.states[key(unit, "ac_on")] == nil || eng.Meta.History != v2Hist+12 {
		t.Fatalf("v2 engine: HVAC unit sensors or 13 h history missing (history %d)", eng.Meta.History)
	}
	eng.SetSensor(unit, "setpoint", 24, "test")
	eng.SetSensor(unit, "ac_on", 1, "test")
	for i := 0; i < 24; i++ { // the room warms at 0.3 C per reading while the AC runs (no cooling effect)
		eng.SetSensor(unit, "room_temp", 25+0.3*float64(i+1), "test")
		eng.Tick()
	}
	eng.mu.RLock()
	st := *eng.states[key(unit, "room_temp")]
	eng.mu.RUnlock()
	if !contains(HVACPatterns, st.Pattern) || sevRank(st.Status) == 0 || st.Finding == nil || st.Finding.Onset == "" {
		t.Fatalf("HVAC unit not judged by the HVAC rule: %s/%s", st.Pattern, st.Status)
	}
	r := &Reasoner{eng: eng}
	_, _, sim := eng.SimBase()
	s := SensorRef{Ref: "S1", Node: unit, Metric: "room_temp", Role: "hvac", Location: HVACDescribe(unit), End: sim, WinN: 144}
	ai, ok := r.agentPrompt(s)
	if !ok || !strings.Contains(ai.Prompt, ", 144 x 5 min") || !strings.Contains(ai.Prompt, "\nE10 recent episodes") ||
		!strings.Contains(ai.Prompt, "occupancy n/a") || !strings.Contains(ai.Prompt, "You are the HVAC agent") {
		t.Fatalf("HVAC v2 prompt:\n%s", ai.Prompt)
	}
	s.Evidence = ai.Evidence
	out := `{"pattern": "running_empty_room", "status": "warning", "observations": ["AC on with the room getting warmer [E5,E10]"], ` +
		`"likely_cause": "unoccupied_running", "confidence": 0.7, "event_active": true, "onset": "10:05"}`
	call := checkAgent(s, GenieResult{Text: out}, ai.Prompt)
	if !call.Valid || call.Parsed.Action != "switch_off_ac" || call.Parsed.Onset != "10:05" {
		t.Fatalf("v2 HVAC answer rejected: %v %+v", call.Errors, call.Parsed)
	}
	agentVer = "v1"
	if call := checkAgent(s, GenieResult{Text: out}, ai.Prompt); call.Valid {
		t.Fatal("the v1 gate must not accept HVAC agent output")
	}
}

func TestV2PolicyWaterCauses(t *testing.T) {
	s := SensorRef{Ref: "S1", Role: "water", Metric: "level", Evidence: []Evidence{{"E1", "last", ""}, {"E2", "max", ""}}}
	out := `{"pattern": "step_increase", "status": "warning", "observations": ["Level above the high mark [E2,E9]"], "likely_cause": "tank_overflow_risk", "confidence": 0.7}`
	prompt := "x\nEVIDENCE:\nE1 a\nE2 b\nE9 12 h view: no level shift or drift\nE10 recent episodes: none<|eot_id|>"
	withAgentVersion(t, "v1")
	if checkAgent(s, GenieResult{Text: out}, prompt).Valid {
		t.Fatal("v1 accepted a v2 cause")
	}
	agentVer = "v2"
	c := checkAgent(s, GenieResult{Text: out}, prompt)
	if !c.Valid || c.Parsed.Action != "inspect_water_system" {
		t.Fatalf("v2 water cause: %v %+v", c.Errors, c.Parsed)
	}
	c = checkAgent(s, GenieResult{Text: strings.Replace(out, "E9", "E11", 1)}, prompt)
	if c.Valid {
		t.Fatal("an id the prompt never showed must stay a hallucination")
	}
}

// The refinement ladder: alert 4 h, then the window grows with severity (warning 8 h, critical 12 h).
func TestV2RefineLadder(t *testing.T) {
	withAgentVersion(t, "v2")
	rg := newRefineRig(t)
	var mu sync.Mutex
	var lens []string
	inner := mockGen
	mockGen = func(prompt string) (string, error) {
		if strings.Contains(prompt, "METRIC: co2") {
			mu.Lock()
			lens = append(lens, regexp.MustCompile(`, (\d+) x 5 min`).FindStringSubmatch(prompt)[1])
			mu.Unlock()
			if !strings.Contains(prompt, "\nE9 12 h view") || !strings.Contains(prompt, "(E1..E10)") {
				t.Errorf("not a v2 prompt")
			}
		}
		return inner(prompt)
	}
	inc := rg.alert()
	rg.settle(inc.ID)
	rg.answer("exponential_increase/critical")
	rg.readings(18)
	rg.settle(inc.ID)
	rg.readings(18)
	got := rg.settle(inc.ID)
	mu.Lock()
	defer mu.Unlock()
	if strings.Join(lens, ",") != "48,48,96" || got.RefineStage != "3h" {
		t.Fatalf("window lengths %v (want 48,48,96: early step_increase = 4 h at 1.5 h, 8 h at 3 h), stage %s", lens, got.RefineStage)
	}
	if ev := got.Sensors[0].Evidence; len(ev) != 10 || ev[9].ID != "E10" || got.Sensors[0].WinN != 96 {
		t.Fatalf("refined sensor evidence/length: %d items, N %d", len(ev), got.Sensors[0].WinN)
	}
}
