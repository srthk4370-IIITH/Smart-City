package main

// Safe decisions (owner 2026-11-19, "Undo/reopen + safe dismiss"):
//   - the last decision (acknowledge, approve all, close, dismiss) can be undone for 10 minutes: POST {id}/undo;
//   - a CRITICAL incident cannot be dismissed without a second confirmation flag in the request (confirm_critical);
//   - a dismissal made by one person is "unconfirmed": it stays out of the AI's retrieval memory until a second,
//     different person confirms it: POST {id}/confirm_dismiss;
//   - reopen needs a reason (POST {id}/reopen, polish_events.go Reopen).
// A critical incident may be acknowledged and decided on the rules report while the AI is still running.

import (
	"strings"
	"time"
)

const undoWindow = 10 * time.Minute

// UndoSnap is what a decision changed, enough to put the incident back.
type UndoSnap struct {
	Kind       string   `json:"kind"` // ack | approve_all | close | dismiss
	By         string   `json:"by"`
	At         int64    `json:"at"`
	Until      int64    `json:"until"` // wall unix: the undo is possible until then
	EventsAt   int      `json:"events_at"`
	Workflow   string   `json:"workflow"`
	Owner      string   `json:"owner,omitempty"`
	AckedAt    int64    `json:"acked_at,omitempty"`
	NeedsSince int64    `json:"needs_since,omitempty"`
	Reminded   bool     `json:"reminded,omitempty"`
	Approval   string   `json:"approval,omitempty"`
	ApprovalNt string   `json:"approval_note,omitempty"`
	Outcome    string   `json:"outcome,omitempty"`
	OutcomeNt  string   `json:"outcome_note,omitempty"`
	ClosedAt   int64    `json:"closed_at,omitempty"`
	ClosedBy   string   `json:"closed_by,omitempty"`
	Unconf     bool     `json:"unconfirmed,omitempty"`
	Accepted   []string `json:"accepted_steps,omitempty"`
}

// criticalOnRulesReport: a critical incident whose analysis still runs but whose rules report is already there.
func criticalOnRulesReport(inc *Incident) bool {
	return normSeverity(inc.Severity) == "critical" && inc.Final != nil && inc.Final.Parsed != nil
}

func isCritical(inc *Incident) bool {
	return normSeverity(inc.Severity) == "critical"
}

// takeUndoLocked records the state before a decision. Caller holds r.mu and calls setUndoEventsLocked after it
// appended the decision's own event.
func takeUndoLocked(inc *Incident, kind, by string) *UndoSnap {
	now := wfNow()
	return &UndoSnap{Kind: kind, By: by, At: now.Unix(), Until: now.Add(undoWindow).Unix(),
		Workflow: wfOf(inc), Owner: inc.Owner, AckedAt: inc.AckedAt, NeedsSince: inc.NeedsSince, Reminded: inc.Reminded,
		Approval: inc.Approval, ApprovalNt: inc.ApprovalNote, Outcome: inc.Outcome, OutcomeNt: inc.OutcomeNote,
		ClosedAt: inc.ClosedAt, ClosedBy: inc.ClosedBy, Unconf: inc.DismissUnconfirmed}
}

