package main

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func wavBody(n int) []byte {
	b := make([]byte, n)
	copy(b, "RIFF")
	copy(b[8:], "WAVE")
	return b
}

func voicePost(body []byte) *httptest.ResponseRecorder {
	mux := http.NewServeMux()
	(&Server{}).voiceRoutes(mux)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, httptest.NewRequest("POST", "/api/chat/voice", bytes.NewReader(body)))
	return w
}

func TestVoice(t *testing.T) {
	defer func() { voiceRun = nil }()
	voiceRun = func(ctx context.Context, p string) (string, error) { return "which sensors are critical", nil }
	if w := voicePost(wavBody(100)); w.Code != 200 || !strings.Contains(w.Body.String(), "which sensors are critical") {
		t.Fatal(w.Code, w.Body.String())
	}
	if w := voicePost(wavBody(voiceMaxBytes + 10)); w.Code != 413 {
		t.Fatal("size", w.Code)
	}
	if w := voicePost([]byte("not a wav file at all, really not a wav file....")); w.Code != 400 {
		t.Fatal("format", w.Code)
	}
	voiceRun = func(ctx context.Context, p string) (string, error) { return "", errVoiceUnavailable }
	if w := voicePost(wavBody(100)); w.Code != 503 || !strings.Contains(w.Body.String(), "voice not available") {
		t.Fatal("absent", w.Code, w.Body.String())
	}
	voiceMu.Lock()
	w := voicePost(wavBody(100))
	voiceMu.Unlock()
	if w.Code != 503 || !strings.Contains(w.Body.String(), "busy") {
		t.Fatal("busy", w.Code)
	}
}

func TestVoiceAbsentBinary(t *testing.T) {
	t.Setenv("SCE_VOICE_DIR", t.TempDir())
	if _, err := whisperRun(context.Background(), "x.wav"); err != errVoiceUnavailable {
		t.Fatal(err)
	}
	if cleanTranscript(" [BLANK_AUDIO] hello  (music) there ") != "hello there" {
		t.Fatal("clean")
	}
}
