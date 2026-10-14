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
	"log"
	"net"
	"os"
	"os/exec"
	"path/filepath"
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
	start := func() {
		if daemonUp() {
			return
		}
		rt := g.runtime
		cmd := exec.Command(bin, "-bundle", g.Tuned.Dir, "-config", g.Tuned.Config, "-addr", daemonAddr())
		cmd.Env = append(os.Environ(),
			"LD_LIBRARY_PATH="+envOr("SCE_GENIE_LD", rt+"/qairt_2_50_libs:"+rt+"/aarch64-android:"+rt),
			"ADSP_LIBRARY_PATH="+envOr("SCE_GENIE_ADSP", rt+"/dsp_2_50;"+rt+"/dsp;"+rt+"/dsp/unsigned;/vendor/dsp/cdsp;/vendor/lib/rfsa/adsp;/system/lib/rfsa/adsp;/dsp"))
		if f, err := os.OpenFile(filepath.Join(workDir, "state", "genied.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644); err == nil {
			cmd.Stdout, cmd.Stderr = f, f
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
		for range time.Tick(60 * time.Second) {
			// never restart it underneath an in-flight NPU call
			if !g.busy.Load() {
				start()
			}
		}
	}()
}