// Undo puts the incident back as it was before the last decision, within 10 minutes and only if nobody else has
// acted on it since.
func (r *Reasoner) Undo(id, op string) (*Incident, error) {
	op, err := cleanOperator(op)
	if err != nil {
		return nil, err
	}
	inc, err := r.mutate(id, func(inc *Incident) error {
		u := inc.Undo
		if u == nil {
			return wfErr(409, "there is no decision to undo")
		}
		if wfNow().Unix() > u.Until {
			inc.Undo = nil
			return wfErr(409, "the 10-minute undo window is over - reopen the incident with a reason instead")
		}
		for _, e := range inc.Events[min(u.EventsAt, len(inc.Events)):] {
			if e.Actor != "system" && e.Actor != "reasoner" {
				return wfErr(409, "someone has acted on this incident since - it cannot be undone any more")
			}
		}
		inc.Workflow, inc.Owner, inc.AckedAt, inc.NeedsSince, inc.Reminded = u.Workflow, u.Owner, u.AckedAt, u.NeedsSince, u.Reminded
		inc.Approval, inc.ApprovalNote, inc.Outcome, inc.OutcomeNote = u.Approval, u.ApprovalNt, u.Outcome, u.OutcomeNt
		inc.ClosedAt, inc.ClosedBy, inc.DismissUnconfirmed = u.ClosedAt, u.ClosedBy, u.Unconf
		for i := range inc.Steps {
			for _, sid := range u.Accepted {
				if inc.Steps[i].ID == sid {
					inc.Steps[i].Accepted = false
				}
			}
		}
		kind := u.Kind
		inc.Undo = nil
		inc.event(op, "undone", "", "", "", "undid: "+kind)
		return nil
	})
	if err == nil {
		r.retRefresh(inc)
	}
	return inc, err
}

// retRefresh brings the retrieval memory in line with an incident whose dismissal status changed.
func (r *Reasoner) retRefresh(inc *Incident) {
	r.mu.RLock()
	unconf := inc.DismissUnconfirmed
	r.mu.RUnlock()
	if unconf {
		r.ret.remove(inc.ID)
		return
	}
	r.mu.RLock()
	r.ret.add(inc)
	r.mu.RUnlock()
}

// CloseChecked is what the HTTP layer calls: Close plus the second confirmation for a critical dismissal.
func (r *Reasoner) CloseChecked(id, op, outcome, note string, dismiss, confirmCritical bool) (*Incident, error) {
	if (dismiss || outcome == "false_alarm" || outcome == "no_action_needed") && !confirmCritical {
		r.mu.RLock()
		var crit bool
		for _, i := range r.incidents {
			if i.ID == id {
				crit = isCritical(i)
			}
		}
		r.mu.RUnlock()
		if crit {
			return nil, wfErr(409, "confirm_required: this is a CRITICAL incident - dismissing it needs a second confirmation (send confirm_critical=true)")
		}
	}
	inc, err := r.Close(id, op, outcome, note, dismiss)
	if err == nil {
		r.retRefresh(inc)
	}
	return inc, err
}

// ConfirmDismiss: a second person (not the one who dismissed) confirms the dismissal; it then counts as memory.
func (r *Reasoner) ConfirmDismiss(id, op string) (*Incident, error) {
	op, err := cleanOperator(op)
	if err != nil {
		return nil, err
	}
	inc, err := r.mutate(id, func(inc *Incident) error {
		if !inc.DismissUnconfirmed {
			return wfErr(409, "this incident has no unconfirmed dismissal")
		}
		if strings.EqualFold(op, inc.ClosedBy) {
			return wfErr(409, "a second person must confirm the dismissal (it was made by %s)", inc.ClosedBy)
		}
		inc.DismissUnconfirmed = false
		inc.event(op, "dismiss_confirmed", "", inc.Outcome, "", "dismissal confirmed")
		return nil
	})
	if err == nil {
		r.retRefresh(inc)
	}
	return inc, err
}

// runningBlocksDecision: approve / dismiss must wait for the report, except a critical on its rules report.
func (r *Reasoner) runningBlocksDecision(inc *Incident) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return inc.State == "running" && !criticalOnRulesReport(inc)
}

// undoUntil: wall unix until which the last decision can be undone (0 = nothing to undo). Caller holds r.mu.
func undoUntil(inc *Incident) int64 {
	if inc.Undo != nil && inc.Undo.Until > wfNow().Unix() {
		return inc.Undo.Until
	}
	return 0
}

func undoKind(inc *Incident) string {
	if undoUntil(inc) > 0 {
		return inc.Undo.Kind
	}
	return ""
}
