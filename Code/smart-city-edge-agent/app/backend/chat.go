package main

// Operator chat (2026-10-29, beginner version). The reasoner rsn_v1 was trained on ~2,800 chat traces with the
// read-only chat tools (proofs/2026-10-25_reasoner_final: tools_v3.json["chat"], SYSTEM_CHAT); this file serves
// them: the same prompt (chat_header.txt = Qwen3.5 tools block rendered exactly like reasoner_v3_header.txt,
// chat_system.txt = the trained system text after its device-time line), the tool executor over the incident
// store and the live sensors (result shapes of eval/p0/tools_impl.py), a tool loop (<= 5 calls), and chat
// sessions kept in state/chats.json. Frontend: web/chat/ (a separate app on the same backend).
// NPU: one chat at a time; while an incident analysis runs, chat answers "busy" instead of delaying alerts.

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"math"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

//go:embed chat_header.txt
var chatHeader string

// chatHeader15: the 15-tool chat header the rsn_v3 models were trained with (tools_r2.json["chat"] = tools_v4 chat:
// the 9 tools above + rank_readings, current_levels, recent_incidents, open_incidents, faulty_sensors, what_if),
// rendered by the Qwen3.5 HF chat template (proofs/2026-11-02_2b_r2/tools/render_chat_header15.py); byte-identical to
// proofs/2026-11-02_2b_r2/tools/chat_header15.txt (TestChatHeader15MatchesTraining). Sent when chat_think=adaptive
// (rsn_v3); rsn_v1 (thinking off) keeps the 9-tool chat_header.txt it was trained on.
//
//go:embed chat_header15.txt
var chatHeader15 string

// chatHeaderFor: the tools block for the chat model in use.
func chatHeaderFor(adaptive bool) string {
	if adaptive && chatPromptR3() {
		return chatHeaderR3
	}
	if adaptive {
		return chatHeader15
	}
	return chatHeader
}

//go:embed chat_system.txt
var chatSystem string

// r3 (rsn_v3 4B local, proofs/2026-11-06_4b_local): the 21-tool chat header (tools_r3.json["chat"], rendered by the Qwen3.5
// HF template, byte-identical to tools/chat_header_r3.txt there) and the system rules with the fog lines. Profile key
// chat_prompt=r3 (with chat_think=adaptive) switches them on; the models trained before keep their prompts.
//
//go:embed chat_header_r3.txt
var chatHeaderR3 string

//go:embed chat_system_r3.txt
var chatSystemR3 string

func chatPromptR3() bool { return reasonerProfile("chat_prompt", "SCE_CHAT_PROMPT") == "r3" }

const chatMaxCalls, chatMaxNew, chatKeepTurns = 5, 220, 2

// chatStaticPrefix: tools + system up to the user turn. The device time is rounded to the hour so htpd's
// whole-state prefix cache is reused within the hour.
func chatStaticPrefix(now time.Time) string { return chatStaticPrefixMode(now, chatThinkAdaptive()) }

func chatStaticPrefixMode(now time.Time, adaptive bool) string {
	t := now.In(IST).Truncate(time.Hour)
	if adaptive && chatPromptR3() { // r3: 21-tool header, live fog sentence, fog rules (chat_fog.go)
		// the hour in IST (Truncate(time.Hour) works on UTC and gives IST half hours: 12:07 -> 11:30)
		l := now.In(IST)
		t := time.Date(l.Year(), l.Month(), l.Day(), l.Hour(), 0, 0, 0, IST)
		first := fmt.Sprintf("You are the operator assistant of a smart-campus edge monitor (IIIT Hyderabad) on a Qualcomm QIDK. "+
			"Device time: %s IST (%s). %s Full incident records on the device since %s.\n", t.Format("2006-01-02 15:04"), t.Weekday(),
			chatFogLine(), chatDeviceSince(now))
		if chatSiteV4() { // chat r5: + 4 site tools, SITE_RULE (chat_site.go; Phase 2)
			return chatHeaderR5 + first + chatSystemR5 + "<|im_end|>\n<|im_start|>user\n"
		}
		return chatHeaderR3 + first + chatSystemR3 + "<|im_end|>\n<|im_start|>user\n"
	}
	first := fmt.Sprintf("You are the operator assistant of a smart-campus edge monitor (IIIT Hyderabad) on a Qualcomm QIDK. "+
		"Device time: %s IST (%s). The device is offline: the fog server is unreachable.\n", t.Format("2006-01-02 15:04"), t.Weekday())
	return chatHeaderFor(adaptive) + first + chatSystem + "<|im_end|>\n<|im_start|>user\n"
}

// Chat prompt = the Qwen3.5 HF chat template (models/qwen3.5-4b/chat_template.jinja) as training renders it:
//   - earlier exchanges (before the last user question): the template drops reasoning from them, so a history answer
//     is "<|im_start|>assistant\n" + trim(answer) + "<|im_end|>\n" - no <think> block at all (thinking on or off);
//   - the user text is trimmed; tool results are "<|im_start|>user\n<tool_response>\n...\n</tool_response>" joined by "\n";
//   - assistant rounds of the current question keep their reasoning: "<|im_start|>assistant\n<think>\n" + reasoning +
//     "\n</think>\n\n" + calls; the generation prompt is chatAssistantOpen().
//
// chatThinkAdaptive selects the current-turn opening: false (rsn_v1, trained with enable_thinking=False) = the empty
// think block v3AssistantOpen; true (rsn_v3, adaptive thinking: trained with thinking on, the target either reasons
// or closes the block at once) = "<|im_start|>assistant\n<think>\n", the template's add_generation_prompt with
// thinking enabled, and the model writes the (possibly empty) reasoning and "</think>" itself. Profile key chat_think
// (or SCE_CHAT_THINK) = "adaptive" switches it on.
func chatThinkAdaptive() bool { return reasonerProfile("chat_think", "SCE_CHAT_THINK") == "adaptive" }

const chatAssistantOpenAdaptive = "<|im_start|>assistant\n<think>\n"

func chatAssistantOpen(adaptive bool) string {
	if adaptive {
		return chatAssistantOpenAdaptive
	}
	return v3AssistantOpen
}

// chatPrompt: prefix + up to chatKeepTurns earlier exchanges + the question + this question's tool rounds.
func chatPrompt(prefix string, history []ChatMsg, question string, turns []v3Turn) string {
	return chatPromptMode(prefix, history, question, turns, chatThinkAdaptive())
}

