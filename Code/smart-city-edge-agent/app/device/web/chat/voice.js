/* Push-to-talk voice for the chat. Records in the browser, converts to 16 kHz mono WAV, the board transcribes it
   (whisper.cpp, CPU), the text is shown for 1 s, then sent as a normal question. Answers to SPOKEN questions are read
   aloud with the system text-to-speech (speechSynthesis, on-device). Typed questions are never read aloud. */
(function () {
  const $ = (s) => document.querySelector(s);
  const mic = $('#mic'), stopBtn = $('#speakstop'), q = $('#q'), sendBtn = $('#send');
  if (!mic || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { if (mic) mic.hidden = true; return; }
  const note = $('#voicenote');
  let rec = null, stream = null, chunks = [], ctx = null, proc = null, src = null, busy = false, tmo = null;
  const say = (t) => { if (note) { note.textContent = t; note.hidden = !t; } };

  function toWav(buf16) { // Float32 mono 16 kHz -> 16-bit WAV
    const n = buf16.length, b = new ArrayBuffer(44 + n * 2), v = new DataView(b);
    const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    w(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); w(8, 'WAVE'); w(12, 'fmt '); v.setUint32(16, 16, true);
    v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 16000, true); v.setUint32(28, 32000, true);
    v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, 'data'); v.setUint32(40, n * 2, true);
    for (let i = 0; i < n; i++) { const s = Math.max(-1, Math.min(1, buf16[i])); v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true); }
    return b;
  }
  function resample(f32, rate) { // linear, box-averaged when downsampling
    if (rate === 16000) return f32;
    const ratio = rate / 16000, n = Math.floor(f32.length / ratio), o = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const a = Math.floor(i * ratio), e = Math.min(f32.length, Math.floor((i + 1) * ratio));
      let s = 0; for (let j = a; j < e; j++) s += f32[j]; o[i] = s / Math.max(1, e - a);
    }
    return o;
  }

  async function start() {
    if (busy || (window.S && window.S.busy)) return;
    stopSpeaking();
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } }); }
    catch (e) { say('Microphone blocked. Allow it for this app in Android settings.'); return; }
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    src = ctx.createMediaStreamSource(stream);
    proc = ctx.createScriptProcessor(4096, 1, 1); chunks = [];
    // 2026-11-20: voice activity detection - stop by itself after 2 s of quiet once speech was heard;
    // stop with a hint if nothing above the noise floor arrives in 8 s (silent / blocked microphone)
    const blk = 4096 / ctx.sampleRate; let heard = false, quiet = 0, t = 0, peak = 0, floor = 0.004;
    proc.onaudioprocess = (ev) => {
      const d = ev.inputBuffer.getChannelData(0); chunks.push(new Float32Array(d));
      let e = 0; for (let i = 0; i < d.length; i++) e += d[i] * d[i]; const rms = Math.sqrt(e / d.length);
      peak = Math.max(peak, rms); t += blk;
      if (t < 0.5) floor = Math.max(floor, rms * 1.5); // first half second sets the room noise level
      const on = rms > Math.max(0.01, floor * 2.5);
      if (on) { heard = true; quiet = 0; } else if (heard) quiet += blk;
      mic.style.setProperty('--lvl', Math.min(1, rms * 12).toFixed(2));
      say(heard ? 'Listening… (stops after 2 s of quiet)' + ' ' + '|'.repeat(Math.min(12, Math.round(rms * 120))) : 'Listening… speak now');
      if (heard && quiet >= 2) stop();
      else if (!heard && t >= 8) { stop(peak < 0.0005 ? 'silent' : 'none'); }
    };
    src.connect(proc); proc.connect(ctx.destination);
    rec = true; mic.classList.add('rec'); mic.setAttribute('aria-pressed', 'true'); say('Listening… speak now');
    tmo = setTimeout(stop, 28000); // the board accepts about 30 s
  }
  async function stop(why) {
    if (!rec) return; rec = false; clearTimeout(tmo);
    mic.classList.remove('rec'); mic.setAttribute('aria-pressed', 'false');
    const rate = ctx.sampleRate;
    try { proc.disconnect(); src.disconnect(); stream.getTracks().forEach((t) => t.stop()); ctx.close(); } catch { /* ignore */ }
    let len = 0; chunks.forEach((c) => { len += c.length; });
    const all = new Float32Array(len); let o = 0; chunks.forEach((c) => { all.set(c, o); o += c.length; }); chunks = [];
    if (why === 'silent') { say('The microphone gives only silence. Check that the board mic is not covered or muted, and that the app may use it.'); return; }
    if (why === 'none') { say('I did not hear any speech. Tap the mic and speak a little louder or closer.'); return; }
    if (len < rate * 0.4) { say('Too short. Tap the mic and speak.'); return; }
    busy = true; mic.disabled = true; say('Transcribing…');
    try {
      const r = await fetch('/api/chat/voice', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: toWav(resample(all, rate)) });
      if (!r.ok) throw new Error((await r.text()).trim() || 'voice not available');
      const text = ((await r.json()).text || '').trim();
      if (!text) { say('Heard nothing. Try again, a little closer.'); return; }
      q.value = text; q.dispatchEvent(new Event('input')); say('Heard: "' + text.slice(0, 80) + '"');
      setTimeout(() => { say(''); window.SPOKEN = true; if (window.ask) window.ask(q.value); }, 1000);
    } catch (e) { say(String(e.message || e).slice(0, 90)); }
    finally { busy = false; mic.disabled = false; }
  }
  mic.addEventListener('click', () => { rec ? stop() : start(); }); // tap again still stops at once

  /* read-aloud of the answer to a spoken question */
  function pickVoice() {
    const vs = speechSynthesis.getVoices();
    return vs.find((v) => /en[-_]IN/i.test(v.lang)) || vs.find((v) => /^en/i.test(v.lang)) || null;
  }
  function stopSpeaking() { try { speechSynthesis.cancel(); } catch { /* none */ } if (stopBtn) stopBtn.hidden = true; }
  window.speakAnswer = function (text) {
    if (!('speechSynthesis' in window) || !text) return;
    const clean = text.replace(/[*_`#>]+/g, ' ').replace(/\s+/g, ' ').trim();
    stopSpeaking();
    const u = new SpeechSynthesisUtterance(clean), v = pickVoice();
    if (v) { u.voice = v; u.lang = v.lang; } else u.lang = 'en-IN';
    u.onend = u.onerror = () => { if (stopBtn) stopBtn.hidden = true; };
    if (stopBtn) stopBtn.hidden = false;
    speechSynthesis.speak(u);
  };
  if (stopBtn) stopBtn.addEventListener('click', stopSpeaking);
  addEventListener('pagehide', stopSpeaking);
})();
