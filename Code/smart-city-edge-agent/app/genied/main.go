// genied holds one Genie dialog alive for the life of the process and answers prompts over a
// loopback socket, so model init is paid once instead of on every request.
//
// Why this exists
// ---------------
// The backend spawns `genie-t2t-run` per request and pays 687-731 ms of model init every time -
// 18% of a 3.76 s request, and the largest remaining cost now that decode is known to be
// bandwidth-bound (HANDBOOK 2.15). Reading the Genie C++ source that ships in the SDK confirms
// dialog reuse removes it: the load happens in the engine constructor, and GenieDialog_reset only
// zeroes the KV and the token counters - there is no load()/unload() in the reset path.
//
// Two cheaper routes were measured on device and both are dead (HANDBOOK 2.19): mkfifo is refused
// by SELinux everywhere writable, and `genie-app -s /proc/self/fd/0` still waits for EOF before
// executing anything. So the C API via cgo is the only way.
//
// Why a separate daemon instead of putting cgo in the backend
// -----------------------------------------------------------
// cgo forces an Android NDK cross-compile and gives up the static binary. Keeping it in its own
// process means the backend stays CGO_ENABLED=0 and exactly as it is today, and the fallback is
// free: if the daemon is not running, GenieRunner spawns the CLI as it always has. Rollback is
// "don't start genied".
//
// Protocol (loopback TCP, length-prefixed, one query at a time)
// -------------------------------------------------------------
//
//	client -> server   u32 len, then len bytes of prompt
//	client -> server   (optional, any time during a response) a single 0xFF byte = abort
//	server -> client   frames: u8 kind, u32 len, len bytes
//	                   kind 0 = token chunk, 1 = end of answer, 2 = error text
//
// The daemon deliberately does NOT know about our JSON schema. The backend owns every stop
// decision - the closing-brace scan and the action trim - and sends the abort byte when its own
// scanner says the answer is complete. That keeps one copy of that logic, in the non-cgo code.
//
// The Genie C API is documented as NOT thread safe, so every dialog call is serialised behind one
// mutex. GenieDialog_signal is the documented exception: it is designed to be called while a query
// is in flight, which is exactly how genie-t2t-run uses it.
package main

/*
#cgo CFLAGS: -I${SRCDIR}/include
#cgo LDFLAGS: -L${SRCDIR}/lib -lGenie -ldl -lm

#include <stdlib.h>
#include "GenieCommon.h"
#include "GenieDialog.h"

// Trampoline: Genie calls this C function, which calls back into Go. Declared here because cgo
// cannot take the address of a Go function directly. The signature must match what cgo generates
// for the //export below EXACTLY - cgo drops `const`, so declaring it with const qualifiers is a
// "conflicting types" error. The cast to GenieDialog_QueryCallback_t happens at the call site.
extern void genieQueryCallback(char* response, GenieDialog_SentenceCode_t code, void* userData);

// slot travels through Genie's userData so the callback can route text to the right request when
// several dialogs are generating at once (continuous batching). It is an integer, never a Go
// pointer, which keeps this within cgo's pointer-passing rules.
static Genie_Status_t genieQuery(GenieDialog_Handle_t dlg, const char* prompt, uintptr_t slot) {
  return GenieDialog_query(dlg, prompt, GENIE_DIALOG_SENTENCE_COMPLETE,
                           (GenieDialog_QueryCallback_t)genieQueryCallback, (const void*)slot);
}
*/
import "C"

import (
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"time"
	"unsafe"
)

const (
	frameChunk = 0
	frameEnd   = 1
	frameError = 2
	abortByte  = 0xFF
)

// Per-slot output routing. With -slots 1 there is one dialog and this behaves exactly like the
// original single-sink daemon. With -slots N there are N dialogs sharing ONE engine whose scheduler
// fuses their decode steps into shared NPU passes, so N callbacks can be live at once; each one
// carries its slot index in userData and lands in its own sink.
var (
	sinkMu sync.RWMutex
	sinks  = map[uintptr]func(string){}
)

func setSink(slot uintptr, f func(string)) {
	sinkMu.Lock()
	if f == nil {
		delete(sinks, slot)
	} else {
		sinks[slot] = f
	}
	sinkMu.Unlock()
}

//export genieQueryCallback
func genieQueryCallback(response *C.char, code C.GenieDialog_SentenceCode_t, userData unsafe.Pointer) {
	if response == nil {
		return
	}
	sinkMu.RLock()
	f := sinks[uintptr(userData)]
	sinkMu.RUnlock()
	if f == nil {
		return
	}
	if s := C.GoString(response); s != "" {
		f(s)
	}
}

type dialog struct {
	h    C.GenieDialog_Handle_t
	slot uintptr
	mu   sync.Mutex // one query per dialog at a time; the pool also guarantees this
}