func chatPromptMode(prefix string, history []ChatMsg, question string, turns []v3Turn, adaptive bool) string {
	var b strings.Builder
	b.WriteString(prefix)
	var pairs [][2]string
	for i := 0; i+1 < len(history); i++ {
		if history[i].Role == "user" && history[i+1].Role == "assistant" && !history[i+1].Busy {
			pairs = append(pairs, [2]string{history[i].Text, history[i+1].Text})
		}
	}
	if len(pairs) > chatKeepTurns {
		pairs = pairs[len(pairs)-chatKeepTurns:]
	}
	for _, p := range pairs {
		b.WriteString(strings.TrimSpace(p[0]) + "<|im_end|>\n<|im_start|>assistant\n" + strings.TrimSpace(chatClean(p[1])) + "<|im_end|>\n<|im_start|>user\n")
	}
	open := chatAssistantOpen(adaptive)
	b.WriteString(strings.TrimSpace(question) + "<|im_end|>\n" + open)
	for _, t := range turns {
		if adaptive {
			b.WriteString(strings.TrimSpace(t.Think) + "\n</think>\n\n")
		}
		for i, c := range t.Calls {
			if i > 0 {
				b.WriteString("\n")
			}
			b.WriteString("<tool_call>\n<function=" + c.Name + ">\n")
			for _, p := range c.Params {
				b.WriteString("<parameter=" + p.K + ">\n" + p.V + "\n</parameter>\n")
			}
			b.WriteString("</function>\n</tool_call>")
		}
		b.WriteString("<|im_end|>\n<|im_start|>user\n")
		for i, r := range t.Results {
			if i > 0 {
				b.WriteString("\n")
			}
			b.WriteString("<tool_response>\n" + r + "\n</tool_response>")
		}
		b.WriteString("<|im_end|>\n" + open)
	}
	return b.String()
}

// chatThinkOf: the reasoning of one generated round (adaptive mode: the text before "</think>"; the prompt already
// opened the block).
func chatThinkOf(text string) string {
	if i := strings.Index(text, "</think>"); i >= 0 {
		return strings.TrimSpace(strings.TrimPrefix(strings.TrimSpace(text[:i]), "<think>"))
	}
	return ""
}

// htpdChatLLM: the reasoner slot without the report schema (free text, stops at EOG), with the chat prefix.
// chatLLM: the engine for chat (tests point it at a host llama-server).
// With chat_url set (chat_gpu.go) chat runs on the board GPU's llama-server and falls back to htpd on any error.
var chatLLM = func(prefix string) v3LLM {
	if u := chatURL(); u != "" {
		return &chatGPULLM{url: u, prefix: prefix}
	}
	return htpdChatLLM{prefix: prefix}
}

type htpdChatLLM struct{ prefix string }

func (htpdChatLLM) Name() string { return reasonerModelLabel() + " chat (htpd)" }

func (l htpdChatLLM) Complete(ctx context.Context, prompt string, maxNew int, onPiece func(string)) (string, CallMetrics, error) {
	if err := htpdReasonCaps(ctx); err != nil {
		return "", CallMetrics{}, err
	}
	r, err := htpdCallOpts(ctx, "reason", []string{prompt}, 3*time.Minute,
		map[string]any{"keep": true, "prefix": l.prefix, "max_new": maxNew}, func(int, string) {})
	if err != nil {
		return "", CallMetrics{}, err
	}
	if len(r.Outputs) == 0 || len(r.Reason) == 0 {
		return "", CallMetrics{}, errHtpdNoReasoner
	}
	o := r.Outputs[0]
	return o.Text, CallMetrics{TTFTMs: o.TTFTMs, GenTokens: o.Tokens}, nil
}

// ---------------------------------------------------------------- sessions

type ChatTool struct {
	Name   string `json:"name"`
	Args   string `json:"args"`
	Result string `json:"result"`
}

type ChatMsg struct {
	Role   string     `json:"role"` // user | assistant
	Text   string     `json:"text"`
	At     int64      `json:"at"`
	Ms     int64      `json:"ms,omitempty"`
	Tools  []ChatTool `json:"tools,omitempty"`
	Queued int64      `json:"queued_ms,omitempty"` // time spent waiting for the NPU before answering
	Busy   bool       `json:"busy,omitempty"`      // "the NPU is analysing an incident" (not kept as context)
	Error  bool       `json:"error,omitempty"`     // the engine failed
	Model  string     `json:"model,omitempty"`     // engine that answered (only with chat_url: GPU or the htpd fallback)
}

type ChatSession struct {
	ID      string    `json:"id"`
	Title   string    `json:"title"`
	Created int64     `json:"created"`
	Updated int64     `json:"updated"`
	Msgs    []ChatMsg `json:"messages"`
}

type chatStore struct {
	mu      sync.Mutex
	run     sync.Mutex // one chat on the NPU at a time
	path    string
	S       map[string]*ChatSession
	seq     int
	wait    string    // what the running question waits for ("" = answering)
	active  time.Time // keep the reasoner warm until then (chat page open / recent question)
	warming bool
}

func newChatStore(dir string) *chatStore {
	c := &chatStore{path: filepath.Join(dir, "state", "chats.json"), S: map[string]*ChatSession{}}
	fogInit(dir)
	if b, err := os.ReadFile(c.path); err == nil {
		var list []*ChatSession
		if json.Unmarshal(b, &list) == nil {
			for _, s := range list {
				c.S[s.ID] = s
				if n, err := strconv.Atoi(strings.TrimPrefix(s.ID, "CHAT-")); err == nil && n > c.seq {
					c.seq = n
				}
			}
		}
	}
	return c
}

func (c *chatStore) saveLocked() {
	list := c.listLocked()
	b, _ := json.Marshal(list)
	tmp := c.path + ".tmp"
	if os.WriteFile(tmp, b, 0o644) == nil {
		os.Rename(tmp, c.path)
	}
}

func (c *chatStore) listLocked() []*ChatSession {
	list := make([]*ChatSession, 0, len(c.S))
	for _, s := range c.S {
		list = append(list, s)
	}
	sort.Slice(list, func(i, j int) bool { return list[i].Updated > list[j].Updated })
	if len(list) > 100 {
		list = list[:100]
	}
	return list
}

func (c *chatStore) setWait(w string) { c.mu.Lock(); c.wait = w; c.mu.Unlock() }

// chatWarmFor: how long the reasoner is kept loaded after chat activity (page open, typing, an answer).
const chatWarmFor = 60 * time.Second

