package main

// answerScanner owns every decision about when an answer is finished and what the caller is
// allowed to see. It exists so the CLI path (GenieRunner.exec) and the daemon path
// (execViaDaemon) share ONE copy of that logic.
//
// There are two reasons to stop generating early:
//
//   - the JSON object the prefill opened has closed. Nothing useful follows it; the fine-tuned
//     model emits EOS straight after `}` anyway, so this mostly matters for the base model.
//   - the model is about to write the `action` field, which policy.go overwrites unconditionally
//     with ActionOf(cause, status). Those tokens are pure latency (HANDBOOK 2.18).
//
// The second case is why the text is accumulated in a []byte rather than a strings.Builder: the
// cut point is the comma BEFORE `"action"`, which has already been absorbed by the time we can
// recognise the key. A builder cannot give those bytes back - that was the defect that kept this
// optimisation on the shelf. For the same reason the token stream is held back by trimHoldback
// bytes, so the dashboard is never shown text that is then retracted.

type answerScanner struct {
	js      jsonScanner
	ts      *trailScanner // nil when the action trim is off
	prefill string

	gen     []byte
	emitted int
	onToken func(string)

	Trimmed bool // generation was cut short of the action field
	Closed  bool // the JSON object closed on its own
}

func newAnswerScanner(prefill string, onToken func(string)) *answerScanner {
	a := &answerScanner{prefill: prefill, onToken: onToken}
	// the object starts inside the prefill (the assistant turn already holds `{"pattern": "`)
	a.js.feed(prefill)
	// ONLY agent calls may be trimmed. policy.go derives `action` from (cause, status) for an agent
	// finding, so those tokens are waste - but checkReport does NOT derive it for the synthesizer /
	// Mode 2 report, where the model's action is the real output. Trimming there would hand the
	// policy gate an empty action and fail the report ("action '' not whitelisted"). The agent
	// prefill is the discriminator.
	if trimAction() && prefill == AgentPrefill {
		a.ts = newTrailScanner()
		a.ts.feed(prefill, trimStopKey) // prime depth and key state with the prefilled part
	}
	return a
}

// feed consumes one chunk of generated text. It reports done=true when generation should stop.
func (a *answerScanner) feed(chunk string) (done bool) {
	if at := a.js.feed(chunk); at >= 0 && a.prefill != "" {
		a.gen = append(a.gen, chunk[:at]...)
		a.Closed = true
		a.flush(true)
		return true
	}
	a.gen = append(a.gen, chunk...)
	if a.ts != nil {
		// the scanner reports an absolute index over prefill+generated text; rebase onto gen
		if cut := a.ts.feed(chunk, trimStopKey); cut >= 0 {
			if g := cut - len(a.prefill); g >= 0 && g <= len(a.gen) {
				a.gen = append(a.gen[:g], '}')
				a.Trimmed = true
				a.flush(true)
				return true
			}
		}
	}
	a.flush(false)
	return false
}

// flush hands onToken every byte that can no longer be retracted.
func (a *answerScanner) flush(force bool) {
	end := len(a.gen)
	if !force {
		end -= trimHoldback
	}
	if end > a.emitted {
		if a.onToken != nil {
			a.onToken(string(a.gen[a.emitted:end]))
		}
		a.emitted = end
	}
}

// Done releases anything the holdback was still sitting on and returns the answer.
func (a *answerScanner) Done() string {
	a.flush(true)
	return string(a.gen)
}