func newDialog(configJSON string, slot uintptr) (*dialog, error) {
	cs := C.CString(configJSON)
	defer C.free(unsafe.Pointer(cs))

	var cfg C.GenieDialogConfig_Handle_t
	if st := C.GenieDialogConfig_createFromJson(cs, &cfg); st != 0 {
		return nil, fmt.Errorf("GenieDialogConfig_createFromJson: status %d", int(st))
	}
	defer C.GenieDialogConfig_free(cfg)

	var h C.GenieDialog_Handle_t
	t0 := time.Now()
	if st := C.GenieDialog_create(cfg, &h); st != 0 {
		return nil, fmt.Errorf("GenieDialog_create: status %d", int(st))
	}
	log.Printf("dialog %d created in %v (model init is paid once, by the first dialog)", slot, time.Since(t0))
	return &dialog{h: h, slot: slot}, nil
}

// query runs one prompt. onChunk is called from the Genie callback on this goroutine's thread.
// Returns when generation ends or is aborted.
func (d *dialog) query(prompt string, onChunk func(string)) error {
	d.mu.Lock()
	defer d.mu.Unlock()

	// Genie's HTP backend keeps per-thread FastRPC state; pin so the Go scheduler cannot move us
	// mid-query.
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()

	if st := C.GenieDialog_reset(d.h); st != 0 {
		return fmt.Errorf("GenieDialog_reset: status %d", int(st))
	}

	setSink(d.slot, onChunk)
	defer setSink(d.slot, nil)

	cp := C.CString(prompt)
	defer C.free(unsafe.Pointer(cp))

	st := C.genieQuery(d.h, cp, C.uintptr_t(d.slot))
	// positive statuses are warnings, not failures: 1 = ABORTED, which is the normal result when
	// the backend stops us early because the JSON object closed
	if int(st) < 0 {
		return fmt.Errorf("GenieDialog_query: status %d", int(st))
	}
	return nil
}

// abort stops an in-flight query. Documented as safe to call concurrently with query.
func (d *dialog) abort() {
	C.GenieDialog_signal(d.h, C.GENIE_DIALOG_ACTION_ABORT)
}

func (d *dialog) free() { C.GenieDialog_free(d.h) }

func writeFrame(w io.Writer, kind byte, payload []byte) error {
	hdr := make([]byte, 5)
	hdr[0] = kind
	binary.BigEndian.PutUint32(hdr[1:], uint32(len(payload)))
	if _, err := w.Write(hdr); err != nil {
		return err
	}
	if len(payload) == 0 {
		return nil
	}
	_, err := w.Write(payload)
	return err
}

func serve(c net.Conn, d *dialog) {
	defer c.Close()

	var n uint32
	if err := binary.Read(c, binary.BigEndian, &n); err != nil {
		return
	}
	if n == 0 || n > 1<<20 {
		writeFrame(c, frameError, []byte(fmt.Sprintf("bad prompt length %d", n)))
		return
	}
	prompt := make([]byte, n)
	if _, err := io.ReadFull(c, prompt); err != nil {
		return
	}

	// Watch for the abort byte while the query runs. The read ends on its own when the handler
	// closes the connection.
	done := make(chan struct{})
	go func() {
		b := make([]byte, 1)
		for {
			if _, err := c.Read(b); err != nil {
				return
			}
			if b[0] == abortByte {
				d.abort()
				return
			}
			select {
			case <-done:
				return
			default:
			}
		}
	}()

	var werr error
	t0 := time.Now()
	err := d.query(string(prompt), func(chunk string) {
		if werr == nil {
			werr = writeFrame(c, frameChunk, []byte(chunk))
		}
	})
	close(done)

	if err != nil {
		writeFrame(c, frameError, []byte(err.Error()))
		log.Printf("query failed after %v: %v", time.Since(t0), err)
		return
	}
	if werr != nil {
		log.Printf("client went away after %v: %v", time.Since(t0), werr)
		return
	}
	writeFrame(c, frameEnd, nil)
	log.Printf("query served in %v", time.Since(t0))
}

