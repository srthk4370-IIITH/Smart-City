package main

// Agentic data requests for the NPU domain agents (coordinator, 2026-11-17). An agent that is unsure of its own
// answer may be asked again with more data, at most maxMoreRounds times per sensor per analysis:
//
//	round 1: the longest window the history holds (the trained v2 lengths, ValidV2N / HistoryAt, up to 12 h)
//	round 2: related-sensor summaries as extra EVIDENCE lines (E11, E12 ...) of the same prompt: the agt_v3
//	         format has no new section, only more E-lines, written from the context agents' own findings
//
// Triggers (on the parsed, valid answer): data_quality.verdict is not "ok", confidence below 0.6, or the onset is at
// or before the window start (the event began before the window). The most confident valid answer is kept. No model
// change; v2/v3 agents only (the v1 prompt has no window ladder).

import (
	"context"
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const (
	maxMoreRounds    = 2
	moreConfidence   = 0.6
	maxRelatedLines  = 3
	relatedLineChars = 180
)

// needMoreData names why the agent's answer should be re-asked with more data ("" = no need). nWin is the
// length of the window the answer was given on.
func needMoreData(call AgentCall, nWin int, end int64) string {
	f := call.Parsed
	if f == nil || !call.Valid {
		return ""
	}
	if f.DataQuality != nil && f.DataQuality.Verdict != "ok" {
		return "data quality " + f.DataQuality.Verdict
	}
	if f.Confidence < moreConfidence {
		return fmt.Sprintf("confidence %.2f", f.Confidence)
	}
	if f.Onset != "" && nWin > 0 {
		if age := onsetAge(f.Onset, nWin, end); age < 0 || age >= nWin {
			return "onset at the window start"
		}
	}
	return ""
}

var citeRe = regexp.MustCompile(`\s*\[[A-Z0-9, ]+\]`)

// relatedLines: one summary line per related sensor of the incident, from the context agents' findings text. Same
// location first (same room), then the others in the incident's order.
func relatedLines(inc *Incident, self SensorRef) []string {
	var same, rest []string
	for _, o := range inc.Sensors {
		if o.Ref == self.Ref || !o.Context {
			continue
		}
		txt := o.Rule.Pattern + ", " + o.Rule.Status
		if len(o.Rule.Observations) > 0 {
			txt = strings.TrimSpace(citeRe.ReplaceAllString(o.Rule.Observations[0], ""))
		}
		line := fmt.Sprintf("related %s (%s, %s): %s", o.Metric, o.Role, o.Location, strings.ReplaceAll(txt, "_", " "))
		if r := []rune(line); len(r) > relatedLineChars {
			line = string(r[:relatedLineChars])
		}
		if o.Location == self.Location {
			same = append(same, line)
		} else {
			rest = append(rest, line)
		}
	}
	out := append(same, rest...)
	if len(out) > maxRelatedLines {
		out = out[:maxRelatedLines]
	}
	return out
}

// withExtraEvidence appends E-lines (ids after the highest shown) to the evidence block of a prompt.
func withExtraEvidence(ai AgentInput, extra []string) AgentInput {
	end := strings.LastIndex(ai.Prompt, "<|eot_id|><|start_header_id|>assistant")
	if end < 0 || len(extra) == 0 {
		return ai
	}
	next := 0
	for id := range promptEvidenceIDs(ai.Prompt) {
		if n, err := strconv.Atoi(id[1:]); err == nil && n > next {
			next = n
		}
	}
	var b strings.Builder
	ev := append([]Evidence(nil), ai.Evidence...)
	for _, x := range extra {
		next++
		id := "E" + strconv.Itoa(next)
		b.WriteString("\n" + id + " " + x)
		ev = append(ev, Evidence{ID: id, Stat: "related", Text: x})
	}
	ai.Prompt = ai.Prompt[:end] + b.String() + ai.Prompt[end:]
	ai.Evidence = ev
	return ai
}

// askMoreData re-asks sensor i's agent while its answer is unsure. Returns the answer to keep, the sensor (window
// length, evidence) it was given on, and whether that differs from first.
// agentMoreOff switches the data requests off (tests that count agent calls or window lengths).
var agentMoreOff bool

func (r *Reasoner) askMoreData(ctx context.Context, inc *Incident, i int, am ModelBundle, first AgentCall) (AgentCall, SensorRef, bool) {
	s0 := inc.Sensors[i]
	best, bestS, changed := first, s0, false
	if agentMoreOff || !agentV2() || s0.Context || s0.Role == "hvac" || first.Parsed == nil || !first.Valid {
		return best, bestS, false
	}
	ai0, ok := r.agentPrompt(s0)
	if !ok {
		return best, bestS, false
	}
	n := len(ai0.Xs)
	bestN := n
	if why := needMoreData(best, bestN, bestS.End); why != "" {
		// night sweep 2026-11-27 #58: on the board the 12 h re-run (~3 s of NPU) always ended with "the larger prompt
		// would not fit the NPU agent context" for the related-sensor round, so the request never completed. Skip it
		// up front when the full request cannot fit agent_ctx.
		if dead := moreDataDead(r.agentPrompt, s0, n, relatedLines(inc, s0)); dead != "" {
			r.log(inc, fmt.Sprintf("%s agent unsure (%s): %s; no re-run, answer kept", title(s0.Role), why, dead))
			return best, bestS, false
		}
	}
	tried := s0 // the longest window asked so far
	for round := 1; round <= maxMoreRounds; round++ {
		why := needMoreData(best, bestN, bestS.End)
		if why == "" || inc.preempted() {
			break
		}
		sx := tried
		var ask string
		if round == 1 {
			sx.WinN = v2MaxN
			for _, wn := range []int{v2MaxN, 96, 72} { // longest window whose prompt still fits the board agent ctx
				sx.WinN = wn
				if ai, ok := r.agentPrompt(sx); ok && agentFits(ai.Prompt) {
					break
				}
			}
			if ai, ok := r.agentPrompt(sx); !ok || len(ai.Xs) <= n || !agentFits(ai.Prompt) {
				r.log(inc, fmt.Sprintf("%s agent unsure (%s): no longer window in the history, skipping to related sensors", title(s0.Role), why))
				continue
			} else {
				n = len(ai.Xs)
				sx.WinN = n
				ask = fmt.Sprintf("re-run with %s h window", hoursStr(n))
			}
		} else {
			sx.ExtraEv = relatedLines(inc, s0)
			if len(sx.ExtraEv) == 0 {
				r.log(inc, fmt.Sprintf("%s agent unsure (%s): no related sensor summaries to add", title(s0.Role), why))
				break
			}
			ask = fmt.Sprintf("re-run with %d related-sensor line(s)", len(sx.ExtraEv))
		}
		tried = sx
		ai, ok := r.agentPrompt(sx)
		if !ok {
			break
		}
		if !agentFits(ai.Prompt) {
			r.log(inc, fmt.Sprintf("%s agent unsure (%s): the larger prompt would not fit the NPU agent context, answer kept", title(s0.Role), why))
			break
		}
		sx.Evidence = ai.Evidence
		r.log(inc, fmt.Sprintf("%s agent asked for more data (%s): %s", title(s0.Role), why, ask))
		var res GenieResult
		agPrompt := ai.Prompt + AgentPrefill
		if agentTools() {
			res, agPrompt = r.runAgentTools(ctx, inc, sx, am, ai, false, false)
		} else {
			res = r.genie.Run(ctx, am, ai.Prompt+AgentPrefill, AgentPrefill, 90*time.Second, r.tokenSink(inc, sx.Ref))
			res.Text = AgentPrefill + res.Text
		}
		if !res.Cached {
			inc.NPUCalls++
		}
		call := checkAgentWin(sx, res, agPrompt, ai.Xs, ai.HVRule)
		call.CallMetrics = metricsOf(res)
		if res.Error != "" {
			r.log(inc, fmt.Sprintf("%s agent: more-data run failed (%s), answer kept", title(s0.Role), res.Error))
			break
		}
		applyConfidenceRecal(&call, sx.End, ai.Prompt)
		if !call.Valid || call.Parsed == nil {
			r.log(inc, fmt.Sprintf("%s agent: more-data answer invalid, previous answer kept", title(s0.Role)))
			continue
		}
		if call.Parsed.Confidence >= best.Parsed.Confidence {
			best, changed = call, true
			if round == 1 {
				// evidence at the longer window, so the agent, the gate and the reasoner cite the same lines
				r.applyV2Evidence(&sx)
				sx.ExtraEv = nil
			} else {
				sx.GlobalEv = nil
				for _, e := range ai.Evidence {
					sx.GlobalEv = append(sx.GlobalEv, fmt.Sprintf("ev:%s:%s:%s:%d", sx.Node, sx.Metric, e.Stat, sx.End))
				}
			}
			bestS, bestN = sx, len(ai.Xs)
			r.log(inc, fmt.Sprintf("%s agent more-data answer kept: %s / %s, confidence %.2f", title(s0.Role), call.Parsed.Pattern, call.Parsed.Status, call.Parsed.Confidence))
		} else {
			r.log(inc, fmt.Sprintf("%s agent more-data answer less confident (%.2f < %.2f): previous kept", title(s0.Role), call.Parsed.Confidence, best.Parsed.Confidence))
		}
	}
	return best, bestS, changed
}

// moreDataDead: why the more-data request cannot complete inside agent_ctx ("" = it can). The request is the longest
// window that fits (round 1) followed by the related-sensor lines on that window (round 2); when round 2 would not
// fit, round 1 is the dead "12 h re-run" of the board logs (night sweep 2026-11-27 #58). Without a longer window or
// without related lines there is nothing to pre-check (the rounds skip themselves at no NPU cost).
func moreDataDead(build func(SensorRef) (AgentInput, bool), s0 SensorRef, n int, related []string) string {
	if len(related) == 0 {
		return ""
	}
	sx := s0
	for _, wn := range []int{v2MaxN, 96, 72} { // same choice as round 1
		sx.WinN = wn
		if ai, ok := build(sx); ok && agentFits(ai.Prompt) {
			break
		}
	}
	ai, ok := build(sx)
	if !ok || len(ai.Xs) <= n || !agentFits(ai.Prompt) {
		return "" // no longer window: round 1 is skipped anyway
	}
	sx.WinN = len(ai.Xs)
	sx.ExtraEv = related
	if ai2, ok := build(sx); ok && agentFits(ai2.Prompt) {
		return ""
	}
	return fmt.Sprintf("the %s h window with %d related-sensor line(s) would not fit the NPU agent context (agent_ctx %d)",
		hoursStr(len(ai.Xs)), len(related), htpdAgentCtx())
}

// agentFits: prompt + new-token cap + htpd layout headroom must fit the agent ctx. Overflowing it is what crashed htpd on
// the board (agent_ctx 1408 -> fastrpc_mmap, 2026-11-17), so a bigger re-ask is only sent when it fits the current ctx.
func agentFits(prompt string) bool {
	return estTokens(prompt)+240+136 <= htpdAgentCtx()
}
