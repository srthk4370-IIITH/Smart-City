# Re-run on the fix build (2026-11-28, edge-agent 809a914f, all 121 decisions)

Same feeder5 scenario (H1-H8, 85 min from 04:29:41), state backed up (`handsonfix_state_backup.tgz`) and restored after;
run state kept as `state_handsonfix1128`. Run 1 outputs moved to `run1/`.

## Verification log
- **04:30 voice (#113) FIXED:** owner spoke after the ping; the app transcribed "What is the temperature in KH level 3?"
  and answered for exactly KH level 03 (3 sensors, 0.0 s) (#68 also verified). Screens: ui/fix_mic_a.png, fix_mic_b.png.
- **04:30 UI:** gear icon (#26), opaque bottom nav (#25), "Readings right now" counters (#110) visible.
- **NEW BUG (#100 regression):** "Since you last looked (24 Sep 04:48 IST): 12 new · 6 got worse · 6 resolved". The card
  uses the WebView's raw clock (board RTC, 2023-09-24), not the corrected server clock, so every incident counts as new.
- **04:31-04:59 speak-back:** board has a working Built-In Mic (bottom) + Back Mic (dumpsys audio). No TTS engine was
  installed (owner approved): sherpa-onnx 1.12.22 TTS engine APK with Piper en_US-lessac-medium (79 MB, from
  huggingface csukuangfj/sherpa-onnx-apk, md5 0b706591...), installed, set as default (tts_default_synth). Spoken
  question "Which incidents are open right now?" transcribed + answered, but **no audio**: Android WebView has no
  `speechSynthesis`, so `speakAnswer` silently returned. Fix: Android bridge `window.SCETTS` (system TextToSpeech,
  USAGE_ASSISTANT) in MainActivity + voice.js uses it. APK built; install after the run.
- **#55 FIXED (board):** pH = one incident (INC-0015), no duplicate. **#59 FIXED (board):** SB00 pf has its own
  incident (INC-0017), not merged with KH heat.
- **BUG (accuracy, recurring):** heat INC-0016 (04:55): reasoner on the NPU said "Point sensor reading not credible",
  sensor_fault, root cause "the AC's own sensor reads normal" although the AGREE line was in the prompt and AC room temp
  was 30.8 C and rising. Guard lowered severity to warning but kept the wrong title and story. Fix (code, deploy after
  run): when the verdict itself is sensor_fault on a corroborated rise, title / root cause / explanation are replaced
  ("Real room temperature rise ... most likely the AC units are off"). Test TestCorroboratedRiseStrongVerdictReplaced.
  Recurring same error (run1 2/4, now again on the NPU) -> candidate for the reasoner top-up the owner allowed when
  errors repeat.
- **#37 OK:** timeline now says "the AI agents are reading the sensors now" at the gate, "the reasoner is writing the
  full report" only right before the reasoner call. **#58 OK:** "would not fit ... no re-run, answer kept" (no wasted
  NPU call).
- **Latency FIXED (#77/#78):** pH fast path 04:45:00 -> AI done 04:46:10 (run 1: full reading held 26 min). PF matured
  ~05:00 -> full reading 05:05 (5 min). Heat promoted warning -> critical at 05:10 when it crossed 34 C ("Sensor
  Temperature rose to critical (agent had said sensor fault): agent re-run, report updated"). The 2-reading CO2 spike
  (05:04-05:09) did not hold any batch and got no early look.
- **Chat FIXED on the board:** "Which readings are critical right now?" -> all 5 critical with values (0.01 s);
  "Is anything wrong in KH level 3?" -> exactly KH level 3, 4 abnormal readings; "pH sensor fault or real?" -> "Real.
  ... an agent first read it as a sensor fault; the final report overruled it"; "Why has KH level 3 CO2 not been
  analysed yet?" -> "2 of the 4 abnormal readings ... AI in about 5 min"; early look explained; "between 10 pm and now"
  -> since 22:00; unknown INC id handled; "hi"/"?" -> hello + examples; multi-part -> model (8.3 s).
- **BUG (still):** "Has this happened before on this sensor?" right after the pH question -> answered INC-0018 (dust)
  via the model in 14 s. The history route did not resolve "this sensor" to the pH sensor from the previous turn.
- **minor (invented):** pH root cause says "a second meter agrees"; there is no second pH meter (TDS/flow are context).
- **05:24-05:42 late scenarios:** dust INC-0018 critical (fast path); stopped tank-level feed -> `stale` / `no_data` in
  data health (#105, 3 missed readings); KH03 CO2 at 300 ppm shows `sensor_fault` live. TDS "stuck at 152" could not
  test #80: this feeder adds noise to every value, so the reading was never exactly constant.
- **BUG (accuracy):** INC-0019, an early look on the AC indoor-unit sensor SR-AC-KH03-15 room_temp, had **no context
  sensors at all** and called a real 33.8 C reading a sensor fault. Cause: the context map had no entry for per-unit AC
  sensors (`hvac/room_temp`, `hvac/ac_on`). Fixed: room air sensor, other AC sensor, AC units, outdoor temp, occupancy;
  test TestContextForPerUnitACSensor.
- **BUG (chat, fixed):** "Has this happened before on this sensor?" now uses the incident of the latest answer (an older
  turn about PM sensors used to win); regression test with the board's exact 3-question sequence.

## After the run (09:00-09:35)
- Deployed edge-agent 2ca53710 + APK with: strong corroborated-rise guard, per-unit AC context, chat history follow-up,
  since-card clock fix, watchdog gate-rule text, TTS bridge, TTS package visibility, no-data banner logic.
- **Speak-back (owner request) WORKS:** the board's own mic hears questions; answers are spoken by the offline Piper
  engine. Fixes needed: (1) TTS engine installed (sherpa-onnx Piper lessac, owner OK); (2) WebView has no
  speechSynthesis -> Android bridge `window.SCETTS`; (3) Android 11 package visibility blocked the engine ("AppsFilter
  BLOCKED") -> `<queries>` TTS_SERVICE in the manifest; (4) speaker volume was 9/15 (very low per owner); raised to max
  with the volume keys (`cmd media_session volume --set` silently did nothing). Owner: "Good now".
- **#120 no-data screen:** now a banner over the dashboard when data was ever seen (remembered per device, server time),
  full screen only if never. Found: the engine forgets per-sensor reading times on restart (data health "missing 27"
  until new readings arrive), and the "catching up 0 %" banner flashes during start-up.
- **#10 fog delivery FIXED:** laptop fog server (`edge-agent-host --fog-addr 0.0.0.0:8092`, WSL ~/fogbox) +
  `adb reverse tcp:8092` + matching `fog_token` (generated, `proofs/secrets/fog.env`, gitignored, never printed) in the
  board profile. Result: fog online, **18,528 queued rows sent, outbox 0 bytes**. Note: the fog server and the adb
  reverse live on the laptop; they stop when the laptop session/USB stops (usb_relay.ps1 -Watch keeps the reverse).
- **09:34 final end-to-end voice:** owner asked "Which incidents are open right now?" by voice -> transcribed exactly ->
  answered (restored state: none open, correct) -> spoken by the Piper engine (AudioTrack USAGE_ASSISTANT/SPEECH from
  the sherpa engine 2.5 s after the mic). Full loop works on the board with no laptop and no network.
- **09:36-09:44 speak-back volume:** owner: first full loop "did not hear"; then "starting volume good, then very low".
  Evidence: no ducking, no volume change during playback; the synthesized audio itself is steady (synthesizeToFile,
  RMS 2500-4000 over 17 s); the same text on the MEDIA stream "stayed loud". The QIDK speaker path fades the ASSISTANT
  stream after a few seconds. Fix: spoken answers use USAGE_MEDIA; before speaking the app resets the audio mode to
  normal, clears the call route, takes transient focus and raises the volume to >= 80 %. Verified on the board
  (AudioTrack USAGE_MEDIA/SPEECH).
- **Voice accuracy (real voice, open):** whisper tiny.en with the campus prompt: synthetic WAVs 6/6 correct (run 1
  without prompt: "AC and KH"). Owner's real voice through the board mic: "KH level 3" right once, wrong twice ("and
  pH level 3", "at pH and in 3"). Options: base.en (more accurate, slower), or a router rule for "pH level N" when no pH
  sensor is on level N.
