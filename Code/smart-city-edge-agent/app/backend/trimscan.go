// Wired into GenieRunner.exec behind SCE_TRIM_ACTION=1 (default off until measured on device).
//
// History: the first attempt (2026-10-14) was NOT wired in because the streaming implementation had
// a real defect - when `, "action"` straddled a stdout read boundary, `gen` had already absorbed the
// comma, the cut index went negative, and the output ended as `... "confidence": 0.85, "action}`,
// which is invalid JSON. The fix is two-part and now lives in genie.go:
//   - an accumulator that supports retroactive truncation (a []byte, not a strings.Builder), so the
//     comma can be removed after the fact;
//   - a trimHoldback-byte delay on the token stream, so the UI is never shown text we then cut.
//
// That earlier run also measured the saving at only ~2.5 "tokens" (~0.17 s). Treat that number with
// suspicion: genie.go counts one "token" per stdout read, not per token, so it is a chunk count.
// Genie's own --profile (app/tools/bench_device.sh) is the source of truth.

package main

import (
	"os"
	"strings"
)

const (
	// trimStopKey is the field the backend derives rather than consumes: policy.go always replaces
	// the model's action with ActionOf(cause, status), so every token spent emitting it is wasted.
	trimStopKey = "action"
	// trimHoldback is how many bytes of generated text are withheld from onToken. It must exceed
	// the longest string between the cut point and the point of detection, i.e. `, "action"` plus
	// any whitespace a chunk boundary can land in.
	trimHoldback = 16
)

// ON by default. Measured 2026-10-14 through the real app: 3838.9 -> 3640.1 ms per agent call
// (~199 ms, 58 -> 55 stdout chunks), and 14/14 findings valid across all five roles and the
// patterns stable / spike / flatline / throttling / exponential_increase / step_decrease / vacant,
// including status sensor_fault. Every raw output still ends with a clean `}`. A code default, not
// an env var, because the Android watchdog restarts the backend without our environment.
// Set SCE_TRIM_ACTION=0 to let the model generate the field again.
func trimAction() bool { return os.Getenv("SCE_TRIM_ACTION") != "0" }

// trailScanner finds the point in a streamed JSON object where a named top-level key begins, so
// generation can be stopped before a field we are going to discard anyway.
//
// Why: `action` is a deterministic function of (cause, status) - the same mapping that produced the
// training targets - and policy.go now always derives it (measured: 0.778 generated vs 0.815 derived
// on the 54-window set). Every token the model spends emitting `, "action": "inspect_ventilation"`
// is therefore pure latency: roughly 10 tokens, ~0.43 s at 23 tok/s, ~2 s on a 5-call incident.
//
// The scanner only fires on a key at object depth 1 that is outside any string, so an occurrence of
// the word inside an observation ("...check the action log...") cannot trigger it. On a hit it
// reports the index of the comma that introduced the key, so the caller can truncate there and close
// the object with "}".
type trailScanner struct {
	depth        int
	inStr, esc   bool
	started      bool
	inKey        bool
	key          strings.Builder
	lastComma    int // index of the most recent depth-1 comma, -1 if none yet
	afterColon   bool
	consumed     int // total bytes fed so far, so indices are absolute across chunks
}

func newTrailScanner() *trailScanner { return &trailScanner{lastComma: -1} }

// feed returns cutAt >= 0 when the named key starts a new top-level field; cutAt is the absolute
// index of the comma preceding it. Returns -1 otherwise.
func (t *trailScanner) feed(s, stopKey string) (cutAt int) {
	for i := 0; i < len(s); i++ {
		abs := t.consumed + i
		c := s[i]

		if t.inStr {
			switch {
			case t.esc:
				t.esc = false
			case c == '\\':
				t.esc = true
			case c == '"':
				t.inStr = false
				if t.inKey {
					t.inKey = false
					// a string that closes at depth 1 and is not a value is a key
					if t.depth == 1 && !t.afterColon && t.key.String() == stopKey && t.lastComma >= 0 {
						t.consumed += len(s)
						return t.lastComma
					}
				}
			default:
				if t.inKey {
					t.key.WriteByte(c)
				}
			}
			continue
		}

		switch c {
		case '"':
			t.inStr = true
			if t.depth == 1 && !t.afterColon {
				t.inKey = true
				t.key.Reset()
			}
		case '{', '[':
			t.depth++
			t.started = true
			t.afterColon = false
		case '}', ']':
			t.depth--
			t.afterColon = false
		case ':':
			if t.depth == 1 {
				t.afterColon = true
			}
		case ',':
			if t.depth == 1 {
				t.lastComma = abs
				t.afterColon = false
			}
		}
	}
	t.consumed += len(s)
	return -1
}
