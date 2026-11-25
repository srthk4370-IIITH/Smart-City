package main

// Push-to-talk speech-to-text for the chat: whisper.cpp tiny.en (whisper-cli) on the board CPU, never the NPU.
// POST /api/chat/voice (16 kHz mono 16-bit WAV, <= 2 MB / ~30 s) -> {"text": "..."}. Audio is never stored.

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

const (
	voiceMaxBytes = 2 << 20
	voiceTimeout  = 30 * time.Second
)

var errVoiceUnavailable = errors.New("voice not available")

// voiceRunner transcribes a WAV file; replaced by a fake in tests.
type voiceRunner func(ctx context.Context, wavPath string) (string, error)

var (
	voiceMu  sync.Mutex // one transcription at a time
	voiceRun voiceRunner
)

func voiceDir() string { return envOr("SCE_VOICE_DIR", "/data/local/tmp/smart_city_edge/voice") }

func whisperRun(ctx context.Context, wav string) (string, error) {
	dir := voiceDir()
	bin, model := filepath.Join(dir, "whisper-cli"), filepath.Join(dir, "ggml-tiny.en.bin")
	for _, f := range []string{bin, model} {
		if _, err := os.Stat(f); err != nil {
			return "", errVoiceUnavailable
		}
	}
	ctx, cancel := context.WithTimeout(ctx, voiceTimeout)
	defer cancel()
	args := []string{"-n", "19", bin, "-m", model, "-f", wav, "-t", "2", "-l", "en", "-nt", "-np"}
	name := "nice"
	if _, err := exec.LookPath("nice"); err != nil { // toybox has nice on Android; fall back to no nice
		name, args = bin, args[2:]
	}
	var out bytes.Buffer
	cmd := exec.CommandContext(ctx, name, args...)
	cmd.Stdout = &out
	if err := cmd.Run(); err != nil {
		if ctx.Err() != nil {
			return "", errors.New("voice timed out")
		}
		return "", errVoiceUnavailable
	}
	return cleanTranscript(out.String()), nil
}

var voiceNoise = regexp.MustCompile(`[\[\(][^\]\)]*[\]\)]`) // [BLANK_AUDIO], (music) ...

func cleanTranscript(s string) string {
	s = voiceNoise.ReplaceAllString(s, " ")
	return strings.Join(strings.Fields(s), " ")
}

func (s *Server) voiceRoutes(mux *http.ServeMux) {
	mux.HandleFunc("/api/chat/voice", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST a 16 kHz mono WAV", 405)
			return
		}
		b, err := io.ReadAll(io.LimitReader(r.Body, voiceMaxBytes+1))
		if err != nil || len(b) > voiceMaxBytes {
			http.Error(w, "audio too long (max about 30 s)", 413)
			return
		}
		if len(b) < 44 || string(b[:4]) != "RIFF" || string(b[8:12]) != "WAVE" {
			http.Error(w, "need a WAV file", 400)
			return
		}
		if !voiceMu.TryLock() {
			http.Error(w, "voice not available: busy, try again", 503)
			return
		}
		defer voiceMu.Unlock()
		f, err := os.CreateTemp("", "voice-*.wav")
		if err != nil {
			http.Error(w, "voice not available", 503)
			return
		}
		defer os.Remove(f.Name())
		_, werr := f.Write(b)
		f.Close()
		if werr != nil {
			http.Error(w, "voice not available", 503)
			return
		}
		run := voiceRun
		if run == nil {
			run = whisperRun
		}
		text, err := run(r.Context(), f.Name())
		if err != nil {
			http.Error(w, err.Error(), 503)
			return
		}
		writeJSON(w, map[string]any{"text": text})
	})
}
