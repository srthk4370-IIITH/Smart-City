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
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync/atomic"
	"syscall"
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

// errDaemonDied: the connection closed without an end frame - the daemon process went away.
var errDaemonDied = errors.New("genied died mid-answer")

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
	n := uint32(len(body))
	if needsLargeWindow(prompt) {
		n |= 1 << 31 // genied swaps in the large-context bundle for this call
		trace("daemon: prompt ~%d tokens needs the large context window", estTokens(prompt))
	}
	binary.BigEndian.PutUint32(hdr, n)
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
				// the protocol always ends with an end or error frame: EOF means genied died mid-answer
				return scan.Done(), st, fmt.Errorf("%w after %d tokens", errDaemonDied, st.tokens)
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

// daemonUp reports whether genied is listening right now. Used to keep batching OFF while the
// daemon holds the model: genie-app would load a SECOND copy of the model in its own process, and
// two resident contexts is exactly the configuration that hit the CDSP SMMU limit (HANDBOOK 2.12)
// and, earlier, crashed the board on RAM. With the daemon up batching is redundant anyway - every
// call already skips model init.
func daemonUp() bool {
	if !daemonEnabled() || time.Now().UnixMilli() < daemonDownUntil.Load() {
		return false
	}
	c, err := net.DialTimeout("tcp", daemonAddr(), 200*time.Millisecond)
	if err != nil {
		return false
	}
	c.Close()
	return true
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

// superviseDaemon starts genied if it is not already listening, and restarts it if it dies.
//
// Why the backend does this: the Android watchdog (EdgeService.backendStart) only ever launches
// edge-agent. If genied had to be started by hand, any service restart - a reboot, a crash, the
// heal loop - would silently drop us back to the per-call CLI, ~600-700 ms slower per call, with
// nothing visible except a number on /api/status. Owning its lifecycle here keeps the fast path up.
//
// It is still optional: if the genied binary is absent, this does nothing and every call takes the
// CLI path exactly as before.
func superviseDaemon(g *GenieRunner, workDir string) {
	bin := filepath.Join(workDir, "genied")
	if !daemonEnabled() || g.mock {
		return
	}
	if _, err := os.Stat(bin); err != nil {
		log.Printf("genied: not installed at %s, using the per-call CLI path", bin)
		return
	}
	stuck := 0
	start := func() {
		// probe the port directly: daemonUp() also honours the dial back-off and would report a
		// listening daemon as down, which used to be enough to start a second one
		if c, err := net.DialTimeout("tcp", daemonAddr(), 300*time.Millisecond); err == nil {
			c.Close()
			daemonDownUntil.Store(0)
			stuck = 0
			return
		}
		if len(geniedPids()) > 0 {
			// a genied exists but is not listening (it binds before loading, so it is wedged or
			// exiting). Never start a second one beside it; after 3 checks, kill it and start fresh.
			if stuck++; stuck < 3 {
				return
			}
			killDaemon("process alive but not listening for 3 checks")
			stuck = 0
			time.Sleep(2 * time.Second) // let the kernel release its NPU context
		}
		rt := g.runtime
		args := []string{"-bundle", g.Tuned.Dir, "-config", g.Tuned.Config, "-addr", daemonAddr()}
		if lb := largeBundle(); lb != "" {
			args = append(args, "-large-bundle", lb)
		}
		cmd := exec.Command(bin, args...)
		cmd.Env = append(os.Environ(),
			"LD_LIBRARY_PATH="+envOr("SCE_GENIE_LD", rt+"/qairt_2_50_libs:"+rt+"/aarch64-android:"+rt),
			"ADSP_LIBRARY_PATH="+envOr("SCE_GENIE_ADSP", rt+"/dsp_2_50;"+rt+"/dsp;"+rt+"/dsp/unsigned;/vendor/dsp/cdsp;/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp;/dsp"))
		logPath := filepath.Join(workDir, "state", "genied.log")
		if fi, err := os.Stat(logPath); err == nil && fi.Size() > 4<<20 {
			os.Rename(logPath, logPath+".1") // keep one previous log; the file is append-only otherwise
		}
		lf, lerr := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
		if lerr == nil {
			defer lf.Close() // the child holds its own copy; ours would leak one fd per restart
			cmd.Stdout, cmd.Stderr = lf, lf
		}
		cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true} // survive our own restarts
		if err := cmd.Start(); err != nil {
			log.Printf("genied: start failed: %v (per-call CLI path stays in use)", err)
			return
		}
		go cmd.Wait() // reap it if it exits
		// model load is ~600 ms; give it a few seconds before callers start counting on it
		for i := 0; i < 40 && !daemonUp(); i++ {
			time.Sleep(250 * time.Millisecond)
		}
		daemonDownUntil.Store(0)
		log.Printf("genied: started (pid %d), up=%v", cmd.Process.Pid, daemonUp())
	}
	start()
	go func() {
		for range time.Tick(15 * time.Second) { // one loopback dial; a dead daemon is back within ~15 s
			// never restart it underneath an in-flight NPU call
			if !g.busy.Load() {
				start()
			}
		}
	}()
}

