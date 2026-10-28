// Shell: password gate, pill nav, hash router, encrypted page loader.
import { unlock, lock, hasKey, lockoutRemaining, decryptText, decryptJSON, decryptBytes } from './crypto.js';
import * as charts from './charts.js';
import { createUI, h, PAGES } from './ui.js';
import { createData } from './data.js';
import * as deck from './deck.js';

const ROUTES = ['deck', 'today', 'journey', 'route', 'decisions', 'proofs', 'qa', 'kit', 'rawdata'];
const app = document.getElementById('app');
const gate = document.getElementById('gate');
const nav = document.getElementById('nav');

let manifest = null;
let glossary = {};
let data = null;
let ui = null;
let current = { cleanup: null, token: 0 };

// ---------------------------------------------------------------- gate
function showGate(msg, isError) {
  document.body.classList.add('locked');
  const m = gate.querySelector('.gate__msg');
  m.textContent = msg || '';
  m.classList.toggle('is-error', !!isError);
  const input = gate.querySelector('input');
  input.value = '';
  setTimeout(() => input.focus(), 0);
}

gate.querySelector('form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = gate.querySelector('input');
  const btn = gate.querySelector('button');
  const msg = gate.querySelector('.gate__msg');
  const pw = input.value;
  if (!pw) return;
  const wait = lockoutRemaining();
  if (wait > 0) { msg.textContent = `Too many tries. Wait ${Math.ceil(wait / 1000)} s.`; msg.classList.add('is-error'); return; }
  btn.disabled = true; input.disabled = true;
  msg.classList.remove('is-error'); msg.textContent = 'Checking…';
  try {
    const r = await unlock(pw);
    if (r.ok) {
      msg.textContent = '';
      await enter();
      return;
    }
    msg.classList.add('is-error');
    if (r.reason === 'wrong') {
      const w = lockoutRemaining();
      msg.textContent = w > 0 ? `That password is not right. Try again in ${Math.ceil(w / 1000)} s.` : 'That password is not right.';
    } else if (r.reason === 'wait') msg.textContent = `Too many tries. Wait ${Math.ceil(r.wait / 1000)} s.`;
    else msg.textContent = 'The site files are from a different build. Reload the page.';
  } catch (err) {
    msg.classList.add('is-error');
    msg.textContent = 'Could not check the password (' + err.message + ').';
  } finally {
    btn.disabled = false; input.disabled = false;
    if (document.body.classList.contains('locked')) { input.select(); input.focus(); }
  }
});

document.getElementById('lock').addEventListener('click', () => {
  document.body.classList.add('locked'); // stops the router before the key goes away
  app.replaceChildren();
  lock();
  deck.forget();
  location.hash = '';
  location.reload();
});

// ---------------------------------------------------------------- after unlock
async function enter() {
  try {
    [manifest, glossary] = await Promise.all([
      decryptJSON('pages/_manifest.json'),
      decryptJSON('pages/_glossary.json').catch(() => ({})),
    ]);
  } catch (err) {
    lock();
    showGate('Session expired. Enter the password again.', true);
    return;
  }
  data = createData();
  ui = createUI({ data, glossary });
  window.SITE = { charts, ui, data, deck }; // handy in the console
  document.body.classList.remove('locked');
  route();
}

