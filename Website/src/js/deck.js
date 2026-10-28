// Deck viewer: .pdf (pdf.js, exact) and .pptx (pptx-preview, best effort).
// The file stays in this tab's memory: never uploaded, never stored, forgotten on reload or lock.
import { h } from './ui.js';

const VENDOR = new URL('../vendor/', import.meta.url);
let state = null; // {kind, name, count, index, pdf?, slides?(Element[]), aspect, thumbsOpen}

export function hasDeck() { return !!state; }
export function forget() {
  if (state && state.pdf) { try { state.pdf.destroy(); } catch { /* ignore */ } }
  if (state && state.previewer) { try { state.previewer.destroy(); } catch { /* ignore */ } }
  if (state && state.offscreen) state.offscreen.remove();
  state = null;
}

// ---------------------------------------------------------------- loaders
let pdfjsP = null;
function pdfjs() {
  if (!pdfjsP) {
    pdfjsP = import(new URL('pdfjs/pdf.min.js', VENDOR).href).then((m) => {
      m.GlobalWorkerOptions.workerSrc = new URL('pdfjs/pdf.worker.min.js', VENDOR).href;
      return m;
    });
  }
  return pdfjsP;
}
let pptxP = null;
function pptxLib() {
  if (window.pptxPreview) return Promise.resolve(window.pptxPreview);
  if (!pptxP) {
    pptxP = new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = new URL('pptx-preview/pptx-preview.umd.js', VENDOR).href;
      s.onload = () => resolve(window.pptxPreview);
      s.onerror = () => reject(new Error('PowerPoint renderer failed to load'));
      document.head.append(s);
    });
  }
  return pptxP;
}

async function loadFile(file) {
  const name = file.name || 'deck';
  const ext = name.toLowerCase().split('.').pop();
  const buf = await file.arrayBuffer();
  forget();
  if (ext === 'pdf' || file.type === 'application/pdf') {
    const lib = await pdfjs();
    const pdf = await lib.getDocument({
      data: new Uint8Array(buf), isEvalSupported: false, disableAutoFetch: true,
      cMapUrl: new URL('pdfjs/cmaps/', VENDOR).href, cMapPacked: true,
      standardFontDataUrl: new URL('pdfjs/standard_fonts/', VENDOR).href,
    }).promise;
    const p1 = await pdf.getPage(1);
    const vp = p1.getViewport({ scale: 1 });
    state = { kind: 'pdf', name, pdf, count: pdf.numPages, index: 0, aspect: vp.width / vp.height, cache: new Map() };
  } else if (ext === 'pptx') {
    const lib = await pptxLib();
    const off = h('div.pptx-offscreen', { 'aria-hidden': 'true' });
    document.body.append(off);
    const previewer = lib.init(off, { width: 960, height: 540, mode: 'list' });
    await previewer.preview(buf);
    const slides = [...off.querySelectorAll('.pptx-preview-slide-wrapper')];
    if (!slides.length) { off.remove(); throw new Error('no slides found in this .pptx'); }
    const sh = parseFloat(slides[0].style.height) || slides[0].offsetHeight || 540;
    slides.forEach((s) => { s.style.margin = '0'; s.remove(); });
    state = { kind: 'pptx', name, slides, count: slides.length, index: 0, aspect: 960 / sh, previewer, offscreen: off };
  } else {
    throw new Error('Use a .pdf or .pptx file.');
  }
  state.thumbsOpen = false;
}

// ---------------------------------------------------------------- rendering
async function pdfCanvas(i, cssW, cssH) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2.5);
  const key = `${i}:${Math.round(cssW)}x${Math.round(cssH)}:${dpr}`;
  if (state.cache.has(key)) return state.cache.get(key);
  const page = await state.pdf.getPage(i + 1);
  const vp1 = page.getViewport({ scale: 1 });
  const scale = Math.min(cssW / vp1.width, cssH / vp1.height);
  const vp = page.getViewport({ scale: scale * dpr });
  const c = document.createElement('canvas');
  c.width = Math.floor(vp.width); c.height = Math.floor(vp.height);
  c.style.width = Math.floor(vp.width / dpr) + 'px'; c.style.height = Math.floor(vp.height / dpr) + 'px';
  await page.render({ canvasContext: c.getContext('2d', { alpha: false }), viewport: vp }).promise;
  if (state.cache.size > 24) state.cache.delete(state.cache.keys().next().value);
  state.cache.set(key, c);
  return c;
}

function pptxNode(i, cssW, cssH, clone) {
  const src = state.slides[i];
  const sw = 960, sh = 960 / state.aspect;
  const scale = Math.min(cssW / sw, cssH / sh);
  const host = h('div.pptx-slide-host', { style: `width:${Math.floor(sw * scale)}px;height:${Math.floor(sh * scale)}px` });
  const inner = h('div.pptx-slide-inner', { style: `transform:scale(${scale});width:${sw}px;height:${sh}px` });
  inner.append(clone ? src.cloneNode(true) : src);
  host.append(inner);
  return host;
}