// Warm keeps the reasoner (and this hour's chat prefix cache) loaded on the NPU while someone is chatting, so a
// question skips the ~4 s model swap and the first-of-the-hour prefix prefill. htpd releases a held reasoner after
// HTPD_REASON_IDLE_MS (3 s), so a 1-token call every 2 s holds it. Never while an incident is analysed or a question
// runs; an alert's agents request still takes the NPU back at once (htpd swaps on demand, ~2.6 s).
func (c *chatStore) Warm(r *Reasoner) {
	chatFogRef.Store(r)
	c.mu.Lock()
	c.active = time.Now().Add(chatWarmFor)
	if c.warming {
		c.mu.Unlock()
		return
	}
	c.warming = true
	c.mu.Unlock()
	go func() {
		defer func() { c.mu.Lock(); c.warming = false; c.mu.Unlock() }()
		// GPU chat (chat_url): the model stays resident; a ping only keeps a llama-server context checkpoint inside the
		// static tool header. Qwen3.5 is hybrid (recurrent layers), so the cache can only resume from a checkpoint, and
		// llama-server places one ~1 micro-batch (-ub 128) before each prompt's end. The prompt's hourly time line
		// (sim clock, changes often) comes right after the header, so without a header-only prompt every question
		// re-prefilled the whole ~3100 tokens (board: 11.8-14 s). The ping is the header alone, GPU only (never the
		// NPU), every chatGPUWarmGap; each costs ~128 tokens of prefill.
		var lastGPU time.Time
		for {
			c.mu.Lock()
			until := c.active
			c.mu.Unlock()
			if time.Now().After(until) {
				return
			}
			gpu := chatGPUUp()
			if gpu && time.Since(lastGPU) < chatGPUWarmGap {
				time.Sleep(2 * time.Second)
				continue
			}
			if gpu && c.run.TryLock() {
				lastGPU = time.Now()
				ctx, cancel := context.WithTimeout(context.Background(), chatGPUTimeout)
				// then the whole hour's prefix (header + time line + system): a checkpoint ~128 tokens before the
				// user turn, so a follow-up (history after the prefix) also resumes there. Board: header ping ~0.6 s,
				// prefix ~1.3 s once the header checkpoint exists.
				g := &chatGPULLM{url: chatURL()}
				for _, p := range []string{chatHeaderFor(chatThinkAdaptive()), chatStaticPrefix(chatNowOf(r))} {
					if _, _, err := g.gpu(ctx, p, 1); err != nil {
						log.Printf("chat: GPU keep-warm failed: %v", err)
						break
					}
				}
				cancel()
				c.run.Unlock()
			} else if !gpu && r.analysingIncident() == "" && c.run.TryLock() {
				now := time.Now()
				if r.eng != nil {
					if sim, _, _ := r.eng.Snapshot(); sim > 0 {
						now = time.Unix(sim, 0)
					}
				}
				p := chatStaticPrefix(now)
				ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
				// one token after the prefix: htpd restores the prefix state from its cache (~10 ms) instead of
				// re-prefilling it (a prompt equal to the prefix bypasses the cache: board 4.9 s per ping)
				chatLLM(p).Complete(ctx, p+"Hi", 1, nil)
				cancel()
				c.run.Unlock()
			}
			time.Sleep(2 * time.Second)
		}
	}()
}

// ---------------------------------------------------------------- one question

var chatBusyErr = errors.New("busy")

// Ask runs one question in a session (new session when id is ""). It returns the session after the answer.
func (c *chatStore) Ask(ctx context.Context, r *Reasoner, id, question string) (*ChatSession, error) {
	question = strings.TrimSpace(question)
	if question == "" || len([]rune(question)) > 600 {
		return nil, errors.New("ask a question (max 600 characters)")
	}
	c.mu.Lock()
	s := c.S[id]
	if s == nil {
		c.seq++
		title := question
		if len([]rune(title)) > 60 {
			title = string([]rune(title)[:57]) + "..."
		}
		s = &ChatSession{ID: fmt.Sprintf("CHAT-%04d", c.seq), Title: title, Created: time.Now().Unix()}
		c.S[s.ID] = s
	}
	history := append([]ChatMsg(nil), s.Msgs...)
	s.Msgs = append(s.Msgs, ChatMsg{Role: "user", Text: question, At: time.Now().Unix()})
	s.Updated = time.Now().Unix()
	c.saveLocked()
	c.mu.Unlock()

	ans := c.answer(ctx, r, history, question)
	c.mu.Lock()
	s.Msgs = append(s.Msgs, ans)
	s.Updated = time.Now().Unix()
	c.saveLocked()
	out := *s
	c.mu.Unlock()
	return &out, nil
}