// ---------------------------------------------------------------- router
function parseHash() {
  const raw = (location.hash || '').replace(/^#\/?/, '');
  const [pathPart, queryPart = ''] = raw.split('?');
  const parts = pathPart.split('/').filter(Boolean).map(decodeURIComponent);
  const page = ROUTES.includes(parts[0]) ? parts[0] : 'deck';
  return { page, params: parts.slice(1), query: Object.fromEntries(new URLSearchParams(queryPart)) };
}

// pages whose evidence was collected on 20 Oct (their datasets predate the reasoner and the final build)
const ASOF = {
  route: 'The step-by-step route below was collected on 20 Oct.',
  decisions: 'These decisions were collected on 20 Oct; later ones (reasoner, B50, split decoding, fast path) are on the Journey page.',
  proofs: 'Datasets here were collected on 20 Oct; later proof folders are named on the Journey page.',
  rawdata: 'The raw-data explorer reflects the data as of 20 Oct.',
  qa: 'Answers marked "updated 29 Oct" were rewritten for the final build; the rest date from 20 Oct.',
};
// pages outside the nav: their title, and which nav item they live under
const EXTRA = { kit: { title: 'Chart kit', parent: null } };
function setNav(page) {
  const navPage = (EXTRA[page] && EXTRA[page].parent) || page;
  nav.querySelectorAll('a.nav__item').forEach((a) => {
    if (a.dataset.page === navPage) a.setAttribute('aria-current', 'page');
    else a.removeAttribute('aria-current');
  });
  const p = PAGES.find((x) => x.id === page) || EXTRA[page];
  document.title = (p ? p.title + ' · ' : '') + 'Edge AI evidence';
}

const MIME = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp', svg: 'image/svg+xml', gif: 'image/gif', json: 'application/json', pdf: 'application/pdf' };
const assetUrls = new Map();
async function asset(path) {
  if (assetUrls.has(path)) return assetUrls.get(path);
  const bytes = await decryptBytes('pages/' + path);
  const url = URL.createObjectURL(new Blob([bytes], { type: MIME[path.split('.').pop().toLowerCase()] || 'application/octet-stream' }));
  assetUrls.set(path, url);
  return url;
}

async function route() {
  if (document.body.classList.contains('locked')) return;
  const { page, params, query } = parseHash();
  const token = ++current.token;
  // tear down the previous page
  if (typeof current.cleanup === 'function') { try { current.cleanup(); } catch (e) { console.error(e); } }
  current.cleanup = null;
  if (ui) ui._hideTip();
  charts.disposeIn(app);
  setNav(page);

  const entry = manifest.pages[page];
  const root = h('div.page', { id: 'page-' + page, 'data-page': page });
  if (!entry) {
    app.replaceChildren(root);
    root.append(ui.coming(page, 'This page is not in this build.'));
    return;
  }
  app.replaceChildren(h('div.loading', null, h('span.label', { text: 'Loading' })));
  try {
    const [html, js, css] = await Promise.all([
      entry.html ? decryptText(`pages/${page}.html`) : '',
      entry.js ? decryptText(`pages/${page}.js`) : null,
      entry.css ? decryptText(`pages/${page}.css`) : null,
    ]);
    if (token !== current.token) return; // user navigated away meanwhile
    root.innerHTML = html;
    if (ASOF[page]) root.prepend(h('p.asof-note', null, ASOF[page] + ' ', h('a', { href: '#/journey', text: 'Journey' }), ' and ', h('a', { href: '#/today', text: 'Today' }), ' cover what came after.'));
    if (css) root.prepend(h('style', { text: css }));
    app.replaceChildren(root);
    window.scrollTo(0, 0);
    const cleanups = [];
    const ctx = {
      root, page, params, query, data, charts, ui, h, deck, glossary,
      asset, nav: (hash) => { location.hash = hash; },
      onCleanup: (fn) => cleanups.push(fn),
    };
    if (js) {
      const url = URL.createObjectURL(new Blob([js], { type: 'text/javascript' }));
      try {
        const mod = await import(url);
        if (token !== current.token) return;
        if (typeof mod.default === 'function') {
          const ret = await mod.default(ctx);
          if (typeof ret === 'function') cleanups.push(ret);
        }
      } finally { URL.revokeObjectURL(url); }
    }
    current.cleanup = () => cleanups.forEach((f) => f());
    ui.enhanceTerms(root);
    // move focus to the page for keyboard and screen-reader users (not on first load)
    const focusTarget = root.querySelector('h1, .statement, .anchor') || root;
    if (route._moved) { focusTarget.tabIndex = -1; focusTarget.focus({ preventScroll: true }); }
    route._moved = true;
  } catch (err) {
    if (token !== current.token || document.body.classList.contains('locked')) return;
    console.error('[router] ' + page + ': ' + (err && (err.stack || err.message)));
    if (String(err.message).includes('locked') || err.name === 'OperationError') { lock(); showGate('Enter the password again.', true); return; }
    root.replaceChildren(ui.coming(page, 'This page failed to load.'), h('p.muted', { text: err.message }));
    app.replaceChildren(root);
  }
}
window.addEventListener('hashchange', route);

// ---------------------------------------------------------------- boot
(async function boot() {
  if (hasKey()) await enter();
  else showGate('');
})();
