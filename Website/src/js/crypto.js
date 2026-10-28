// Password gate + content decryption.
// Format of every dist/**/*.enc file:  IV (12 bytes) || AES-256-GCM( gzip(plaintext) ) incl. 16-byte tag.
// Additional authenticated data = the file's site path without ".enc" (e.g. "data/catalog.json"),
// so an encrypted file cannot be swapped for another one.
// Key = PBKDF2-SHA256(password, salt, iterations) -> 256 bits.  The password is checked first with bcrypt.

const KEY_SLOT = 'site.key.v1';
const FAIL_SLOT = 'site.fails.v1';
const te = new TextEncoder();
const td = new TextDecoder();

let authCache = null;
let keyPromise = null;

function b64ToBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function bytesToB64(bytes) {
  let s = '';
  const u = new Uint8Array(bytes);
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
  return btoa(s);
}

function ssGet(k) { try { return sessionStorage.getItem(k); } catch { return null; } }
function ssSet(k, v) { try { sessionStorage.setItem(k, v); } catch { /* private mode: key lives in memory only */ } }
function ssDel(k) { try { sessionStorage.removeItem(k); } catch { /* ignore */ } }

async function loadAuth() {
  if (authCache) return authCache;
  const r = await fetch('auth.json', { cache: 'no-store' });
  if (!r.ok) throw new Error('auth.json missing (was the site built?)');
  authCache = await r.json();
  return authCache;
}

function bcryptCompare(pw, hash) {
  const bc = (window.dcodeIO && window.dcodeIO.bcrypt) || window.bcrypt;
  if (!bc) return Promise.reject(new Error('bcrypt library not loaded'));
  return new Promise((resolve, reject) => {
    bc.compare(pw, hash, (err, ok) => (err ? reject(err) : resolve(ok)));
  });
}

async function deriveRaw(pw, auth) {
  const base = await crypto.subtle.importKey('raw', te.encode(pw), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', hash: 'SHA-256', salt: b64ToBytes(auth.pbkdf2.salt), iterations: auth.pbkdf2.iterations },
    base, 256);
  return new Uint8Array(bits);
}

function importAes(raw) {
  return crypto.subtle.importKey('raw', raw, { name: 'AES-GCM' }, false, ['decrypt']);
}

/** Small exponential delay after failed attempts (per tab). Returns ms still to wait. */
export function lockoutRemaining() {
  try {
    const f = JSON.parse(ssGet(FAIL_SLOT) || '{"n":0,"t":0}');
    if (f.n < 3) return 0;
    const wait = Math.min(30000, 1000 * 2 ** (f.n - 3));
    return Math.max(0, f.t + wait - Date.now());
  } catch { return 0; }
}
function noteFailure() {
  let f = { n: 0, t: 0 };
  try { f = JSON.parse(ssGet(FAIL_SLOT) || '{"n":0,"t":0}'); } catch { /* ignore */ }
  f.n += 1; f.t = Date.now();
  ssSet(FAIL_SLOT, JSON.stringify(f));
}

/**
 * Try a password. Resolves {ok:true} or {ok:false, reason}.
 * bcrypt and PBKDF2 run in parallel; the derived key is only kept if bcrypt says yes
 * and it decrypts the canary file.
 */
export async function unlock(pw) {
  const wait = lockoutRemaining();
  if (wait > 0) return { ok: false, reason: 'wait', wait };
  const auth = await loadAuth();
  const t0 = performance.now();
  const [ok, raw] = await Promise.all([bcryptCompare(pw, auth.bcrypt), deriveRaw(pw, auth)]);
  if (!ok) {
    noteFailure();
    // constant-ish floor so a fast "no" and a slow "no" look alike
    const spent = performance.now() - t0;
    if (spent < 600) await new Promise((r) => setTimeout(r, 600 - spent));
    return { ok: false, reason: 'wrong' };
  }
  const key = await importAes(raw);
  try {
    await decryptBytes('check.txt', key);
  } catch {
    return { ok: false, reason: 'stale' }; // auth.json and content from different builds
  }
  ssSet(KEY_SLOT, bytesToB64(raw));
  ssDel(FAIL_SLOT);
  keyPromise = Promise.resolve(key);
  return { ok: true, ms: Math.round(performance.now() - t0) };
}

export function hasKey() { return !!keyPromise || !!ssGet(KEY_SLOT); }

function getKey() {
  if (keyPromise) return keyPromise;
  const b = ssGet(KEY_SLOT);
  if (!b) return Promise.reject(new Error('locked'));
  keyPromise = importAes(b64ToBytes(b));
  return keyPromise;
}

export function lock() {
  ssDel(KEY_SLOT);
  keyPromise = null;
}

async function gunzip(bytes) {
  const ds = new DecompressionStream('gzip');
  const stream = new Blob([bytes]).stream().pipeThrough(ds);
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Fetch "<path>.enc", decrypt, gunzip. `path` is relative to the site root, e.g. "data/catalog.json". */
export async function decryptBytes(path, key) {
  const k = key || (await getKey());
  const r = await fetch(path + '.enc', { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  const buf = new Uint8Array(await r.arrayBuffer());
  const iv = buf.subarray(0, 12);
  const ct = buf.subarray(12);
  const plainGz = await crypto.subtle.decrypt({ name: 'AES-GCM', iv, additionalData: te.encode(path), tagLength: 128 }, k, ct);
  return gunzip(new Uint8Array(plainGz));
}

export async function decryptText(path) { return td.decode(await decryptBytes(path)); }
export async function decryptJSON(path) { return JSON.parse(await decryptText(path)); }