func (c *chatStore) answer(ctx context.Context, r *Reasoner, history []ChatMsg, question string) ChatMsg {
	chatFogRef.Store(r)
	t0 := time.Now()
	msg := ChatMsg{Role: "assistant", At: time.Now().Unix()}
	question = chatWithNode(r, chatNormalize(question)) // deploy24: "KH level 2 AC unit 24" -> its node id; deploy25: typos
	// deploy25: question types (readings, sensor health, incidents over any span, follow-ups, refusals) first
	if v, ok := (chatTools{r: r, now: chatNowOf(r)}).chatRouteV25(question, history); ok && v.Text != "" {
		msg.Text, msg.Tools, msg.Ms = v.Text, v.Tools, time.Since(t0).Milliseconds()
		return msg
	}
	// a routed question (peak, current levels, recent / open incidents, faulty sensors, what-if) needs no NPU
	// (chat_router.go): answered at once from one tool, never queued behind an incident analysis
	if text, tool, ok := (chatTools{r: r, now: chatNowOf(r)}).chatRouted(question, history); ok {
		msg.Text, msg.Tools, msg.Ms = text, []ChatTool{tool}, time.Since(t0).Milliseconds()
		return msg
	}
	// Queue, don't refuse (owner 2026-10-29): wait for the chat ahead and for any incident analysis (alerts first),
	// then answer. The UI polls /api/chat/status to show what the question is waiting for. Give up after 5 min.
	c.setWait("another question")
	deadline := time.Now().Add(5 * time.Minute)
	for !c.run.TryLock() {
		if time.Now().After(deadline) || ctx.Err() != nil {
			c.setWait("")
			msg.Text, msg.Busy = "The NPU stayed busy for 5 minutes, so I stopped waiting. Please ask again.", true
			return msg
		}
		time.Sleep(time.Second)
	}
	defer c.run.Unlock()
	// waitNPU: wait for any incident analysis (alerts first); returns the incident still running at the deadline.
	waitNPU := func(ctx context.Context) string {
		for {
			busy := r.analysingIncident()
			if busy == "" {
				c.setWait("")
				return ""
			}
			c.setWait(busy)
			if time.Now().After(deadline) || ctx.Err() != nil {
				c.setWait("")
				return busy
			}
			time.Sleep(2 * time.Second)
		}
	}
	// chat on the GPU (chat_url) does not wait for the NPU; its htpd fallback does (beforeNPU below)
	if !chatGPUUp() {
		if busy := waitNPU(ctx); busy != "" {
			msg.Text, msg.Busy = fmt.Sprintf("The AI was analysing [%s] for over 5 minutes (alerts come first), so I stopped waiting. Please ask again.", busy), true
			return msg
		}
	}
	c.setWait("")
	msg.Queued = time.Since(t0).Milliseconds()
	now := time.Now()
	if r.eng != nil {
		if sim, _, _ := r.eng.Snapshot(); sim > 0 {
			now = time.Unix(sim, 0)
		}
	}
	prefix := chatStaticPrefix(now)
	llm := chatLLM(prefix)
	gpu, _ := llm.(*chatGPULLM)
	if gpu != nil {
		gpu.beforeNPU = func(ctx context.Context) error {
			if busy := waitNPU(ctx); busy != "" {
				return fmt.Errorf("the AI was analysing [%s] for over 5 minutes", busy)
			}
			return nil
		}
	}
	tools := chatTools{r: r, now: now}
	// deploy25: the period and sensors the question names, read here, go to the model as a hint, and its tool calls
	// are held to them (chatValidateCall); its answer is checked against the tool results (chatCheckAnswer)
	guard := tools.chatGuardOf(question, history)
	modelQ := question + guard.Hint
	var turns []v3Turn
	used := 0
	seen := map[string]bool{} // tool calls made for this question (name + arguments as the model wrote them)
	for {
		prompt := chatPrompt(prefix, history, modelQ, turns)
		text, _, err := llm.Complete(ctx, prompt, chatMaxNew, nil)
		if err != nil {
			msg.Text, msg.Error = "The assistant could not run on the NPU ("+err.Error()+"). Please try again.", true
			break
		}
		calls := parseV3Calls(text)
		if len(calls) == 0 || used >= chatMaxCalls {
			msg.Text = chatClean(text)
			break
		}
		if room := chatMaxCalls - used; len(calls) > room {
			calls = calls[:room]
		}
		// a call the model already made in this question returns the same result again: drop it, and when a round
		// is only repeats, stop (board 2026-11-04, blind2 Q "pm25 sensr ... kharab hai kya?": the 2B repeated one
		// faulty_sensors call 3 times and ran out of calls after 63 s, with the same "could not find" answer)
		calls = chatNewCalls(calls, seen)
		if len(calls) == 0 {
			break
		}
		t := v3Turn{Calls: calls, Think: chatThinkOf(text)}
		for _, call := range calls {
			args := call.Args()
			res := guard.Validate(tools, call.Name, args)
			if res == "" {
				res = tools.Exec(ctx, call.Name, args)
			}
			guard.Saw(call.Name, res)
			t.Results = append(t.Results, res)
			a, _ := json.Marshal(args)
			msg.Tools = append(msg.Tools, ChatTool{Name: call.Name, Args: string(a), Result: res})
		}
		used += len(calls)
		turns = append(turns, t)
	}
	if msg.Text == "" && !msg.Error {
		msg.Text = "I could not find an answer to that on the device."
	}
	if !msg.Error {
		msg.Text = guard.Check(msg.Text, msg.Tools)
	}
	msg.Ms = time.Since(t0).Milliseconds()
	if gpu != nil {
		msg.Model = gpu.used
	}
	c.Warm(r) // a follow-up usually comes within a minute
	return msg
}

// chatNewCalls: the calls not made before in this question (name + arguments, as the model wrote them); records them.
func chatNewCalls(calls []V3Call, seen map[string]bool) []V3Call {
	var out []V3Call
	for _, c := range calls {
		a, _ := json.Marshal(c.Args()) // map keys marshal sorted
		k := c.Name + " " + string(a)
		if !seen[k] {
			seen[k] = true
			out = append(out, c)
		}
	}
	return out
}

var chatCallRe = regexp.MustCompile(`(?s)<tool_call>.*?(</tool_call>|$)|<think>.*?</think>`)

func chatClean(s string) string {
	if i := strings.LastIndex(s, "</think>"); i >= 0 { // adaptive thinking: the prompt opened the block
		s = s[i+len("</think>"):]
	}
	s = chatCallRe.ReplaceAllString(s, "")
	s = strings.ReplaceAll(s, "<|im_end|>", "")
	return strings.TrimSpace(s)
}

// analysingIncident: the id of an incident whose analysis is running ("" = the NPU is free for chat).
func (r *Reasoner) analysingIncident() string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	for i := len(r.incidents) - 1; i >= 0; i-- {
		if r.incidents[i].State == "running" {
			return r.incidents[i].ID
		}
	}
	return ""
}

// ---------------------------------------------------------------- tools (read-only)

type chatTools struct {
	r   *Reasoner
	now time.Time
}

var chatDomains = []string{"air_quality", "water", "power", "occupancy", "weather", "hvac"}

func (t chatTools) Exec(ctx context.Context, name string, args map[string]any) string {
	enc := func(v any) string { b, _ := json.Marshal(v); return string(b) }
	res, err := t.run(name, args)
	if err != nil {
		return enc(map[string]any{"error": err.Error()})
	}
	res["query_id"] = fmt.Sprintf("q%d", time.Now().UnixNano()%100000)
	return enc(res)
}