// Context-window selection (HANDBOOK 2.32). The normal bundle is ctx 2048 - fastest, and enough for
// every agent call and ordinary synthesizer calls. A prompt that would not leave room for a full
// answer runs on the large-context bundle instead (ctx 4096, same weights, byte-identical outputs).
// Nothing is trimmed to fit; the window grows instead.
const (
	normalWindow = 2048
	maxAnswer    = 320 // max-num-tokens in the bundle config
	windowMargin = 40  // estTokens is calibrated, not exact
)

// largeBundle is the ctx-4096 bundle, or "" if the device does not have one.
func largeBundle() string {
	d := envOr("SCE_GENIE_LARGE_BUNDLE", "/data/local/tmp/genie_bundle_ft_4096")
	if _, err := os.Stat(filepath.Join(d, "smartcity_agent.json")); err != nil {
		return ""
	}
	return d
}

// needsLargeWindow reports whether a prompt plus a full answer would overflow the normal window.
func needsLargeWindow(prompt string) bool {
	// estTokens ran 4% LOW on a real 25-sensor synthesizer prompt (3258 estimated, 3400 actual), so
	// it is padded by 8% here: misjudging a prompt as "fits" would overflow the window mid-answer.
	return estTokens(prompt)*108/100+maxAnswer+windowMargin > normalWindow
}

// geniedPids lists running genied processes (by /proc comm), whatever their state.
func geniedPids() []int {
	var out []int
	ents, _ := os.ReadDir("/proc")
	for _, e := range ents {
		pid, err := strconv.Atoi(e.Name())
		if err != nil {
			continue
		}
		if b, err := os.ReadFile("/proc/" + e.Name() + "/comm"); err == nil && strings.TrimSpace(string(b)) == "genied" {
			if st, err := os.ReadFile("/proc/" + e.Name() + "/stat"); err == nil && strings.Contains(string(st), ") Z ") {
				continue // exited, waiting to be reaped: holds no NPU context
			}
			out = append(out, pid)
		}
	}
	return out
}

// daemonFailures counts consecutive daemon calls that connected but produced nothing.
var daemonFailures atomic.Int32

// killDaemon stops a genied that is resident but not answering, so the supervisor can start a
// clean one. Killing it is what frees its NPU context; until then nothing else may load a model.
func killDaemon(why string) {
	for _, pid := range geniedPids() {
		log.Printf("genied: killing pid %d (%s)", pid, why)
		syscall.Kill(pid, syscall.SIGKILL)
	}
	daemonFailures.Store(0)
	daemonDownUntil.Store(0)
}

// skipStreamed wraps onToken so the first n bytes of a re-run's stream are not shown again.
func skipStreamed(onToken func(string), n int) func(string) {
	if onToken == nil || n == 0 {
		return onToken
	}
	var acc strings.Builder
	passed := false
	return func(s string) {
		if passed {
			onToken(s)
			return
		}
		acc.WriteString(s)
		if acc.Len() > n {
			passed = true
			onToken(acc.String()[n:])
		}
	}
}