// ---------------------------------------------------------------- view
/**
 * Mount the deck area into `el`. Shows the drop zone, or the viewer when a deck is in memory.
 * opts.onChange(hasDeck) lets the page hide its intro once a deck is loaded.
 * Returns a cleanup function.
 */
export function mount(el, opts = {}) {
  let disposers = [];
  const cleanup = () => { disposers.forEach((f) => f()); disposers = []; };
  const render = () => {
    cleanup();
    el.replaceChildren(state ? viewer() : dropZone());
    if (opts.onChange) opts.onChange(!!state);
  };

  function dropZone() {
    const input = h('input', { type: 'file', accept: '.pdf,.pptx,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation', class: 'sr-only', id: 'deck-file', tabindex: '-1' });
    const msg = h('p.drop__msg', { 'aria-live': 'polite' });
    const zone = h('div.drop', null,
      h('p.drop__title', { text: 'Drop the deck here' }),
      h('p.muted', { text: 'PDF looks exactly like your deck. PowerPoint (.pptx) is best effort.' }),
      h('div.drop__actions', null, h('button.btn.btn--solid', { type: 'button', onclick: () => input.click() }, 'Choose file')),
      h('p.label', { text: 'Stays in this tab · never uploaded · gone on reload' }),
      msg, input);
    const take = async (file) => {
      if (!file) return;
      msg.classList.remove('is-error');
      msg.textContent = 'Opening ' + file.name + '…';
      try { await loadFile(file); render(); }
      catch (err) { console.error('[deck]', err); msg.classList.add('is-error'); msg.textContent = 'Could not open this file: ' + err.message; }
    };
    input.addEventListener('change', () => take(input.files[0]));
    const over = (e) => { e.preventDefault(); zone.classList.add('is-over'); };
    const leave = () => zone.classList.remove('is-over');
    zone.addEventListener('dragover', over);
    zone.addEventListener('dragenter', over);
    zone.addEventListener('dragleave', leave);
    zone.addEventListener('drop', (e) => { e.preventDefault(); leave(); take(e.dataTransfer.files[0]); });
    // dropping anywhere on the page also works
    const winDrop = (e) => { if (e.dataTransfer && e.dataTransfer.files.length) { e.preventDefault(); take(e.dataTransfer.files[0]); } };
    const winOver = (e) => { if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) e.preventDefault(); };
    window.addEventListener('drop', winDrop); window.addEventListener('dragover', winOver);
    disposers.push(() => { window.removeEventListener('drop', winDrop); window.removeEventListener('dragover', winOver); });
    return zone;
  }

  function viewer() {
    const stage = h('div.show__stage', { 'aria-live': 'polite' });
    const counter = h('div.show__counter');
    const thumbs = h('div.thumbs', { hidden: !state.thumbsOpen, role: 'tablist', 'aria-label': 'Slides' });
    const prevB = h('button.show__nav.show__nav--prev', { type: 'button', 'aria-label': 'Previous slide' }, '‹');
    const nextB = h('button.show__nav.show__nav--next', { type: 'button', 'aria-label': 'Next slide' }, '›');
    const show = h('div.show', { tabindex: '0', 'aria-roledescription': 'slideshow', 'aria-label': state.name }, stage, prevB, nextB, counter, thumbs);
    const fullB = h('button.btn.btn--solid', { type: 'button' }, 'Present');
    const thumbsB = h('button.btn', { type: 'button', 'aria-pressed': String(state.thumbsOpen) }, 'Slides');
    const closeB = h('button.btn', { type: 'button' }, 'Close deck');
    const bar = h('div.deckbar', null, h('span.deckbar__name', { text: `${state.name} · ${state.count} slides` }), h('div.deckbar__actions', null, thumbsB, fullB, closeB));
    const wrap = h('div', null, bar, show, h('p.label', { style: 'margin-top:10px', text: '← → space · click · swipe · F full screen · Esc exit · T slides' }));

    let drawToken = 0;
    const draw = async () => {
      const tok = ++drawToken;
      const i = state.index;
      counter.textContent = `${i + 1} / ${state.count}`;
      const w = stage.clientWidth || 960, hh = stage.clientHeight || 540;
      let node;
      if (state.kind === 'pdf') node = await pdfCanvas(i, w, hh);
      else node = pptxNode(i, w, hh, false);
      if (tok !== drawToken) return;
      stage.replaceChildren(node);
      node.setAttribute('aria-label', `Slide ${i + 1} of ${state.count}`);
      thumbs.querySelectorAll('button').forEach((b, k) => b.setAttribute('aria-current', String(k === i)));
      const cur = thumbs.children[i]; if (cur && !thumbs.hidden) cur.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      // pre-render the next PDF page
      if (state.kind === 'pdf' && i + 1 < state.count) pdfCanvas(i + 1, w, hh).catch(() => {});
    };
    const go = (i) => { const n = Math.max(0, Math.min(state.count - 1, i)); if (n !== state.index) { state.index = n; draw(); } };
    const next = () => go(state.index + 1), prev = () => go(state.index - 1);

    const buildThumbs = async () => {
      if (thumbs.childNodes.length) return;
      for (let i = 0; i < state.count; i++) {
        const b = h('button', { type: 'button', role: 'tab', 'aria-label': `Slide ${i + 1}`, onclick: () => go(i) }, h('span', { text: String(i + 1) }));
        thumbs.append(b);
      }
      for (let i = 0; i < state.count; i++) {
        if (!state || thumbs.hidden) break;
        const b = thumbs.children[i];
        const node = state.kind === 'pdf' ? await pdfCanvas(i, 128, 72) : pptxNode(i, 124, 70, true);
        b.prepend(state.kind === 'pdf' ? cloneCanvas(node) : node);
      }
    };
    const toggleThumbs = () => {
      state.thumbsOpen = thumbs.hidden; thumbs.hidden = !thumbs.hidden; thumbsB.setAttribute('aria-pressed', String(!thumbs.hidden));
      if (!thumbs.hidden) buildThumbs();
      requestAnimationFrame(draw);
    };

    const isFull = () => show.classList.contains('is-full');
    const enterFull = async () => {
      show.classList.add('is-full');
      try { if (show.requestFullscreen && !document.fullscreenElement) await show.requestFullscreen(); } catch { /* CSS full-screen fallback stays */ }
      show.focus(); requestAnimationFrame(draw);
    };
    const exitFull = async () => {
      show.classList.remove('is-full');
      try { if (document.fullscreenElement) await document.exitFullscreen(); } catch { /* ignore */ }
      requestAnimationFrame(draw);
    };
    const onFs = () => { if (!document.fullscreenElement && isFull()) { show.classList.remove('is-full'); requestAnimationFrame(draw); } };
    document.addEventListener('fullscreenchange', onFs);

    const onKey = (e) => {
      if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const k = e.key;
      if (k === 'ArrowRight' || k === 'PageDown' || k === ' ' || k === 'Enter' && e.target === show) { e.preventDefault(); next(); }
      else if (k === 'ArrowLeft' || k === 'PageUp' || k === 'Backspace') { e.preventDefault(); prev(); }
      else if (k === 'Home') { e.preventDefault(); go(0); }
      else if (k === 'End') { e.preventDefault(); go(state.count - 1); }
      else if (k === 'f' || k === 'F') { e.preventDefault(); isFull() ? exitFull() : enterFull(); }
      else if (k === 't' || k === 'T') { e.preventDefault(); toggleThumbs(); }
      else if (k === 'Escape' && isFull()) { e.preventDefault(); exitFull(); }
    };
    document.addEventListener('keydown', onKey);

    // click: left third = back, rest = forward.  swipe: horizontal drag > 40 px.
    let sx = null, sy = null, swiped = false;
    stage.addEventListener('pointerdown', (e) => { sx = e.clientX; sy = e.clientY; swiped = false; });
    stage.addEventListener('pointerup', (e) => {
      if (sx == null) return;
      const dx = e.clientX - sx, dy = e.clientY - sy; sx = null;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) { swiped = true; dx < 0 ? next() : prev(); }
    });
    stage.addEventListener('click', (e) => {
      if (swiped) return;
      const r = stage.getBoundingClientRect();
      (e.clientX - r.left < r.width / 3) ? prev() : next();
    });
    prevB.addEventListener('click', (e) => { e.stopPropagation(); prev(); });
    nextB.addEventListener('click', (e) => { e.stopPropagation(); next(); });
    fullB.addEventListener('click', enterFull);
    thumbsB.addEventListener('click', toggleThumbs);
    closeB.addEventListener('click', () => { forget(); render(); });

    let lastW = 0;
    const ro = new ResizeObserver(() => { const w = stage.clientWidth; if (w && Math.abs(w - lastW) > 2) { lastW = w; draw(); } });
    ro.observe(stage);
    if (state.thumbsOpen) buildThumbs();

    disposers.push(() => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('fullscreenchange', onFs);
      ro.disconnect();
      if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
      // give pptx slide nodes back to the state (they may be inside the stage)
    });
    show.style.setProperty('--aspect', String(state.aspect));
    requestAnimationFrame(draw);
    return wrap;
  }

  render();
  return cleanup;
}

function cloneCanvas(c) {
  const n = document.createElement('canvas');
  n.width = c.width; n.height = c.height;
  n.getContext('2d').drawImage(c, 0, 0);
  return n;
}
