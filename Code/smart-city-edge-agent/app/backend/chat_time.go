package main

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

// deploy25 (blind chat sweep 2026-11-01, proofs/2026-11-01_chat/VERDICT_blind.md): one time-span parser for the router
// and the model's tools. The blind set showed spans being dropped ("last 12 ghante" listed old incidents), widened
// ("since Monday 8 am" -> this week; "past 2 weeks" -> an unknown preset, then 30 days) or shifted ("those" -> another
// day). chatSpanOf reads every span form the operators used (English and Hinglish) into an absolute [from, to) at the
// device's sensor time; a period it cannot read is reported as such (Unparsed), never replaced by a wider one.

type chatSpan struct {
	From, To time.Time // [From, To), To capped at now
	Words    string    // the period in words, e.g. "in the last 12 hours"
	Future   bool      // the question asks about the future (tomorrow, next week): no data exists for it
	Unparsed string    // a period word was found but not understood ("" = none)
	now      time.Time
}

// Found: the question names a period that was read.
func (s chatSpan) Found() bool { return !s.From.IsZero() }

// Args: the tool time argument for the span.
func (s chatSpan) Args() map[string]any {
	return map[string]any{"from": s.From.In(IST).Format("2006-01-02T15:04"), "to": s.To.In(IST).Format("2006-01-02T15:04")}
}

// Describe: "in the last 12 hours (2026-10-31 05:40 to 2026-10-31 17:40)".
func (s chatSpan) Describe() string {
	to := s.To
	if !s.now.IsZero() && to.After(s.now) && s.now.After(s.From) {
		to = s.now // the window ends a minute after the device time (so the current reading counts); say "now"
	}
	return fmt.Sprintf("%s (%s to %s)", s.Words, chatTS(s.From), chatTS(to))
}