func (t chatTools) span(v any, required bool) (time.Time, time.Time, error) {
	now := t.now.In(IST)
	today := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, IST)
	tr, _ := v.(map[string]any)
	if s, ok := v.(string); ok {
		tr = map[string]any{"preset": s}
	}
	if tr == nil {
		if required {
			return now, now, errors.New(`'time' is required, e.g. {"preset": "this_year"}`)
		}
		tr = map[string]any{"preset": "all"}
	}
	if p, _ := tr["preset"].(string); p != "" {
		switch p {
		case "today":
			return today, today.AddDate(0, 0, 1), nil
		case "yesterday":
			return today.AddDate(0, 0, -1), today, nil
		case "last_24h":
			return now.Add(-24 * time.Hour), now, nil
		case "last_7d":
			return now.AddDate(0, 0, -7), now, nil
		case "this_week":
			wd := (int(today.Weekday()) + 6) % 7
			return today.AddDate(0, 0, -wd), now, nil
		case "last_30d":
			return now.AddDate(0, 0, -30), now, nil
		case "this_month":
			return time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, IST), now, nil
		case "last_month":
			first := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, IST)
			return first.AddDate(0, -1, 0), first, nil
		case "this_year":
			return time.Date(now.Year(), 1, 1, 0, 0, 0, 0, IST), now, nil
		case "last_year":
			return time.Date(now.Year()-1, 1, 1, 0, 0, 0, 0, IST), time.Date(now.Year(), 1, 1, 0, 0, 0, 0, IST), nil
		case "all":
			return time.Date(2000, 1, 1, 0, 0, 0, 0, IST), now, nil
		}
		if a, b, ok := chatPresetSpan(p, now); ok { // deploy25: "last_14d", "last_12h" ... as written
			return a, b, nil
		}
		return now, now, fmt.Errorf("unknown preset %q (use today, yesterday, last_24h, last_7d, this_week, last_30d, this_month, last_month, this_year, all, last_<N>h, last_<N>d, or from/to)", p)
	}
	parse := func(s string) (time.Time, error) {
		s = strings.Replace(strings.TrimSpace(s), " ", "T", 1)
		for _, f := range []string{"2006-01-02T15:04:05", "2006-01-02T15:04", "2006-01-02", "2006-01"} {
			if x, err := time.ParseInLocation(f, s, IST); err == nil {
				return x, nil
			}
		}
		return now, fmt.Errorf("bad date %q (use YYYY-MM-DD or YYYY-MM-DDTHH:MM)", s)
	}
	a, b := time.Date(2000, 1, 1, 0, 0, 0, 0, IST), now
	var err error
	if s, _ := tr["from"].(string); s != "" {
		if a, err = parse(s); err != nil {
			return a, b, err
		}
	}
	if s, _ := tr["to"].(string); s != "" {
		if b, err = parse(s); err != nil {
			return a, b, err
		}
	}
	if !b.After(a) {
		return a, b, errors.New("'to' must be after 'from' (to is exclusive)")
	}
	return a, b, nil
}

func chatCoverage(a, b, now time.Time) map[string]any {
	if b.After(now) {
		b = now
	}
	note := "device store, fog offline"
	if _, ok, _ := fogC.State(); ok {
		note = "device store"
	}
	return map[string]any{"source": "device", "complete": true, "from": a.In(IST).Format("2006-01-02"),
		"to": b.In(IST).Format("2006-01-02 15:04"), "note": note}
}

// incident facts used by the filters
type chatInc struct {
	inc      *Incident
	at       time.Time
	label    string
	root     string
	domains  []string
	sensors  []SensorRef
	patterns map[string]string // ref -> pattern
	status   map[string]string // ref -> status
	faults   map[string]string // ref -> fault kind
	archived bool              // an index row only (archived out of the 1000 full records; chat_fog.go)
}

func (t chatTools) incidents() []chatInc {
	var arch []*Incident
	if chatPromptR3() { // r3 only: the all-time index, counts stay exact after archiving (chat_fog.go); default = deploy32
		arch = t.r.chatArchived()
	}
	t.r.mu.RLock()
	defer t.r.mu.RUnlock()
	out := make([]chatInc, 0, len(t.r.incidents)+len(arch))
	live := make(map[string]bool, len(t.r.incidents))
	for _, p := range t.r.incidents {
		live[p.ID] = true
	}
	all := t.r.incidents
	if len(arch) > 0 {
		all = make([]*Incident, 0, len(arch)+len(t.r.incidents))
		for _, p := range arch {
			if !live[p.ID] {
				all = append(all, p)
			}
		}
		all = append(all, t.r.incidents...)
	}
	for _, p := range all {
		ci := chatInc{inc: p, at: time.Unix(p.CreatedSim, 0), patterns: map[string]string{}, status: map[string]string{}, faults: map[string]string{},
			archived: !live[p.ID]}
		if p.Final != nil && p.Final.Parsed != nil && !p.Final.Preliminary {
			ci.label, ci.root = p.Final.Parsed.Label, p.Final.Parsed.RootCause
		}
		seen := map[string]bool{}
		for _, s := range p.Sensors {
			if s.Context {
				continue
			}
			ci.sensors = append(ci.sensors, s)
			if !seen[s.Role] {
				seen[s.Role] = true
				ci.domains = append(ci.domains, s.Role)
			}
			ci.patterns[s.Ref], ci.status[s.Ref] = s.Rule.Pattern, s.Rule.Status
		}
		for _, a := range p.Agents {
			if a.Valid && a.Parsed != nil {
				ci.patterns[a.Ref], ci.status[a.Ref] = a.Parsed.Pattern, a.Parsed.Status
				if a.Parsed.FaultKind != "" {
					ci.faults[a.Ref] = a.Parsed.FaultKind
				}
			}
		}
		out = append(out, ci)
	}
	return out
}

func strArg(args map[string]any, k string) string {
	s, _ := args[k].(string)
	return strings.TrimSpace(s)
}

func (t chatTools) filter(args map[string]any, requireTime bool) ([]chatInc, time.Time, time.Time, error) {
	a, b, err := t.span(args["time"], requireTime)
	if err != nil {
		return nil, a, b, err
	}
	dom, metric, node, label, pattern, approval := strArg(args, "domain"), strArg(args, "metric"), strArg(args, "node"),
		strArg(args, "label"), strArg(args, "pattern"), strArg(args, "approval")
	if dom != "" && !contains(chatDomains, dom) {
		return nil, a, b, fmt.Errorf("unknown domain %q", dom)
	}
	sevs := map[string]bool{}
	switch v := args["severity"].(type) {
	case string:
		sevs[v] = true
	case []any:
		for _, x := range v {
			if s, ok := x.(string); ok {
				sevs[s] = true
			}
		}
	}
	inj, _ := args["include_injected"].(bool)
	text := strings.ToLower(strArg(args, "text"))
	var out []chatInc
	for _, ci := range t.incidents() {
		p := ci.inc
		if ci.at.Before(a) || !ci.at.Before(b) || (p.Injected && !inj) {
			continue
		}
		if len(sevs) > 0 && !sevs[normSeverity(p.Severity)] {
			continue
		}
		if label != "" && ci.label != label {
			continue
		}
		if approval != "" && p.Approval != approval {
			continue
		}
		if wf := strArg(args, "workflow"); wf != "" && wfOf(p) != wf { // deploy24: needs_decision etc. (router follow-ups)
			continue
		}
		if dom != "" || metric != "" || node != "" || pattern != "" {
			ok := false
			for _, s := range ci.sensors {
				if (dom == "" || s.Role == dom) && (metric == "" || s.Metric == metric) &&
					(node == "" || strings.Contains(s.Node, node) || strings.Contains(strings.ReplaceAll(s.Node, "-", ""), node)) &&
					(pattern == "" || strings.Contains(ci.patterns[s.Ref], pattern)) {
					ok = true
				}
			}
			if !ok {
				continue
			}
		}
		if text != "" {
			hay := strings.ToLower(p.Title + " " + ci.root + " " + ci.label)
			miss := false
			for _, w := range strings.Fields(text) {
				miss = miss || !strings.Contains(hay, w)
			}
			if miss {
				continue
			}
		}
		out = append(out, ci)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].at.After(out[j].at) })
	return out, a, b, nil
}

