package main

// Client for genied, the persistent Genie dialog daemon (app/genied).
//
// Why: the CLI path pays 687-731 ms of model init on EVERY request - 18% of a 3.76 s call, and the
// largest cost left now that decode is known to be bandwidth-bound (HANDBOOK 2.15). A process that
// holds one dialog alive pays it once. Two cheaper routes were measured and are dead (2.19), so the
// daemon calls the Genie C API through cgo.
//
// This client is deliberately optional. If genied is not listening, every call falls back to
// spawning genie-t2t-run exactly as before, so the daemon is a pure addition and "don't start it"
// is a complete rollback. The backend itself stays CGO_ENABLED=0 and statically linked.
//
// Protocol (see app/genied/main.go):
//
//	-> u32 len, len bytes of prompt
//	-> single 0xFF byte at any time = abort generation
//	<- frames of u8 kind, u32 len, len bytes;  kind 0 = chunk, 1 = end, 2 = error
//
// All stop decisions stay here, in answerScanner, shared with the CLI path - the daemon knows
// nothing about our JSON schema.

import (
	"context"
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"strings"
	"sync/atomic"
	"time"
)

const (
	daemonFrameChunk = 0
	daemonFrameEnd   = 1
	daemonFrameError = 2
	daemonAbortByte  = 0xFF
)

// daemonDownUntil suppresses dial attempts for a while after a failure, so a request does not pay
// a connect timeout per call when the daemon simply is not running.
var daemonDownUntil atomic.Int64

func daemonAddr() string { return envOr("SCE_GENIE_DAEMON", "127.0.0.1:8777") }

// daemonEnabled reports whether we should try the daemon at all. Default on; set
// SCE_GENIE_DAEMON=off to force the CLI path.
func daemonEnabled() bool { return !strings.EqualFold(daemonAddr(), "off") }

func daemonDial() (net.Conn, error) {
	if !daemonEnabled() {
		return nil, fmt.Errorf("daemon disabled")
	}
	if time.Now().UnixMilli() < daemonDownUntil.Load() {
		return nil, fmt.Errorf("daemon marked down")
	}
	c, err := net.DialTimeout("tcp", daemonAddr(), 300*time.Millisecond)
	if err != nil {
		// back off for 30 s; a restarted daemon is picked up after that without restarting us
		daemonDownUntil.Store(time.Now().Add(30 * time.Second).UnixMilli())
		return nil, err
	}
	return c, nil
}

// execViaDaemon runs one prompt against the persistent dialog. Its contract matches
// GenieRunner.exec: same answer text, same stats, same early-stop behaviour.
func (g *GenieRunner) execViaDaemon(ctx context.Context, prompt, prefill string,
	timeout time.Duration, onToken func(string)) (string, streamStats, error) {

	var st streamStats
	c, err := daemonDial()
	if err != nil {
		return "", st, err
	}
	defer c.Close()

	dl := time.Now().Add(timeout)
	if d, ok := ctx.Deadline(); ok && d.Before(dl) {
		dl = d
	}
	c.SetDeadline(dl)

	body := []byte(strings.TrimPrefix(prompt, "<|begin_of_text|>")) // same BOS rule as the CLI path
	hdr := make([]byte, 4)
	binary.BigEndian.PutUint32(hdr, uint32(len(body)))
	if _, err := c.Write(hdr); err != nil {
		return "", st, err
	}
	if _, err := c.Write(body); err != nil {
		return "", st, err
	}

	scan := newAnswerScanner(prefill, onToken)
	t0 := time.Now()
	var firstTok time.Time

	fh := make([]byte, 5)
	for {
		if _, err := io.ReadFull(c, fh); err != nil {
			if err == io.EOF || err == io.ErrUnexpectedEOF {
				break
			}
			return scan.Done(), st, err
		}
		kind, n := fh[0], binary.BigEndian.Uint32(fh[1:])
		if n > 1<<20 {
			return scan.Done(), st, fmt.Errorf("daemon frame too large: %d", n)
		}
		payload := make([]byte, n)
		if n > 0 {
			if _, err := io.ReadFull(c, payload); err != nil {
				return scan.Done(), st, err
			}
		}
		switch kind {
		case daemonFrameEnd:
			goto done
		case daemonFrameError:
			return scan.Done(), st, fmt.Errorf("daemon: %s", payload)
		case daemonFrameChunk:
			chunk := string(payload)
			if firstTok.IsZero() && strings.TrimSpace(chunk) != "" {
				firstTok = time.Now()
				st.ttftMs = float64(firstTok.Sub(t0).Microseconds()) / 1000
			}
			st.tokens++
			if scan.feed(chunk) {
				st.early = true
				st.trimmed = scan.Trimmed
				// tell the daemon to stop; it aborts the in-flight query and keeps the dialog
				c.Write([]byte{daemonAbortByte})
				goto done
			}
		}
	}
done:
	if !firstTok.IsZero() {
		st.genSec = time.Since(firstTok).Seconds()
	}
	out := strings.TrimSpace(scan.Done())
	if out == "" {
		return "", st, fmt.Errorf("daemon returned no answer")
	}
	trace("daemon: answered in %v (early=%v trimmed=%v)", time.Since(t0), st.early, st.trimmed)
	return out, st, nil
}

// daemonStatus is a one-line health note for /api/status, so the dashboard can show whether the
// fast path is actually in use rather than silently falling back.
func daemonStatus() string {
	if !daemonEnabled() {
		return "disabled"
	}
	c, err := net.DialTimeout("tcp", daemonAddr(), 200*time.Millisecond)
	if err != nil {
		return "not running (per-call CLI path)"
	}
	c.Close()
	return "running at " + daemonAddr()
}