var (
	chatWeekdays = map[string]time.Weekday{"sunday": time.Sunday, "monday": time.Monday, "tuesday": time.Tuesday, "wednesday": time.Wednesday,
		"thursday": time.Thursday, "friday": time.Friday, "saturday": time.Saturday, "sun": time.Sunday, "mon": time.Monday, "tue": time.Tuesday,
		"tues": time.Tuesday, "wed": time.Wednesday, "thu": time.Thursday, "thur": time.Thursday, "thurs": time.Thursday, "fri": time.Friday, "sat": time.Saturday,
		"ravivar": time.Sunday, "somvar": time.Monday, "mangalvar": time.Tuesday, "budhvar": time.Wednesday, "guruvar": time.Thursday, "shukravar": time.Friday, "shanivar": time.Saturday}
	chatMonths = map[string]time.Month{"jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
		"jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12}
	chatNumWords = map[string]int{"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
		"eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "ninety": 90, "ek": 1, "do": 2, "teen": 3, "char": 4,
		"chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "saat": 7, "aath": 8, "das": 10, "couple": 2, "few": 3}

	chatWdRe    = `(sunday|monday|tuesday|wednesday|thursday|friday|saturday|sun|mon|tues?|wed|thur?s?|fri|sat|ravivar|somvar|mangalvar|budhvar|guruvar|shukravar|shanivar)`
	chatMonRe   = `(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)`
	chatClockRe = `(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|baje|o'?clock|hrs)?`
	chatNumRe   = `(\d{1,4}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|ninety|ek|do|teen|chaa?r|paa?nch|chhe|saat|aath|das|couple(?:\s+of)?|few)`
	chatUnitRe2 = `(minutes?|mins?|m|hours?|hrs?|h|ghante|ghanton|ghanta|ghanto|days?|din|dino|dinon|weeks?|wks?|hafte|hafton|months?|mahine|mahina)`

	chatSpanFutureRe = regexp.MustCompile(`(?i)\btomorrow\b|\bnext\s+(week|month|hour|few\s+hours|\d+\s+\w+)\b|\bkal\b[^?.!]*\b(hoga|hogi|honge|hoge|rahega|rahegi|karega|aayega|aayegi|chahiye)\b|\bforecast\b|\bwill\s+be\b|\bgoing\s+to\s+be\b|\blater\s+today\b|\btonight\b`)
	chatSpanAgoRe    = regexp.MustCompile(`(?i)\b` + chatNumRe + `\s*` + chatUnitRe2 + `\s+(ago|pehle|pahle)\b`)
	chatSpanRelRe    = regexp.MustCompile(`(?i)\b(?:in\s+the\s+|over\s+the\s+|during\s+the\s+|for\s+the\s+|within\s+the\s+)?(?:last|past|previous|prior|pichle|pichhle|picchle|recent)\s+` + chatNumRe + `\s*` + chatUnitRe2 + `\b`)
	chatSpanRelHiRe  = regexp.MustCompile(`(?i)\b` + chatNumRe + `\s*` + chatUnitRe2 + `\s+(?:mein|me|main|se|tak)\b`)
	chatSpanRel1Re   = regexp.MustCompile(`(?i)\b(?:in\s+the\s+|over\s+the\s+|during\s+the\s+|within\s+the\s+)?(?:last|past|previous|pichle|pichhle)\s+(hour|day|week|fortnight|month|year|ghanta|ghante|din|hafte|mahine)\b`)
	chatSpanFortRe   = regexp.MustCompile(`(?i)\bfortnight\b`)
	chatBetweenRe    = regexp.MustCompile(`(?i)\b(?:between|from)\s+` + chatClockRe + `\s+(?:and|to|till|until|-)\s+` + chatClockRe)
	chatSinceRe      = regexp.MustCompile(`(?i)\bsince\s+(?:last\s+)?(` + chatWdRe[1:len(chatWdRe)-1] + `|yesterday|kal|today|this\s+morning|morning|midnight|noon|\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|baje)?)\b(?:\s*(?:at\s+|,\s*)?` + chatClockRe + `)?`)
	chatAfterRe      = regexp.MustCompile(`(?i)\b(?:after|post)\s+` + chatClockRe + `|\b` + chatClockRe + `\s+(?:ke\s+baad|ke\s+bad|baad|onwards)\b`)
	chatBeforeRe     = regexp.MustCompile(`(?i)\b(?:before|until|till)\s+` + chatClockRe + `|\b` + chatClockRe + `\s+(?:se\s+pehle|ke\s+pehle|tak)\b`)
	chatDateRangeRe  = regexp.MustCompile(`(?i)\b(?:between|from)\s+(.{1,16}?)\s+(?:and|to|till|until|-)\s+(.{3,20}?)(?:[?.!,]|$|\s+(?:in|for|on|with)\b)`)
	chatDateRe1      = regexp.MustCompile(`(?i)\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?` + chatMonRe + `\b`)
	chatDateRe2      = regexp.MustCompile(`(?i)\b` + chatMonRe + `\s+(\d{1,2})(?:st|nd|rd|th)?\b`)
	chatDateRe3      = regexp.MustCompile(`\b(20\d\d)-(\d\d)-(\d\d)\b`)
	chatDateRe4      = regexp.MustCompile(`\b(\d{1,2})/(\d{1,2})\b`)
	chatOnWdRe       = regexp.MustCompile(`(?i)\b(?:on\s+|last\s+|this\s+past\s+)?` + chatWdRe + `\b`)
	chatOvernightRe  = regexp.MustCompile(`(?i)\bover\s*night\b|\blast\s+night\b|\bkal\s+raat\b|\braat\s+(ko|mein|me|bhar)\b|\bnight\s+shift\b|\bduring\s+the\s+night\b`)
	chatPartDayRe    = regexp.MustCompile(`(?i)\b(this|today'?s?|aaj|yesterday'?s?|kal)\s+(morning|afternoon|evening|night|subah|dopahar|shaam|sham|raat)\b|\b(subah|dopahar|shaam|sham)\s+(se|ko|mein|me)\b|\bthis\s+(morning|afternoon|evening)\b`)
	chatDayBeforeRe  = regexp.MustCompile(`(?i)\bday\s+before\s+yesterday\b|\bparson\b|\bparso\b`)
	chatTodayRe      = regexp.MustCompile(`(?i)\btoday\b|\baaj\b|\bso\s+far\b|\bsince\s+midnight\b`)
	chatYestRe       = regexp.MustCompile(`(?i)\byesterday\b|\bkal\b`)
	chatThisWeekRe   = regexp.MustCompile(`(?i)\bthis\s+week\b|\bis\s+hafte\b`)
	chatLastWeekRe   = regexp.MustCompile(`(?i)\b(last|past|previous|pichle|pichhle)\s+week\b|\bweek\s+so\s+far\b`)
	chatWeekBeforeRe = regexp.MustCompile(`(?i)\b(the\s+)?week\s+before(\s+that|\s+last)?\b|\bprevious\s+week\b`)
	chatThisMonthRe  = regexp.MustCompile(`(?i)\bthis\s+month\b|\bis\s+mahine\b`)
	chatLastMonthRe  = regexp.MustCompile(`(?i)\blast\s+month\b|\bpichle\s+mahine\b`)
	chatThisYearRe   = regexp.MustCompile(`(?i)\bthis\s+year\b`)
	chatRecentlyRe   = regexp.MustCompile(`(?i)\b(recently|lately|of\s+late)\b`)
	// any period word: when one is present and nothing above reads it, the span is Unparsed
	chatAnyPeriodRe = regexp.MustCompile(`(?i)\b\d+\s*(h|hrs?|hours?|days?|weeks?|months?|years?|mins?|minutes?|ghante|din)\b|\b(month|year|tonight|night|morning|afternoon|evening|since|between|ago|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|june|july|august|september|october|november|december|yesterday|tomorrow|kal|aaj|raat|subah|shaam|ghante|hafte|mahine|fortnight|week|today)\b|\b20\d\d-\d\d`)
)

func chatNumOf(s string) int {
	s = strings.ToLower(strings.TrimSpace(s))
	if n, err := strconv.Atoi(s); err == nil {
		return n
	}
	if strings.HasPrefix(s, "couple") {
		return 2
	}
	return chatNumWords[s]
}

// chatUnitDur: the length of one unit ("ghante" = hours, "din" = days, "hafte" = weeks, "mahine" = 30 days).
func chatUnitDur(u string) time.Duration {
	u = strings.ToLower(u)
	switch {
	case u == "m" || strings.HasPrefix(u, "min"):
		return time.Minute
	case u == "h" || strings.HasPrefix(u, "hour") || strings.HasPrefix(u, "hr") || strings.HasPrefix(u, "ghant"):
		return time.Hour
	case strings.HasPrefix(u, "day") || strings.HasPrefix(u, "din"):
		return 24 * time.Hour
	case strings.HasPrefix(u, "week") || strings.HasPrefix(u, "wk") || strings.HasPrefix(u, "haft"):
		return 7 * 24 * time.Hour
	case strings.HasPrefix(u, "month") || strings.HasPrefix(u, "mahin"):
		return 30 * 24 * time.Hour
	case u == "fortnight":
		return 14 * 24 * time.Hour
	case u == "year":
		return 365 * 24 * time.Hour
	}
	return 0
}

func chatDurWords(n int, d time.Duration) string {
	switch {
	case d == time.Minute:
		return plural(n, "minute", "minutes")
	case d == time.Hour:
		return plural(n, "hour", "hours")
	case d == 24*time.Hour:
		return plural(n, "day", "days")
	case d == 7*24*time.Hour:
		return plural(n, "week", "weeks")
	case d == 30*24*time.Hour:
		return plural(n, "month (30 days)", "months (30 days each)")
	}
	return fmt.Sprint(time.Duration(n) * d)
}

// chatClock: hour and minute of a clock time ("8 am", "17:30", "10 baje"); hint: "am", "pm" or "" (from words like
// raat / shaam around it). ok false = not a time.
func chatClock(h, m, ampm, hint string) (int, int, bool) {
	hh, err := strconv.Atoi(h)
	if err != nil || hh > 23 {
		return 0, 0, false
	}
	mm := 0
	if m != "" {
		mm, _ = strconv.Atoi(m)
		if mm > 59 {
			return 0, 0, false
		}
	}
	ampm = strings.ToLower(strings.ReplaceAll(ampm, ".", ""))
	if ampm == "" || ampm == "baje" || strings.HasPrefix(ampm, "o") || ampm == "hrs" {
		if ampm == "" && m == "" && hint == "" {
			return 0, 0, false // a bare number is not a clock time
		}
		ampm = hint
	}
	switch ampm {
	case "pm":
		if hh < 12 {
			hh += 12
		}
	case "am":
		if hh == 12 {
			hh = 0
		}
	}
	return hh, mm, true
}

// chatAmPmHint: am/pm from day-part words (raat 10 baje = 22:00, subah 8 = 08:00).
func chatAmPmHint(q string) string {
	switch {
	case regexp.MustCompile(`(?i)\b(raat|night|shaam|sham|evening|dopahar|afternoon)\b`).MatchString(q):
		return "pm"
	case regexp.MustCompile(`(?i)\b(subah|morning)\b`).MatchString(q):
		return "am"
	}
	return ""
}

func chatDay(t time.Time) time.Time {
	t = t.In(IST)
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, IST)
}

// chatLastWeekday: the most recent day with that weekday (today counts).
func chatLastWeekday(now time.Time, wd time.Weekday) time.Time {
	d := chatDay(now)
	for d.Weekday() != wd {
		d = d.AddDate(0, 0, -1)
	}
	return d
}

// chatSpanOf reads the period a question names, relative to the device time now.
func chatSpanOf(q string, now time.Time) chatSpan {
	now = now.In(IST)
	today := chatDay(now)
	mk := func(a, b time.Time, words string) chatSpan {
		if b.After(now.Add(time.Minute)) && now.After(a) {
			b = now.Add(time.Minute)
		}
		return chatSpan{From: a, To: b, Words: words, now: now}
	}
	hint := chatAmPmHint(q)
	// a base day named next to a clock time
	baseDay := today
	if chatYestRe.MatchString(q) && !chatSpanFutureRe.MatchString(q) {
		baseDay = today.AddDate(0, 0, -1)
	}
	if chatDayBeforeRe.MatchString(q) {
		baseDay = today.AddDate(0, 0, -2)
	}
	dayWords := func(d time.Time) string {
		switch {
		case d.Equal(today):
			return "today"
		case d.Equal(today.AddDate(0, 0, -1)):
			return "yesterday"
		}
		return "on " + d.Format("Mon 2 Jan")
	}
	if chatSpanFutureRe.MatchString(q) && !chatSinceRe.MatchString(q) {
		return chatSpan{Future: true, Words: "in the future"}
	}
	// between 5 pm and 9 pm [yesterday]
	if m := chatBetweenRe.FindStringSubmatch(q); m != nil {
		h2, m2, ok2 := chatClock(m[4], m[5], m[6], hint)
		amp := m[3]
		if amp == "" {
			amp = m[6] // "between 5 and 9 pm": the second half's am/pm
		}
		h1, m1, ok1 := chatClock(m[1], m[2], amp, hint)
		if ok1 && ok2 {
			a := baseDay.Add(time.Duration(h1)*time.Hour + time.Duration(m1)*time.Minute)
			b := baseDay.Add(time.Duration(h2)*time.Hour + time.Duration(m2)*time.Minute)
			if !b.After(a) {
				b = b.AddDate(0, 0, 1)
			}
			if a.After(now) && baseDay.Equal(today) {
				a, b = a.AddDate(0, 0, -1), b.AddDate(0, 0, -1) // later than now today: the last such window
			}
			return mk(a, b, fmt.Sprintf("between %s and %s %s", a.Format("15:04"), b.Format("15:04"), dayWords(chatDay(a))))
		}
	}
	// since Monday 8 am / since yesterday / since 6 pm
	if m := chatSinceRe.FindStringSubmatch(q); m != nil {
		w := strings.ToLower(m[1])
		var d time.Time
		h, mi, hasClock := 0, 0, false
		if m[2] != "" {
			h, mi, hasClock = chatClock(m[2], m[3], m[4], hint)
		}
		switch {
		case chatWeekdays[w] != 0 || w == "sunday" || w == "sun" || w == "ravivar":
			d = chatLastWeekday(now, chatWeekdays[w])
			if d.Equal(today) && strings.Contains(strings.ToLower(m[0]), "last") {
				d = d.AddDate(0, 0, -7)
			}
		case w == "yesterday" || w == "kal":
			d = today.AddDate(0, 0, -1)
		case w == "today" || w == "midnight":
			d = today
		case strings.Contains(w, "morning"):
			d, h, mi, hasClock = today, 6, 0, true
		case w == "noon":
			d, h, mi, hasClock = today, 12, 0, true
		default:
			// "since 6 pm": the clock is the first group
			mm := regexp.MustCompile(`(?i)^` + chatClockRe + `$`).FindStringSubmatch(strings.TrimSpace(m[1]))
			if mm != nil {
				if hh, mmi, ok := chatClock(mm[1], mm[2], mm[3], hint); ok {
					d, h, mi, hasClock = today, hh, mmi, true
					if d.Add(time.Duration(hh)*time.Hour + time.Duration(mmi)*time.Minute).After(now) {
						d = today.AddDate(0, 0, -1)
					}
				}
			}
		}
		if !d.IsZero() {
			a := d
			if hasClock {
				a = d.Add(time.Duration(h)*time.Hour + time.Duration(mi)*time.Minute)
			}
			words := "since " + a.Format("Mon 2 Jan")
			if hasClock {
				words = "since " + a.Format("Mon 2 Jan 15:04")
			}
			return mk(a, now.Add(time.Minute), words)
		}
	}
	// N hours ago / 3 weeks ago: that hour / day / week
	if m := chatSpanAgoRe.FindStringSubmatch(q); m != nil {
		n, u := chatNumOf(m[1]), chatUnitDur(m[2])
		if n > 0 && u > 0 {
			at := now.Add(-time.Duration(n) * u)
			switch {
			case u >= 7*24*time.Hour:
				a := chatDay(at)
				return mk(a, a.AddDate(0, 0, 7), fmt.Sprintf("in the week starting %s (%s ago)", a.Format("Mon 2 Jan"), chatDurWords(n, u)))
			case u == 24*time.Hour:
				a := chatDay(at)
				return mk(a, a.AddDate(0, 0, 1), dayWords(a)+fmt.Sprintf(" (%s ago)", chatDurWords(n, u)))
			default:
				return mk(at.Add(-30*time.Minute), at.Add(30*time.Minute), fmt.Sprintf("around %s (%s ago)", at.Format("15:04"), chatDurWords(n, u)))
			}
		}
	}
	// last 12 hours / pichle 2 din / 12 ghante mein
	rel := chatSpanRelRe.FindStringSubmatch(q)
	if rel == nil {
		rel = chatSpanRelHiRe.FindStringSubmatch(q)
	}
	if rel != nil {
		n, u := chatNumOf(rel[1]), chatUnitDur(rel[2])
		if n > 0 && u > 0 && time.Duration(n)*u <= 400*24*time.Hour {
			return mk(now.Add(-time.Duration(n)*u), now.Add(time.Minute), "in the last "+chatDurWords(n, u))
		}
	}
	if m := chatSpanRel1Re.FindStringSubmatch(q); m != nil && !chatLastMonthRe.MatchString(q) {
		u := chatUnitDur(m[1])
		if strings.ToLower(m[1]) == "fortnight" {
			u = 14 * 24 * time.Hour
		}
		if u > 0 && !(u == 7*24*time.Hour && chatWeekBeforeRe.MatchString(q)) {
			w := map[time.Duration]string{time.Hour: "in the last hour", 24 * time.Hour: "in the last 24 hours", 7 * 24 * time.Hour: "in the last 7 days",
				14 * 24 * time.Hour: "in the last 14 days", 30 * 24 * time.Hour: "in the last 30 days", 365 * 24 * time.Hour: "in the last 365 days"}[u]
			return mk(now.Add(-u), now.Add(time.Minute), w)
		}
	}
	if chatSpanFortRe.MatchString(q) {
		return mk(now.Add(-14*24*time.Hour), now.Add(time.Minute), "in the last 14 days")
	}
	// overnight / last night / kal raat
	if chatOvernightRe.MatchString(q) && !chatAfterRe.MatchString(q) {
		a := today.AddDate(0, 0, -1).Add(20 * time.Hour)
		b := today.Add(8 * time.Hour)
		if now.Before(today.Add(20*time.Hour)) && now.After(b) {
			return mk(a, b, "overnight")
		}
		if !now.After(b) {
			return mk(a, now.Add(time.Minute), "overnight")
		}
		if regexp.MustCompile(`(?i)\btonight\b|\baaj\s+raat\b`).MatchString(q) {
			return mk(today.Add(20*time.Hour), now.Add(time.Minute), "tonight so far")
		}
		return mk(a, b, "last night") // asked in the evening: the last full night
	}
	// after 10 pm yesterday / kal raat 10 baje ke baad
	if m := chatAfterRe.FindStringSubmatch(q); m != nil {
		g := m[1:4]
		if m[1] == "" {
			g = m[4:7]
		}
		if h, mi, ok := chatClock(g[0], g[1], g[2], hint); ok {
			a := baseDay.Add(time.Duration(h)*time.Hour + time.Duration(mi)*time.Minute)
			if a.After(now) {
				a = a.AddDate(0, 0, -1)
			}
			return mk(a, now.Add(time.Minute), "since "+a.Format("Mon 2 Jan 15:04"))
		}
	}
	// this morning / kal shaam
	if m := chatPartDayRe.FindStringSubmatch(q); m != nil {
		word := strings.ToLower(m[2] + m[4] + m[5])
		day := today
		if strings.HasPrefix(strings.ToLower(m[1]), "yesterday") || strings.ToLower(m[1]) == "kal" {
			day = today.AddDate(0, 0, -1)
		}
		parts := map[string][2]int{"morning": {6, 12}, "subah": {6, 12}, "afternoon": {12, 17}, "dopahar": {12, 17}, "evening": {17, 21},
			"shaam": {17, 21}, "sham": {17, 21}, "night": {21, 30}, "raat": {21, 30}}
		if p, ok := parts[word]; ok {
			a, b := day.Add(time.Duration(p[0])*time.Hour), day.Add(time.Duration(p[1])*time.Hour)
			if a.After(now) {
				a, b = a.AddDate(0, 0, -1), b.AddDate(0, 0, -1)
			}
			en := map[string]string{"subah": "morning", "dopahar": "afternoon", "shaam": "evening", "sham": "evening", "raat": "night"}[word]
			if en == "" {
				en = word
			}
			return mk(a, b, fmt.Sprintf("%s %s (%s-%s)", map[bool]string{true: "this", false: "yesterday"}[chatDay(a).Equal(today)], en,
				a.Format("15:04"), b.Add(-time.Minute).Add(time.Minute).Format("15:04")))
		}
	}
	// date ranges: between 20 Oct and 25 Oct / from 20 to 25 Oct
	if m := chatDateRangeRe.FindStringSubmatch(q); m != nil {
		d1, ok1 := chatDateOf(m[1], now)
		d2, ok2 := chatDateOf(m[2], now)
		if !ok1 && ok2 { // "20 to 25 Oct": the month of the second date
			if n, err := strconv.Atoi(strings.TrimSpace(m[1])); err == nil && n >= 1 && n <= 31 {
				d1, ok1 = time.Date(d2.Year(), d2.Month(), n, 0, 0, 0, 0, IST), true
			}
		}
		if ok1 && ok2 && !d2.Before(d1) {
			return mk(d1, d2.AddDate(0, 0, 1), fmt.Sprintf("from %s to %s", d1.Format("Mon 2 Jan"), d2.Format("Mon 2 Jan")))
		}
	}
	// dates: 22 Oct, Oct 22, 2026-10-22, 22/10
	if d, ok := chatDateOf(q, now); ok {
		return mk(d, d.AddDate(0, 0, 1), "on "+d.Format("Mon 2 Jan"))
	}
	if chatDayBeforeRe.MatchString(q) {
		a := today.AddDate(0, 0, -2)
		return mk(a, a.AddDate(0, 0, 1), "on "+a.Format("Mon 2 Jan"))
	}
	// weeks and months
	if chatWeekBeforeRe.MatchString(q) && !chatLastWeekRe.MatchString(q) && !chatThisWeekRe.MatchString(q) {
		return mk(now.Add(-14*24*time.Hour), now.Add(-7*24*time.Hour), "in the 7 days before the last 7")
	}
	if chatThisWeekRe.MatchString(q) {
		wd := (int(today.Weekday()) + 6) % 7
		a := today.AddDate(0, 0, -wd)
		return mk(a, now.Add(time.Minute), "this week (since Monday)")
	}
	if chatLastWeekRe.MatchString(q) {
		return mk(now.Add(-7*24*time.Hour), now.Add(time.Minute), "in the last 7 days")
	}
	if chatThisMonthRe.MatchString(q) {
		return mk(time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, IST), now.Add(time.Minute), "this month")
	}
	if chatLastMonthRe.MatchString(q) {
		first := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, IST)
		return mk(first.AddDate(0, -1, 0), first, "last month")
	}
	if chatThisYearRe.MatchString(q) {
		return mk(time.Date(now.Year(), 1, 1, 0, 0, 0, 0, IST), now.Add(time.Minute), "this year")
	}
	// on Sunday / last Sunday
	if m := chatOnWdRe.FindStringSubmatch(q); m != nil {
		if wd, ok := chatWeekdays[strings.ToLower(m[1])]; ok {
			d := chatLastWeekday(now, wd)
			if strings.HasPrefix(strings.ToLower(strings.TrimSpace(m[0])), "last") && d.Equal(today) {
				d = d.AddDate(0, 0, -7)
			}
			return mk(d, d.AddDate(0, 0, 1), dayWords(d))
		}
	}
	// a clock time alone: before 9 am (today)
	if m := chatBeforeRe.FindStringSubmatch(q); m != nil {
		g := m[1:4]
		if m[1] == "" {
			g = m[4:7]
		}
		if h, mi, ok := chatClock(g[0], g[1], g[2], hint); ok {
			b := baseDay.Add(time.Duration(h)*time.Hour + time.Duration(mi)*time.Minute)
			return mk(baseDay, b, fmt.Sprintf("%s before %s", dayWords(baseDay), b.Format("15:04")))
		}
	}
	if chatTodayRe.MatchString(q) {
		return mk(today, now.Add(time.Minute), "today")
	}
	if chatYestRe.MatchString(q) {
		a := today.AddDate(0, 0, -1)
		return mk(a, today, "yesterday")
	}
	if chatRecentlyRe.MatchString(q) {
		return mk(now.Add(-24*time.Hour), now.Add(time.Minute), "in the last 24 hours")
	}
	if m := chatAnyPeriodRe.FindString(q); m != "" {
		return chatSpan{Unparsed: m}
	}
	return chatSpan{}
}