func main() {
	var (
		bundle = flag.String("bundle", "/data/local/tmp/genie_bundle_ft", "directory holding the config and context binaries")
		config = flag.String("config", "smartcity_agent.json", "Genie dialog config, relative to -bundle")
		addr   = flag.String("addr", "127.0.0.1:8777", "loopback address to listen on")
		slots  = flag.Int("slots", 1, "dialogs sharing one batching engine; 1 = one query at a time")
	)
	flag.Parse()

	// Genie resolves ctx-bins and tokenizer.json relative to the working directory.
	if err := os.Chdir(*bundle); err != nil {
		log.Fatalf("chdir %s: %v", *bundle, err)
	}
	cfg, err := os.ReadFile(filepath.Join(*bundle, *config))
	if err != nil {
		log.Fatalf("reading config: %v", err)
	}
	cfg = daemonConfig(cfg)
	if *slots > 1 {
		cfg = batchingConfig(cfg, *slots)
	}

	// The pool: each request borrows a free dialog. With -slots 1 this is a single dialog and
	// requests are served strictly one at a time, exactly as before.
	pool := make(chan *dialog, *slots)
	for i := 0; i < *slots; i++ {
		d, err := newDialog(string(cfg), uintptr(i+1))
		if err != nil {
			log.Fatalf("creating dialog %d: %v", i+1, err)
		}
		defer d.free()
		pool <- d
	}

	ln, err := net.Listen("tcp", *addr)
	if err != nil {
		log.Fatalf("listen %s: %v", *addr, err)
	}
	log.Printf("genied %s ready on %s, bundle %s, %d slot(s)", version, *addr, *bundle, *slots)

	for {
		c, err := ln.Accept()
		if err != nil {
			log.Printf("accept: %v", err)
			continue
		}
		go func(c net.Conn) {
			d := <-pool // blocks while every slot is busy
			defer func() { pool <- d }()
			serve(c, d)
		}(c)
	}
}

// batchingConfig turns on Genie's continuous batching for N concurrent dialogs.
//
// Traced in the Genie source (QAIRT 2.50, examples/Genie/Genie/src): a dialog whose engine has
// QnnHtp "shared-engine": true is resolved through a registry keyed on the engine config, so N
// dialogs created from the same config share ONE loaded engine instead of loading N copies. Each
// dialog takes a scheduler slot, and the engine-level "batching" block (passed through by
// Engine.cpp) lets the InferenceScheduler fuse the slots' decode tokens into a single graph fire -
// the weights are read once for several tokens, which is the only lever left once decode is at the
// memory-bandwidth roof (HANDBOOK 2.15). "allow-async-init" must be true for a shared engine; our
// config already has it. A plain dialog config or genie-app cannot enable this: it needs N dialogs
// in one process, which is exactly what genied is.
func batchingConfig(raw []byte, slots int) []byte {
	var c map[string]any
	if json.Unmarshal(raw, &c) != nil {
		return raw
	}
	dlg, _ := c["dialog"].(map[string]any)
	eng, _ := dlg["engine"].(map[string]any)
	be, _ := eng["backend"].(map[string]any)
	htp, _ := be["QnnHtp"].(map[string]any)
	if htp == nil || eng == nil {
		return raw
	}
	htp["shared-engine"] = true
	htp["allow-async-init"] = true
	eng["batching"] = map[string]any{
		"max-slots":            slots,
		"mixed-prefill-decode": true, // one request's prefill can share a fire with another's decode
		"coalesce-window-us":   2000, // wait up to 2 ms for other slots to join a fire
	}
	out, err := json.Marshal(c)
	if err != nil {
		return raw
	}
	log.Printf("config: continuous batching on, %d slots sharing one engine", slots)
	return out
}

// daemonConfig adapts the shared Genie config for a LONG-LIVED process.
//
// "poll": true makes Genie's worker threads busy-wait on the NPU instead of sleeping. For the
// per-call CLI that is harmless: the process exits when the answer is done, so the spinning stops.
// In a daemon it never stops. Measured on the QIDK: genied idled at 359% CPU (four big cores pinned)
// and drove the board to 94 C, tripping the app's thermal guard so no analysis ran at all.
//
// With poll off, measured over the same 28 queries (14 prompts, forward then reverse):
//
//	poll true   28/28 identical   mean 3686 ms   idle 359% CPU
//	poll false  28/28 identical   mean 3670 ms   idle   0% CPU
//
// i.e. no measurable speed cost here (the ~5% poll benefit recorded in HANDBOOK 5 was for the CLI).
// The shared smartcity_agent.json is left untouched, because the CLI fallback still wants poll on.
func daemonConfig(raw []byte) []byte {
	var c map[string]any
	if json.Unmarshal(raw, &c) != nil {
		return raw // not ours to fix; Genie will report a malformed config itself
	}
	dlg, _ := c["dialog"].(map[string]any)
	eng, _ := dlg["engine"].(map[string]any)
	be, _ := eng["backend"].(map[string]any)
	htp, _ := be["QnnHtp"].(map[string]any)
	if htp == nil {
		return raw
	}
	if htp["poll"] == true {
		log.Printf("config: forcing \"poll\": false (a daemon must idle cold; see daemonConfig)")
	}
	htp["poll"] = false
	out, err := json.Marshal(c)
	if err != nil {
		return raw
	}
	return out
}

// version is logged at startup so a deployed daemon can be matched to its build.
const version = "2026-10-14.3-batch"
