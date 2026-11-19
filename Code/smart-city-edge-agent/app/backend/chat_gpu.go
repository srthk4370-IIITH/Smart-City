package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync/atomic"
	"time"
)

// Chat on the board GPU (owner 2026-11-04): the 2B rsn_v3 chat model runs in its own llama.cpp llama-server
// (OpenCL, resident, started by a board-side script), the 4B reports stay on the NPU (htpd). Profile key chat_url
// (or SCE_CHAT_URL), e.g. http://127.0.0.1:8090; unset = every chat call goes to htpd exactly as before.
//
// The prompt is byte-identical to the one htpd gets (htpd's "prefix" is only a cache hint: the prompt already starts
// with it). htpd decodes chat greedily and stops at EOG only (no stop strings), which llama-server does by default.
// Any GPU failure falls back to htpd for that call (chat must never break) and skips the GPU for chatGPUBackoff.

const (
	chatGPUTimeout = 60 * time.Second // worst call on the board: cold header prefill ~15 s + 220 tokens at ~8 t/s
	chatGPUWarmGap = 30 * time.Second // keep-warm ping spacing on the GPU (see chatStore.Warm)
	chatGPUBackoff = 60 * time.Second // after a failure, chat uses htpd for this long before trying the GPU again
)

func chatURL() string { return strings.TrimSpace(reasonerProfile("chat_url", "SCE_CHAT_URL")) }

// chatGPULabel: the engine badge of a chat_url answer. Profile key chat_device (or SCE_CHAT_DEVICE) names where the
// llama-server runs: "gpu" (default, Adreno OpenCL) or "cpu" (board 2026-11-04: the hybrid 2B decodes at ~25 t/s on 6
// CPU cores vs ~9 t/s on the GPU, gpu/tune/TUNE.md). The badge must say the truth in the demo.
func chatGPULabel() string {
	d := strings.ToLower(strings.TrimSpace(reasonerProfile("chat_device", "SCE_CHAT_DEVICE")))
	if d == "" {
		d = "gpu"
	}
	return "qwen3.5-2b rsn_v3 (" + d + ")"
}

// chatGPUDownUntil: unix nanoseconds until which the GPU server is treated as down.
var chatGPUDownUntil atomic.Int64

// chatGPUUp: chat_url set and no recent failure (the chat then does not wait for the NPU).
func chatGPUUp() bool { return chatURL() != "" && time.Now().UnixNano() >= chatGPUDownUntil.Load() }

// chatGPULLM: llama-server /completion first, htpd (beforeNPU first, when set) on any error.
type chatGPULLM struct {
	url, prefix string
	beforeNPU   func(ctx context.Context) error // waits for the NPU before a fallback call (incident analysis first)
	used        string                          // engine label of the last call
}

func (l *chatGPULLM) Name() string { return chatGPULabel() }

func chatGPURequest(prompt string, maxNew int) map[string]any {
	return map[string]any{"prompt": prompt, "n_predict": maxNew, "temperature": 0, "top_k": 1,
		"cache_prompt": true, "stream": false}
}

func (l *chatGPULLM) Complete(ctx context.Context, prompt string, maxNew int, onPiece func(string)) (string, CallMetrics, error) {
	if time.Now().UnixNano() >= chatGPUDownUntil.Load() {
		text, m, err := l.gpu(ctx, prompt, maxNew)
		if err == nil {
			l.used = chatGPULabel()
			if onPiece != nil && text != "" {
				onPiece(text)
			}
			return text, m, nil
		}
		if ctx.Err() != nil {
			return "", CallMetrics{}, ctx.Err()
		}
		chatGPUDownUntil.Store(time.Now().Add(chatGPUBackoff).UnixNano())
		log.Printf("chat: GPU llama-server %s failed (%v) - falling back to htpd for %v", l.url, err, chatGPUBackoff)
	}
	if l.beforeNPU != nil {
		if err := l.beforeNPU(ctx); err != nil {
			return "", CallMetrics{}, err
		}
	}
	h := htpdChatLLM{prefix: l.prefix}
	l.used = h.Name()
	return h.Complete(ctx, prompt, maxNew, onPiece)
}

func (l *chatGPULLM) gpu(ctx context.Context, prompt string, maxNew int) (string, CallMetrics, error) {
	body, _ := json.Marshal(chatGPURequest(prompt, maxNew))
	ctx, cancel := context.WithTimeout(ctx, chatGPUTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, "POST", strings.TrimRight(l.url, "/")+"/completion", bytes.NewReader(body))
	if err != nil {
		return "", CallMetrics{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return "", CallMetrics{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return "", CallMetrics{}, fmt.Errorf("HTTP %d", resp.StatusCode)
	}
	var out struct {
		Content         *string `json:"content"`
		TokensPredicted int     `json:"tokens_predicted"`
		Timings         struct {
			PromptMs    float64 `json:"prompt_ms"`
			PredictedPS float64 `json:"predicted_per_second"`
		} `json:"timings"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return "", CallMetrics{}, err
	}
	if out.Content == nil {
		return "", CallMetrics{}, fmt.Errorf("no content in the answer")
	}
	return *out.Content, CallMetrics{TTFTMs: out.Timings.PromptMs, GenTokens: out.TokensPredicted, TokensPerS: out.Timings.PredictedPS}, nil
}
