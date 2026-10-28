package main

// Agent version switch: v1 (deployed, default) or v2 (retrain v2, training/RETRAIN_V2_SPEC.md).
//
// Like npu_engine, a state file selects it: <workDir>/agent_version containing "v2" (on the QIDK
// /data/local/tmp/smart_city_edge/agent_version), or SCE_AGENT_VERSION=v2. Anything else, or no file,
// keeps v1 exactly as before: v1 prompts (features.go, byte-identical to training/features.py), v1
// whitelists, 4 h windows, htpd 13 x 768. It is read once at startup, because the v2 agent needs the v2
// model and htpd context sizes chosen when htpd starts, and the per-unit HVAC sensors loaded with the
// sensor bank: switching takes a backend restart.
//
// v2 changes, all gated on agentV2():
//   - agent prompts: features_v2.go / hvac_v2.go (any N, E9/E10, TANK line, v2 schema hint), parity-
//     tested against training (features_v2_test.go);
//   - policy whitelists per role: v2 causes (water + tank_overflow_risk, fill_valve_stuck), HVAC
//     patterns/causes, switch_off_ac (recommendation only), fault kinds incl. quantised;
//   - window ladder: early alert 4 h; refinements normal 4 h, warning 8 h, critical/sensor fault 12 h;
//   - per-unit HVAC agents (data/sensors_hvac_v2.json, D1); the engine keeps 13 h of readings so a 12 h
//     window exists from the start;
//   - htpd: --agents 10 --agent-ctx 1280 (12 h prompts reach ~1.1k tokens + ~120 generated).

import (
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

var agentVer = "v1"

// initAgentVersion reads the switch (call once at startup, before the engine and htpd start).
func initAgentVersion(workDir string) {
	agentVer = readAgentVersion(workDir)
	if agentVer == "v2" {
		loadV2Assets(workDir)
		log.Printf("agent version v2: v2 prompts, window ladder, per-unit HVAC agents (%d tank limits, %d E10 thresholds)",
			len(NodeLimitsV2), len(E10CountThresholds))
	}
}

func readAgentVersion(workDir string) string {
	v := strings.TrimSpace(os.Getenv("SCE_AGENT_VERSION"))
	if v == "" {
		if b, err := os.ReadFile(filepath.Join(workDir, "agent_version")); err == nil {
			v = strings.TrimSpace(string(b))
		}
	}
	if v == "v2" {
		return "v2"
	}
	return "v1"
}

func agentV2() bool { return agentVer == "v2" }

// agentPatterns / agentCauses: the policy gate's whitelists for the active agent version.
func agentPatterns(role string) []string {
	if agentV2() {
		return PatternsV2(role)
	}
	if role == "occupancy" {
		return OccPatterns
	}
	return ContPatterns
}

func agentCauses(role string) []string {
	if agentV2() {
		return CausesV2[role]
	}
	return Causes[role]
}

// htpd sizing per version. v1: 13 streams x 768 tokens (HANDBOOK 2.37). v2: 12 h prompts are ~1.1k
// tokens plus ~120 generated, so each stream needs 1280; 10 x 1280 = 12.8k KV cells against v1's
// 13 x 768 = 10k (+28%), the most that leaves the 4096-token synthesizer context and the model within
// the memory htpd uses today. A 13-agent incident then runs as two batches (10 + 3).
func htpdAgentStreams() int {
	if n := htpdProfileInt("agents"); n > 0 {
		return n
	}
	if agentV2() {
		return 10
	}
	return 13
}

func htpdAgentCtx() int {
	if n := htpdProfileInt("agent_ctx"); n > 0 {
		return n
	}
	if agentV2() {
		return 1280
	}
	return 768
}

// htpdProfile is an optional state file <workDir>/htpd_profile of key=value lines that switches the NPU
// daemon build and its options without a new APK (the htpd v7 A/B, HANDBOOK 2.42):
//
//	bin=/data/local/tmp/llama.cpp/bin/htpd_v7
//	agents=14
//	agent_ctx=1024
//	layouts=14x1024,10x1280
//	env=HTPD_ROLE_DRAFT=1 HTPD_AGENT_MAX_NEW=160
//
// No file (or a key missing) = today's defaults. Any change restarts htpd (superviseHtpd's args key).
func htpdProfile() map[string]string {
	out := map[string]string{}
	b, err := os.ReadFile(filepath.Join(htpdWorkDir, "htpd_profile"))
	if err != nil {
		return out
	}
	for _, line := range strings.Split(string(b), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if k, v, ok := strings.Cut(line, "="); ok {
			out[strings.TrimSpace(k)] = strings.TrimSpace(v)
		}
	}
	return out
}

func htpdProfileInt(k string) int {
	n, _ := strconv.Atoi(htpdProfile()[k])
	return n
}

// htpdModelPath: the v2 adapter is merged and quantised to GGUF Q4_0 (spec D2) under its own name, so the
// switch can never pair v2 prompts with the v1 weights by accident. SCE_HTPD_MODEL overrides both.
func htpdModelPath() string {
	// htpd_profile "model=" swaps the v2 GGUF without a new APK (e.g. a top-up candidate), loaded by the
	// app's own htpd - the path that has run stably on the board (separate test daemons did not, 2026-10-22)
	if m := htpdProfile()["model"]; m != "" && agentV2() {
		return m
	}
	if agentV2() {
		return envOr("SCE_HTPD_MODEL", "/data/local/tmp/gpu/ft_v2_q4_0.gguf")
	}
	return envOr("SCE_HTPD_MODEL", "/data/local/tmp/gpu/ft_device_q4exact.gguf")
}
