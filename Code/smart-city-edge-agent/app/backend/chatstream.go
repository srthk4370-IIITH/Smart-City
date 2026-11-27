package main

// Chat streaming (owner 2026-11-27: "chat streaming + push UI"). The chat page sends a random stream id with its
// question; while the answer is generated the backend publishes SSE events "chat_piece" {stream, step} for each tool
// look-up and {stream, text} with the draft answer so far (thinking and tool-call text are never shown). The HTTP
// reply still carries the final, checked answer (chatGuard / chatFinish), which replaces the draft.

import (
	"context"
	"strings"
	"sync"
	"time"
)

type chatStreamKey struct{}

type chatStreamer struct {
	id   string
	pub  func(string, any)
	mu    sync.Mutex
	buf   strings.Builder
	last  time.Time
	think bool // the prompt ends inside an open <think>: nothing is visible before </think>
}

func withChatStream(ctx context.Context, id string, pub func(string, any)) context.Context {
	id = strings.TrimSpace(id)
	if id == "" || len(id) > 40 || pub == nil {
		return ctx
	}
	return context.WithValue(ctx, chatStreamKey{}, &chatStreamer{id: id, pub: pub})
}

func chatStreamOf(ctx context.Context) *chatStreamer {
	cs, _ := ctx.Value(chatStreamKey{}).(*chatStreamer)
	return cs
}

// step: one tool look-up ("Looking up sensor readings ...").
func (cs *chatStreamer) step(text string) {
	if cs == nil {
		return
	}
	cs.pub("chat_piece", map[string]any{"stream": cs.id, "step": text})
}

// begin: a new model completion starts (the draft of the previous one was a tool call or is superseded).
func (cs *chatStreamer) begin(prompt string) {
	if cs == nil {
		return
	}
	p := strings.TrimSpace(prompt)
	cs.mu.Lock()
	cs.buf.Reset()
	cs.think = strings.LastIndex(p, "<think>") > strings.LastIndex(p, "</think>")
	cs.mu.Unlock()
}

// chatVisible: the part of a raw completion a person may see now ("" while thinking or writing a tool call).
func chatVisible(raw string, thinkOpen bool) string {
	if thinkOpen {
		j := strings.LastIndex(raw, "</think>")
		if j < 0 {
			return ""
		}
		raw = raw[j+len("</think>"):]
	}
	if i := strings.Index(raw, "<think>"); i >= 0 {
		j := strings.Index(raw, "</think>")
		if j < 0 {
			return ""
		}
		raw = raw[:i] + raw[j+len("</think>"):]
	}
	t := strings.TrimSpace(raw)
	if strings.HasPrefix(t, "<tool_call>") || strings.HasPrefix(t, "{") || strings.HasPrefix(t, "[") || strings.Contains(t, "<tool_call>") {
		return ""
	}
	return t
}

// piece: one generated piece; publishes the visible draft at most every 120 ms.
func (cs *chatStreamer) piece(p string) {
	if cs == nil {
		return
	}
	cs.mu.Lock()
	cs.buf.WriteString(p)
	if time.Since(cs.last) < 120*time.Millisecond {
		cs.mu.Unlock()
		return
	}
	cs.last = time.Now()
	v := chatVisible(cs.buf.String(), cs.think)
	cs.mu.Unlock()
	if v != "" {
		cs.pub("chat_piece", map[string]any{"stream": cs.id, "text": v})
	}
}

// chatToolStep: a short human line for a tool look-up.
func chatToolStep(name string) string {
	n := strings.ReplaceAll(strings.TrimPrefix(name, "get_"), "_", " ")
	return "Looking up " + n + "..."
}