func (t chatTools) run(name string, args map[string]any) (map[string]any, error) {
	ts := func(x time.Time) string { return x.In(IST).Format("2006-01-02 15:04") }
	switch name {
	case "count_incidents":
		incs, a, b, err := t.filter(args, true)
		if err != nil {
			return nil, err
		}
		res := map[string]any{"coverage": chatCoverage(a, b, t.now), "definition": "demo injections excluded"}
		g := strArg(args, "group_by")
		if g == "" || g == "none" {
			res["count"] = len(incs)
			return res, nil
		}
		cnt := map[string]int{}
		for _, ci := range incs {
			keys := map[string]bool{}
			switch g {
			case "day":
				keys[ci.at.In(IST).Format("2006-01-02")] = true
			case "week":
				y, w := ci.at.In(IST).ISOWeek()
				keys[fmt.Sprintf("%d-W%02d", y, w)] = true
			case "month":
				keys[ci.at.In(IST).Format("2006-01")] = true
			case "severity":
				keys[normSeverity(ci.inc.Severity)] = true
			case "label":
				keys[ci.label] = true
			case "approval": // router only (dismissed and approved counts in one answer)
				keys[map[bool]string{true: "none", false: ci.inc.Approval}[ci.inc.Approval == ""]] = true
			case "domain", "metric", "node", "pattern":
				for _, s := range ci.sensors {
					keys[map[string]string{"domain": s.Role, "metric": s.Metric, "node": s.Node, "pattern": ci.patterns[s.Ref]}[g]] = true
				}
			default:
				return nil, fmt.Errorf("unknown group_by %q", g)
			}
			for k := range keys {
				cnt[k]++
			}
		}
		groups := []map[string]any{}
		for k, v := range cnt {
			groups = append(groups, map[string]any{"key": k, "count": v})
		}
		sort.Slice(groups, func(i, j int) bool {
			if groups[i]["count"].(int) != groups[j]["count"].(int) {
				return groups[i]["count"].(int) > groups[j]["count"].(int)
			}
			return groups[i]["key"].(string) < groups[j]["key"].(string)
		})
		res["groups"], res["total"] = groups, len(incs)
		return res, nil
	case "find_incidents":
		incs, a, b, err := t.filter(args, true)
		if err != nil {
			return nil, err
		}
		limit := 5
		if f, ok := args["limit"].(float64); ok {
			limit = int(math.Max(1, math.Min(10, f)))
		}
		items := []map[string]any{}
		for _, ci := range incs {
			if len(items) >= limit {
				break
			}
			items = append(items, map[string]any{"id": ci.inc.ID, "time": ts(ci.at), "title": ci.inc.Title, "severity": normSeverity(ci.inc.Severity),
				"label": chatNull(ci.label), "domains": ci.domains, "approval": ci.inc.Approval, "outcome": chatNull(ci.inc.Outcome)})
		}
		return map[string]any{"items": items, "total": len(incs), "coverage": chatCoverage(a, b, t.now)}, nil
	case "get_incident":
		id := strings.ToUpper(strArg(args, "id"))
		if id == "" {
			return nil, errors.New("'id' is required")
		}
		for _, ci := range t.incidents() {
			p := ci.inc
			if p.ID != id {
				continue
			}
			sens := []map[string]any{}
			t.r.mu.RLock()
			for _, s := range p.Sensors {
				pat, st := ci.patterns[s.Ref], ci.status[s.Ref]
				if s.Context && pat == "" && st == "" { // context sensors: the rule finding (as the training store's incident_sensor rows)
					pat, st = s.Rule.Pattern, s.Rule.Status
				}
				m := map[string]any{"ref": s.Ref, "node": s.Node, "metric": s.Metric, "domain": s.Role, "flagged": !s.Context,
					"pattern": pat, "status": st}
				if f := ci.faults[s.Ref]; f != "" {
					m["fault_kind"] = f
				}
				sens = append(sens, m)
			}
			steps := []map[string]any{}
			for _, st := range p.Steps {
				steps = append(steps, map[string]any{"action": st.Action, "state": st.State, "by": st.By})
			}
			out := map[string]any{"id": p.ID, "time": ts(ci.at), "title": p.Title, "severity": normSeverity(p.Severity), "label": chatNull(ci.label),
				"root_cause": chatNull(ci.root), "sensors": sens, "approval": p.Approval, "workflow": wfOf(p), "outcome": chatNull(p.Outcome), "steps": steps,
				"injected": p.Injected, "refine_stage": p.RefineStage}
			t.r.mu.RUnlock()
			if ci.archived { // index row only: the full record is on the fog (chat_fog.go)
				return t.archivedIncident(context.Background(), args, out), nil
			}
			return out, nil
		}
		return map[string]any{"error": "no incident " + id + " on this device"}, nil
	case "sensor_faults":
		a, b, err := t.span(args["time"], true)
		if err != nil {
			return nil, err
		}
		basis := strArg(args, "basis")
		if basis != "ai" && basis != "confirmed" && basis != "replaced" {
			return nil, errors.New("basis must be ai|confirmed|replaced")
		}
		dom, fk := strArg(args, "domain"), strArg(args, "fault_kind")
		distinct := true
		if v, ok := args["distinct_sensors"].(bool); ok {
			distinct = v
		}
		type agg struct {
			Node, Metric, First, Last string
			Incs                      []string
		}
		sensors := map[string]*agg{}
		order := []string{}
		nInc := map[string]bool{}
		incs := t.incidents()
		sort.Slice(incs, func(i, j int) bool { return incs[i].at.Before(incs[j].at) })
		for _, ci := range incs {
			p := ci.inc
			if ci.at.Before(a) || !ci.at.Before(b) || p.Injected {
				continue
			}
			if basis == "confirmed" && p.Approval != "approved" && wfOf(p) != wfInProgress && wfOf(p) != wfClosed {
				continue
			}
			replaced := false
			for _, st := range p.Steps {
				replaced = replaced || (st.Action == "replace_sensor" && st.State == "done")
			}
			replaced = replaced || p.Outcome == "sensor_replaced"
			for _, s := range ci.sensors {
				if dom != "" && s.Role != dom {
					continue
				}
				if basis == "replaced" {
					if !replaced {
						continue
					}
				} else if ci.status[s.Ref] != "sensor_fault" || (fk != "" && ci.faults[s.Ref] != fk) {
					continue
				}
				k := s.Node + "|" + s.Metric
				g := sensors[k]
				if g == nil {
					g = &agg{Node: s.Node, Metric: s.Metric, First: ts(ci.at)}
					sensors[k] = g
					order = append(order, k)
				}
				g.Last = ts(ci.at)
				g.Incs = append(g.Incs, p.ID)
				nInc[p.ID] = true
			}
		}
		list := []map[string]any{}
		sort.SliceStable(order, func(i, j int) bool { return len(sensors[order[i]].Incs) > len(sensors[order[j]].Incs) })
		for _, k := range order {
			g := sensors[k]
			last := g.Incs
			if len(last) > 5 {
				last = last[len(last)-5:]
			}
			if len(list) < 10 {
				list = append(list, map[string]any{"node": g.Node, "metric": g.Metric, "first": g.First, "last": g.Last,
					"incident_count": len(g.Incs), "incidents": last})
			}
		}
		count, counted := len(sensors), "distinct sensors"
		if !distinct {
			count, counted = len(nInc), "incidents"
		}
		return map[string]any{"count": count, "basis": basis, "counted": counted, "sensors": list, "coverage": chatCoverage(a, b, t.now)}, nil
	case "get_sensor_history":
		node, metric := strArg(args, "node"), strArg(args, "metric")
		if node == "" || metric == "" {
			return nil, errors.New("'node' and 'metric' are required")
		}
		var st *SensorState
		cands := []string{}
		if t.r.eng != nil {
			_, states, _ := t.r.eng.Snapshot()
			for i := range states {
				if states[i].Node == node {
					cands = append(cands, states[i].Metric)
					if states[i].Metric == metric {
						st = &states[i]
					}
				}
			}
		}
		if st == nil {
			e := fmt.Sprintf("unknown sensor %s/%s", node, metric)
			if len(cands) > 0 {
				e += "; this node has " + strings.Join(cands, ", ")
			}
			return nil, errors.New(e)
		}
		a, b, err := t.span(args["time"], true)
		if err != nil {
			return nil, err
		}
		if b.After(t.now) {
			b = t.now
		}
		n := int(b.Sub(a) / (5 * time.Minute))
		if n > 2016 {
			n = 2016 // the engine keeps 7 days of 5-min readings
		}
		var xs []float64
		if n > 0 {
			xs = t.r.eng.HistoryAt(node, metric, b.Unix(), n)
		}
		cov := map[string]any{"source": "device", "complete": n < 2016, "from": ts(b.Add(-time.Duration(len(xs)) * 5 * time.Minute)), "to": ts(b),
			"note": "device keeps raw 5-min readings for the last 7 days"}
		if len(xs) == 0 {
			return map[string]any{"summary": []map[string]any{{"id": "H1", "text": fmt.Sprintf("no readings stored for %s %s in this period", node, metric)}},
				"resolution": "5min", "coverage": cov}, nil
		}
		dec := 1
		if metric == "pf" || metric == "ph" {
			dec = 3
		}
		r := func(x float64) string { return strconv.FormatFloat(x, 'f', dec, 64) }
		at := func(i int) string { return ts(b.Add(-time.Duration(len(xs)-1-i) * 5 * time.Minute)) }
		mn, mx, sum, jm, ji := 0, 0, 0.0, 0.0, 0
		for i, x := range xs {
			sum += x
			if x < xs[mn] {
				mn = i
			}
			if x > xs[mx] {
				mx = i
			}
			if i > 0 && math.Abs(x-xs[i-1]) > math.Abs(jm) {
				jm, ji = x-xs[i-1], i
			}
		}
		slope := 0.0
		if len(xs) > 2 {
			nn := float64(len(xs))
			xm, ym := (nn-1)/2, sum/nn
			var sxy, sxx float64
			for i, y := range xs {
				dx := float64(i) - xm
				sxy, sxx = sxy+dx*(y-ym), sxx+dx*dx
			}
			slope = sxy / sxx * 288 // per 5-min step -> per day
		}
		u := st.Unit
		lines := []string{
			fmt.Sprintf("%d 5min points from %s to %s", len(xs), at(0), at(len(xs)-1)),
			fmt.Sprintf("mean = %s %s", r(sum/float64(len(xs))), u),
			fmt.Sprintf("min = %s %s at %s", r(xs[mn]), u, at(mn)),
			fmt.Sprintf("max = %s %s at %s", r(xs[mx]), u, at(mx)),
			fmt.Sprintf("last = %s %s (%s)", r(xs[len(xs)-1]), u, at(len(xs)-1)),
			fmt.Sprintf("trend = %+.*f %s/day", dec, slope, u),
			fmt.Sprintf("largest step between points = %+.*f %s at %s", dec, jm, u, at(ji)),
		}
		sum2 := []map[string]any{}
		for i, l := range lines {
			sum2 = append(sum2, map[string]any{"id": fmt.Sprintf("H%d", i+1), "text": l})
		}
		return map[string]any{"sensor": node + " " + metric, "summary": sum2, "resolution": "5min", "coverage": cov}, nil
	case "list_sensors":
		dom, loc, status := strArg(args, "domain"), strings.ToLower(strArg(args, "location")), strArg(args, "status")
		out := []map[string]any{}
		if t.r.eng != nil {
			_, states, _ := t.r.eng.Snapshot()
			faults := t.chatFaultsNow(t.incidents())
			for _, s := range states {
				if (dom != "" && s.Role != dom) || (loc != "" && !strings.Contains(strings.ToLower(s.Node+" "+s.Location), loc)) {
					continue
				}
				st := chatLiveStatus(s, faults) // the chat tools' live status (chat_tools_v3.go), as in training
				if status != "" && st != status {
					continue
				}
				var last any
				if s.Last != nil {
					last = strings.TrimSpace(strconv.FormatFloat(chatRound(s.Metric, *s.Last), 'f', -1, 64) + " " + s.Unit)
				}
				out = append(out, map[string]any{"node": s.Node, "metric": s.Metric, "domain": s.Role, "location": s.Location, "status": st, "last": last})
			}
		}
		if len(out) > 40 {
			return map[string]any{"sensors": out[:40], "count": len(out), "note": "first 40 shown"}, nil
		}
		return map[string]any{"sensors": out, "count": len(out)}, nil
	case "domain_health":
		want := strArg(args, "domain")
		out := []map[string]any{}
		incs := t.incidents()
		for _, d := range chatDomains {
			if want != "" && d != want {
				continue
			}
			var ids []string
			worst, needs := "normal", 0
			rank := map[string]int{"critical": 3, "sensor_fault": 2, "warning": 1}
			for _, ci := range incs {
				if wfOf(ci.inc) == wfClosed || ci.inc.Injected || !contains(ci.domains, d) {
					continue
				}
				ids = append(ids, ci.inc.ID)
				if s := normSeverity(ci.inc.Severity); rank[s] > rank[worst] {
					worst = s
				}
				if wfOf(ci.inc) == wfNeeds {
					needs++
				}
			}
			n := len(ids)
			if len(ids) > 5 {
				ids = ids[:5]
			}
			if ids == nil {
				ids = []string{}
			}
			out = append(out, map[string]any{"domain": d, "worst_status": worst, "open_incidents": n, "needs_decision": needs, "open_ids": ids})
		}
		return map[string]any{"domains": out}, nil
	case "get_action_history":
		if strArg(args, "node") == "" && strArg(args, "location") != "" {
			args["node"] = args["location"]
		}
		incs, a, b, err := t.filter(map[string]any{"time": args["time"], "node": args["node"], "metric": args["metric"], "domain": args["domain"]}, false)
		if err != nil {
			return nil, err
		}
		outcome := strArg(args, "outcome")
		counts := map[string]int{}
		items := []map[string]any{}
		for _, ci := range incs {
			p := ci.inc
			if p.Outcome != "" {
				counts[p.Outcome]++
			}
			if outcome != "" && p.Outcome != outcome {
				continue
			}
			if p.Outcome == "" && wfOf(p) == wfClosed {
				continue
			}
			if len(items) < 8 {
				steps := []string{}
				for _, st := range p.Steps {
					steps = append(steps, st.Action+":"+st.State)
				}
				var sensor any
				if len(ci.sensors) > 0 {
					sensor = ci.sensors[0].Node + "/" + ci.sensors[0].Metric
				}
				items = append(items, map[string]any{"id": p.ID, "time": ts(ci.at), "sensor": sensor, "label": ci.label, "steps": steps,
					"outcome": p.Outcome, "workflow": wfOf(p)})
			}
		}
		return map[string]any{"outcome_counts": counts, "maintenance_counts": map[string]int{}, "maintenance": []any{},
			"items": items, "coverage": chatCoverage(a, b, t.now)}, nil
	case "rank_readings", "current_levels", "recent_incidents", "open_incidents", "faulty_sensors", "what_if":
		return t.runV3(name, args) // chat_tools_v3.go
	case "get_site_tree", "nodes_under", "linked_equipment", "site_status":
		return liveSiteTools(t.r).Call(name, args) // chat_site.go
	case "search_knowledge":
		if !chatPromptR3() { // default (no chat_prompt=r3) = deploy32: the stub the 9/15-tool models were trained on
			return map[string]any{"available": false, "passages": []any{},
				"note": "search_knowledge runs on the fog server, which is unreachable (device offline). No documents are available."}, nil
		}
		return t.fogTool(context.Background(), name, args) // fog first, device fallback (chat_fog.go)
	}
	if chatPromptR3() { // the r3 tools exist only with chat_prompt=r3 (21-tool header)
		switch name {
		case "fog_search_history", "fog_analytics": // fog first, device fallback (chat_fog.go)
			return t.fogTool(context.Background(), name, args)
		case "fog_status":
			return t.fogStatus(context.Background()), nil
		case "co_occurring_incidents", "recurring_issues", "compare_periods":
			return t.runLocalR3(name, args)
		}
	}
	return nil, fmt.Errorf("unknown tool %q", name)
}

