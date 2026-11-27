# Questions for the owner (hands-on sweep, night of 2026-11-26/27)

Decisions I did not take alone. Everything else from the sweep was fixed and deployed (see
`proofs/2026-11-27_sweep/SWEEP.md`). Each item says what I did meanwhile.

1. **Batch split of unrelated events (deployed, can be switched off).** The batch gate used to put every abnormal
   sensor on campus into ONE incident (water pH at the KH tank + an AC failure on KH level 03; outdoor PM10 + the
   SB00 feeder power factor). The reasoner then invented links ("dust ingress ... load ... power factor") or missed a
   sensor. Now sensors that the site tree does not relate (`Relation = campus_no_link`) become separate incidents, and
   only RELATED young sensors hold a batch open. This changes how the paper's "domains >= 2" trigger counts on the
   live board (fewer accidental multi-domain incidents). Keep it? (`htpd_profile batch_split=0` restores the old way.)

2. **Coverage retry (deployed, can be switched off).** When the reasoner's report skipped an alerting sensor, the
   app asked again (~45 s on the board), the retry also missed it, and the good AI report was replaced by the
   template. Now the AI report is kept and one line per missing sensor is added (no second call).
   `coverage_retry=1` restores the retry. OK?

3. **Stale open incidents.** An incident left open longer than 24 h no longer absorbs a NEW episode of its own
   sensor (a new incident and alert open instead). Before, a 6-day-old open pH incident swallowed a new critical
   episode with no alert. Is 24 h right, or do you want auto-close of old open incidents (e.g. after 7 days)?

4. **Old test incidents on the board.** INC-0001/0002/0003/0009/0012 (20-24 Nov) were still open. I restored the
   pre-sweep state after testing, so they are open again. Close them (as "no action needed")?

5. **Board clock.** The board's RTC says 2023-09-22; the app corrects it with a start offset. The UI now uses the
   backend's corrected time, but a real fix is NTP or `POST /api/prod/time` at boot. Should the launcher set it?

6. **Model wording errors (training data, not code).** Seen live: "AC running ... stop the AC" while AC units = 0;
   "ventilate" for an OUTDOOR PM event (should be: close windows, cut fresh-air intake); calm wind (3 -> 0.6 m/s)
   called "steady". Add these to the next reasoner top-up set?

7. **Chat about incidents is weak** ("is the pH a sensor fault or real?" answered with the current value only;
   "has this happened before on this sensor?" picked the wrong sensor). I fixed the time-window bug that hid the
   newest incident from "latest critical" / "waiting for a decision". The rest needs router/training work: priority?

8. **Fog / MQTT / campus relays are down on the board** (outbox 17 MB, ~750 failed uploads). Expected while the
   board is off campus? The logs are now rate-limited (one line per 10 min).

9. **Room-temperature context now includes the AC on/off state** (`orchestrator.go`: `air_quality/temp` also attaches
   `hvac/ac_units_on`). In run 2 the reasoner called a real AC-failure heat-up a "sensor jump" partly because the AC
   state was not in the prompt. This adds one context sensor to such prompts (a small shift from the training
   prompts). Keep it?

10. **Reasoner misjudgement seen in run 2 (training data).** INC-0017: room temp +2 C per 5 min with the AC room sensor
    rising too (both in the prompt) -> "sensor jump, not real heat". Run 1 judged the same scenario correctly. Add
    "corroborated rise = real event" pairs to the next top-up?

11. **Remaining chat gaps (router work).** "What should maintenance check first for the KH level 3 issue?" answered
    with the KH level 98 pH incident (place not used to pick the incident); "Has this happened before on this
    sensor?" repeats the current incident instead of the sensor's history; "most urgent" picks a 6-day-old critical
    over today's. Note: my first chat test reported broken follow-ups ("why did you say that?") - that was my test
    script (it did not reuse the chat id); with the real session the follow-ups work.

12. **Flatline (stuck sensor) needs 16 identical readings = 80 min** before it is a sensor fault (`features.go`).
    A stuck feed is invisible for 80 min. Shorten for sensors that never repeat exactly (TDS, CO2)?
