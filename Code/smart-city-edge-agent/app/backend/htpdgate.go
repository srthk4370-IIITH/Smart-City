package main

// htpd readiness gate and crash classification.
//
// Seen on the QIDK: htpd crashes on its FIRST decode after a (re)start ("ggml-hex: HTP0 buffer mapping failed ...
// fastrpc_mmap failed", then "terminating"); the supervisor restarts it ~30 s later and the second one is fine. The
// pair of starts suggests the new process maps NPU memory while the old one still holds it, and the first request
// reached a cold process. So:
//   - the supervisor waits for the previous htpd to be fully gone plus a settle delay before it launches a new one;
//   - a freshly started htpd is not "ready" until one tiny agent request returned tokens (warm-up gate); a failed
//     warm-up restarts htpd (same wait) with backoff, up to 5 tries;
//   - real calls wait (bounded) for ready instead of hitting a cold htpd;
//   - a transport failure (EOF, reset, refused, broken pipe, empty reply, process gone) is "NPU unavailable", the
//     class reason.go re-runs at the end of an incident, after htpd is ready again.

import (
	"context"
	"errors"
	"io"
	"log"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
)

var (
	htpdGateOn    atomic.Bool                 // set by superviseHtpd (the supervisor drives bring-up)
	htpdReady     atomic.Bool                 // warmed up and listening
	htpdBringHook atomic.Pointer[func() bool] // runs/awaits bring-up; true when ready
	htpdReadyWait = 90 * time.Second          // bound for a real call waiting on a restart
	htpdSettle    = 3 * time.Second           // after the old process is gone, before a new one starts
	htpdBackoff   = []time.Duration{3 * time.Second, 10 * time.Second, 30 * time.Second}
	htpdWarmTries = 5
)

// htpdMarkDown: the current htpd can no longer be trusted (crashed, killed, answered nothing).
func htpdMarkDown() { htpdReady.Store(false) }

// htpdWaitReady blocks until htpd is warmed up or max passes (or ctx ends). Gate off (genie mode, tests) = true.
func htpdWaitReady(ctx context.Context, max time.Duration) bool {
	if !htpdGateOn.Load() {
		return true
	}
	if htpdReady.Load() && htpdUp() {
		return true
	}
	htpdReady.Store(false)
	hp := htpdBringHook.Load()
	if hp == nil {
		return false
	}
	done := make(chan bool, 1)
	go func() { done <- (*hp)() }()
	t := time.NewTimer(max)
	defer t.Stop()
	select {
	case ok := <-done:
		return ok
	case <-t.C:
		return false
	case <-ctx.Done():
		return false
	}
}

// htpdTransportErr: the htpd process died, was killed, or is not there (as opposed to a timeout or a normal error).
func htpdTransportErr(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF) || errors.Is(err, syscall.ECONNRESET) ||
		errors.Is(err, syscall.ECONNREFUSED) || errors.Is(err, syscall.EPIPE) {
		return true
	}
	m := strings.ToLower(err.Error())
	for _, k := range []string{"eof", "connection reset", "connection refused", "broken pipe", "empty reply",
		"buffer mapping failed", "fastrpc_mmap", "terminating"} {
		if strings.Contains(m, k) {
			return true
		}
	}
	return false
}

// htpdEmptyOut: htpd answered but generated nothing and gave no stop reason (a dying process, not a model answer).
func htpdEmptyOut(o htpdOut) bool {
	return o.Tokens == 0 && strings.TrimSpace(o.Text) == "" && o.Stop == ""
}

// htpdBring brings htpd to "ready": running, and one tiny request answered with tokens.
type htpdBring struct {
	mu    sync.Mutex
	start func()              // supervisor start: launches htpd if none runs (waits for old exit + settle)
	up    func() bool         // listening
	pids  func() []int        // running htpd processes
	kill  func(why string)    // stop htpd and wait for exit
	warm  func() error        // one tiny agent request; nil only when it returned tokens
	sleep func(time.Duration) // test hook
	after func()              // after a successful warm-up (the optional htpd_warmup.jsonl pass)
}

func (b *htpdBring) run() bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	if htpdReady.Load() && b.up() {
		return true
	}
	htpdReady.Store(false)
	for try := 0; try < htpdWarmTries; try++ {
		if !b.up() {
			b.start()
			// a cold board loads the 2.8 GB model for minutes before the port opens
			for i := 0; i < 1200 && !b.up() && len(b.pids()) > 0; i++ {
				b.sleep(250 * time.Millisecond)
			}
		}
		var err error
		if !b.up() {
			err = errors.New("htpd not listening")
			if len(b.pids()) > 0 {
				b.kill("not listening after start")
			}
		} else {
			b.sleep(htpdSettleAfterUp)
			if err = b.warm(); err != nil {
				log.Printf("htpd: warm-up %d/%d failed: %v", try+1, htpdWarmTries, err)
				b.kill("warm-up failed: " + err.Error())
			} else {
				htpdReady.Store(true)
				log.Printf("htpd: ready after warm-up (try %d/%d)", try+1, htpdWarmTries)
				if b.after != nil {
					go b.after()
				}
				return true
			}
		}
		if try < htpdWarmTries-1 {
			w := htpdBackoff[len(htpdBackoff)-1]
			if try < len(htpdBackoff) {
				w = htpdBackoff[try]
			}
			log.Printf("htpd: restart %d/%d in %v (%v)", try+2, htpdWarmTries, w, err)
			b.sleep(w)
		}
	}
	log.Printf("htpd: not ready after %d tries - real requests will find it as it is", htpdWarmTries)
	return false
}

// htpdSettleAfterUp: htpd opens its port before its start-up (reasoner slot, NPU buffers) is done; a decode in that
// window crashed it every time on the board (fastrpc_mmap failed, 2026-11-17). Wait before the warm-up decode.
var htpdSettleAfterUp = 20 * time.Second

// htpdWarmNoDecode: the board gate - no decode (a 1-prompt warm-up batch needs its own NPU buffers and crashed htpd
// every time, 2026-11-17); readiness = port up after the settle wait. Real crashes are handled by the agent re-run.
func htpdWarmNoDecode() error { return nil }

// htpdWarmRequest: the tiny agent request of the gate. Returns nil only when tokens came back.
func htpdWarmRequest() error {
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	r, err := htpdCallRaw(ctx, "agents", []string{"Warm-up check." + AgentPrefill}, 120*time.Second,
		map[string]any{"max_new": 8}, nil)
	if err != nil {
		return err
	}
	o := r.Outputs[0]
	if o.Tokens <= 0 && strings.TrimSpace(o.Text) == "" {
		return errors.New("warm-up returned no tokens")
	}
	return nil
}

// maxNPURerun: re-runs of an agent whose NPU call failed as unavailable/crashed, per incident.
const maxNPURerun = 2