// ---------------------------------------------------------------- HTTP

func (s *Server) chatRoutes(mux *http.ServeMux) {
	cs := newChatStore(s.dir)
	chatMain = cs
	mux.HandleFunc("/api/chat/warm", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST", 405)
			return
		}
		cs.Warm(s.rsn)
		writeJSON(w, map[string]any{"warm_for_s": int(chatWarmFor / time.Second)})
	})
	mux.HandleFunc("/api/chat/status", func(w http.ResponseWriter, r *http.Request) {
		cs.mu.Lock()
		w8 := cs.wait
		cs.mu.Unlock()
		writeJSON(w, map[string]any{"waiting_for": w8})
	})
	mux.HandleFunc("/api/chat/sessions", func(w http.ResponseWriter, r *http.Request) {
		cs.mu.Lock()
		list := cs.listLocked()
		type row struct {
			ID      string `json:"id"`
			Title   string `json:"title"`
			Updated int64  `json:"updated"`
			N       int    `json:"messages"`
		}
		out := []row{}
		for _, x := range list {
			out = append(out, row{x.ID, x.Title, x.Updated, len(x.Msgs)})
		}
		cs.mu.Unlock()
		writeJSON(w, out)
	})
	mux.HandleFunc("/api/chat/sessions/", func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimPrefix(r.URL.Path, "/api/chat/sessions/")
		cs.mu.Lock()
		defer cs.mu.Unlock()
		x := cs.S[id]
		if x == nil {
			http.Error(w, "no such chat", 404)
			return
		}
		if r.Method == http.MethodDelete {
			delete(cs.S, id)
			cs.saveLocked()
			writeJSON(w, map[string]any{"deleted": id})
			return
		}
		writeJSON(w, x)
	})
	mux.HandleFunc("/api/chat", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST {session, message}", 405)
			return
		}
		var body struct {
			Session string `json:"session"`
			Message string `json:"message"`
		}
		if readBody(r, &body) != nil {
			http.Error(w, "bad JSON", 400)
			return
		}
		x, err := cs.Ask(r.Context(), s.rsn, body.Session, body.Message)
		if err != nil {
			http.Error(w, err.Error(), 400)
			return
		}
		writeJSON(w, x)
	})
}