// chatDateOf: a calendar date named in q (the most recent one not after now).
func chatDateOf(q string, now time.Time) (time.Time, bool) {
	var day int
	var mon time.Month
	year := now.Year()
	switch {
	case chatDateRe3.MatchString(q):
		m := chatDateRe3.FindStringSubmatch(q)
		y, _ := strconv.Atoi(m[1])
		mo, _ := strconv.Atoi(m[2])
		d, _ := strconv.Atoi(m[3])
		return time.Date(y, time.Month(mo), d, 0, 0, 0, 0, IST), mo >= 1 && mo <= 12 && d >= 1 && d <= 31
	case chatDateRe1.MatchString(q):
		m := chatDateRe1.FindStringSubmatch(q)
		day, _ = strconv.Atoi(m[1])
		mon = chatMonths[strings.ToLower(m[2])]
		if mon == 0 {
			mon = chatMonths[strings.ToLower(m[2][:3])]
		}
	case chatDateRe2.MatchString(q):
		m := chatDateRe2.FindStringSubmatch(q)
		day, _ = strconv.Atoi(m[2])
		mon = chatMonths[strings.ToLower(m[1])]
		if mon == 0 {
			mon = chatMonths[strings.ToLower(m[1][:3])]
		}
	case chatDateRe4.MatchString(q):
		m := chatDateRe4.FindStringSubmatch(q)
		day, _ = strconv.Atoi(m[1])
		mo, _ := strconv.Atoi(m[2])
		mon = time.Month(mo)
	default:
		return time.Time{}, false
	}
	if day < 1 || day > 31 || mon < 1 || mon > 12 {
		return time.Time{}, false
	}
	d := time.Date(year, mon, day, 0, 0, 0, 0, IST)
	if d.After(now.AddDate(0, 0, 60)) { // the device's sensor clock replays days, so a date a little ahead stays this year
		d = d.AddDate(-1, 0, 0)
	}
	return d, true
}

// chatPresetSpan: a tool time preset the model wrote that span() does not list ("last_14d", "last_12h", "last_90m",
// "last_2w"): the same relative window. ok false = not of that form.
var chatPresetNRe = regexp.MustCompile(`^(?:last|past)_(\d{1,4})\s*(m|min|mins|minutes|h|hr|hrs|hours|d|days|w|wk|weeks)$`)

func chatPresetSpan(p string, now time.Time) (time.Time, time.Time, bool) {
	m := chatPresetNRe.FindStringSubmatch(strings.ToLower(strings.TrimSpace(p)))
	if m == nil {
		return now, now, false
	}
	n, _ := strconv.Atoi(m[1])
	u := map[byte]time.Duration{'m': time.Minute, 'h': time.Hour, 'd': 24 * time.Hour, 'w': 7 * 24 * time.Hour}[m[2][0]]
	if n <= 0 || time.Duration(n)*u > 400*24*time.Hour {
		return now, now, false
	}
	return now.Add(-time.Duration(n) * u), now, true
}
