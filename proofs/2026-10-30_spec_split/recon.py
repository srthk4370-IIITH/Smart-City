# recon.py: rebuild the reasoner's per-stream token sequences (pick vs forced) from a final answer text.
# Python port of htpd's Forcer (Code/smart-city-edge-agent/app/htpd/reason_logic.h) and of the split decode
# handle() rule in htpd.cpp: after each model pick, the forcer's deterministic continuation is tokenized and all
# but its last token are injected as forced tokens (all of it if it ends the answer), capped at 64.
# The model's own picks are approximated by the first BPE token of the remaining answer text (Qwen3.5 tokenizer).
import copy
from tokenizers import Tokenizer

TOK_PATH = '/home/hp_srthk4370/models/qwen3.5-4b/tokenizer.json'


def bytes_to_unicode():
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("\xa1"), ord("\xac") + 1)) + list(range(ord("\xae"), ord("\xff") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b); cs.append(256 + n); n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


class Tok:
    def __init__(self, path=TOK_PATH):
        self.t = Tokenizer.from_file(path)
        u2b = {v: k for k, v in bytes_to_unicode().items()}
        self.piece = {}
        vocab = self.t.get_vocab()
        for s, i in vocab.items():
            try:
                self.piece[i] = bytes(u2b[c] for c in s)
            except KeyError:
                self.piece[i] = s.encode('utf-8')  # added/special tokens
        self.cache = {}

    def enc(self, b):
        """tokenize bytes (htpd tokenize: no BOS, specials parsed)"""
        return self.t.encode(b.decode('utf-8', errors='surrogateescape') if isinstance(b, bytes) else b,
                             add_special_tokens=False).ids

    def enc_str(self, s):
        return self.t.encode(s, add_special_tokens=False).ids

    def first_token(self, buf, p, win=96):
        """the first BPE token of buf[p:], as (id, piece bytes)"""
        # move back to a utf-8 char boundary
        c = p
        while c > 0 and (buf[c] & 0xC0) == 0x80:
            c -= 1
        seg = buf[c:c + win]
        # cut seg at a char boundary at its end
        e = len(seg)
        while e > 0 and e < len(seg) and (seg[e] & 0xC0) == 0x80:
            e -= 1
        s = seg[:e].decode('utf-8', errors='replace')
        ids = self.enc_str(s)
        off = c
        for i in ids:
            pb = self.piece[i]
            if off == p:
                return i, pb
            off += len(pb)
            if off > p:
                break
        # straddling a char: fall back to single-byte token
        b = buf[p:p + 1]
        for i, pb in self.piece.items():
            if pb == b:
                return i, b
        raise RuntimeError('no token')


ROOT, FORCED, STR, NUM, BOOL, ARR_FIRST, ARR_NEXT, DONE, OFF = range(9)


class Forcer:
    """byte-level port of htpd::Forcer"""

    def __init__(self, S):
        self.S = S
        self.mode = ROOT if S else OFF
        self.st = []  # [obj, key, idx]
        self.need = b''
        self.then_key = ''
        self.then_push = ''
        self.then_close = False
        self.key = ''
        self.val = b''
        self.esc = False
        self.ndig = 0

    def clone(self):
        f = copy.copy(self)
        f.st = [list(x) for x in self.st]
        return f

    def active(self): return self.mode != OFF
    def done(self): return self.mode == DONE
    def constrained(self): return self.mode not in (OFF, ROOT)

    def type_of(self, k): return self.S['types'].get(k, '')
    def enum_of(self, k): return self.S['enums'].get(k)

    def keys_of(self, f):
        return self.S['keys'] if f[1] == '' else self.S['items'][f[1]]

    @staticmethod
    def opener(ty):
        if ty == 'str': return '"'
        if ty in ('arr_str', 'arr_obj'): return '['
        return ''

    def force(self, n, k, push, close):
        self.mode = FORCED; self.need = n.encode() if isinstance(n, str) else n
        self.then_key = k; self.then_push = push; self.then_close = close

    def force_key(self, pre, k, push=''):
        self.force(pre + '"' + k + '": ' + self.opener(self.type_of(k)), k, push, False)

    def begin_value(self, k):
        ty = self.type_of(k)
        self.key = k; self.val = b''; self.esc = False; self.ndig = 0
        if ty == 'str': self.mode = STR
        elif ty == 'num': self.mode = NUM
        elif ty == 'bool': self.mode = BOOL
        elif ty in ('arr_str', 'arr_obj'): self.st.append([False, k, 0]); self.mode = ARR_FIRST
        else: self.mode = OFF

    def after_value(self):
        if not self.st: self.mode = DONE; return
        f = self.st[-1]
        if not f[0]: self.mode = ARR_NEXT; return
        ks = self.keys_of(f)
        if f[2] < len(ks):
            k = ks[f[2]]; f[2] += 1; self.force_key(', ', k)
        else:
            self.force('}', '', '', True)

    def start_item(self, pre, c):
        a = self.st[-1]
        ty = self.type_of(a[1])
        if ty == 'arr_obj':
            ks = self.S['items'][a[1]]
            if pre == '':
                if c != ord('{'): return False, False
                self.force_key('', ks[0], a[1]); return True, True
            self.force_key(' {', ks[0], a[1]); return True, False
        if pre == '':
            if c != ord('"'): return False, False
            self.key = a[1]; self.val = b''; self.esc = False; self.mode = STR; return True, True
        self.force(' "', '', '', False)
        self.then_push = '\x01' + a[1]
        return True, False

    @staticmethod
    def is_any(v, en): return any(v == l.encode() for l in en)
    @staticmethod
    def is_prefix_of_any(v, en): return any(l.encode().startswith(v) for l in en)

    def step(self, c):
        m = self.mode
        if m == OFF: return True
        if m == DONE: return False
        if m == ROOT:
            if c in b' \n\r\t': return True
            if c != ord('{'): self.mode = OFF; return True
            self.st.append([True, '', 1]); self.force_key('', self.S['keys'][0]); return True
        if m == FORCED:
            if not self.need or c != self.need[0]: return False
            self.need = self.need[1:]
            if self.need: return True
            if self.then_close: self.st.pop(); self.after_value(); return True
            if self.then_push and self.then_push[0] == '\x01':
                self.key = self.then_push[1:]; self.val = b''; self.esc = False; self.mode = STR; self.then_push = ''; return True
            if self.then_push: self.st.append([True, self.then_push, 1])
            self.begin_value(self.then_key); return True
        if m == STR:
            en = self.enum_of(self.key)
            if c < 0x20: return False
            if self.esc:
                if en: return False
                self.esc = False; return True
            if c == ord('\\'):
                if en: return False
                self.esc = True; return True
            if c == ord('"'):
                if en and not self.is_any(self.val, en): return False
                self.after_value(); return True
            if en:
                if not self.is_prefix_of_any(self.val + bytes([c]), en): return False
                self.val += bytes([c])
            return True
        if m == NUM:
            if ord('0') <= c <= ord('9'): self.ndig += 1; return True
            if c in b'-+.eE': return True
            if self.ndig == 0: return False
            self.after_value(); return self.step(c)
        if m == BOOL:
            tf = ['true', 'false']
            if not self.is_prefix_of_any(self.val + bytes([c]), tf): return False
            self.val += bytes([c])
            if self.is_any(self.val, tf): self.after_value()
            return True
        if m == ARR_FIRST:
            if c == ord(']'): self.st.pop(); self.after_value(); return True
            ok, consumed = self.start_item('', c)
            return ok and consumed
        if m == ARR_NEXT:
            if c == ord(']'): self.st.pop(); self.after_value(); return True
            if c != ord(','): return False
            ok, _ = self.start_item(' ', c)
            return ok
        return False

    def feed(self, s):
        for c in s:
            if not self.step(c): return False
        return True

    def allows(self, piece):
        if not self.constrained(): return True
        if not piece: return False
        return self.clone().feed(piece)

    def forced_text(self, cap=256):
        if not self.constrained(): return b''
        f = self.clone(); out = b''; it = 0
        while len(out) < cap and it < 1024:
            it += 1
            if f.mode == FORCED:
                n = f.need; out += n
                for c in n: f.step(c)
                continue
            if f.mode == STR:
                en = f.enum_of(f.key)
                if not en: break
                cands = [l for l in en if l.encode().startswith(f.val)]
                if len(cands) != 1: break
                rest = cands[0].encode()[len(f.val):] + b'"'
                out += rest
                for c in rest: f.step(c)
                continue
            break
        return out


def replay(tok, S, text, sentinel=None, fork_key=None, ap=b''):
    """Replay htpd's decode over `text` (bytes) with schema S.
    Returns dict: toks, pick (bool list), fork (index of the fork pick or None), end (index after the last pick),
    stop, mismatches."""
    f = Forcer(S)
    f.feed(ap)
    toks, pick = [], []
    p = 0
    fork = None
    stop = 'eot'
    mism = 0
    fk = ('"' + fork_key + '"').encode() if fork_key else None
    sk = ('"' + sentinel + '"').encode() if sentinel else None
    while p < len(text):
        tid, pb = tok.first_token(text, p)
        if f.constrained() and not f.allows(pb):
            # constrained pick: the longest allowed single-token prefix
            found = False
            for L in range(len(pb) - 1, 0, -1):
                ids = tok.enc(pb[:L])
                if len(ids) == 1 and f.allows(pb[:L]):
                    tid, pb = ids[0], pb[:L]; found = True; break
            if not found:
                mism += 1
        toks.append(tid); pick.append(True)
        if not f.feed(pb):
            f = Forcer(None); mism += 1
        p += len(pb)
        if f.done(): stop = 'json'; break
        ft = f.forced_text()
        if fk and fork is None and fk in ft:
            fork = len(toks) - 1
        if sk and fork is not None and sk in ft:
            stop = 'json'; break
        if ft:
            g = f.clone(); g.feed(ft)
            ftk = tok.enc(ft)
            take = len(ftk) if g.done() else max(0, len(ftk) - 1)
            take = min(take, 64)
            acc = b''
            for j in range(take):
                pc = tok.piece[ftk[j]]
                if ft[len(acc):len(acc) + len(pc)] != pc: break
                if text[p:p + len(pc)] != pc:
                    mism += 1; break
                acc += pc
                toks.append(ftk[j]); pick.append(False)
                f.feed(pc); p += len(pc)
            if f.done(): stop = 'json'; break
    end = max(i for i, x in enumerate(pick) if x) + 1 if pick else 0
    return dict(toks=toks, pick=pick, fork=fork, end=end, stop=stop, mism=mism, consumed=p)


SPLIT3 = [['observations'],
          ['agent_checks', 'affected_domains', 'suspect_sensors', 'evidence', 'confidence'],
          ['checklist', 'monitor_next', 'needs_more_data', 'needs_deeper', 'explanation']]


def sub_schema(S, groups, gi, after='causal_chain'):
    head = []
    for k in S['keys']:
        head.append(k)
        if k == after: break
    keys = head + list(groups[gi])
    if gi + 1 < len(groups): keys.append(groups[gi + 1][0])
    s = dict(S); s['keys'] = keys
    return s


def split_streams(tok, S, answer, groups=SPLIT3, after='causal_chain'):
    """per-stream sequences of the split-3 decode for the final assembled answer (str)."""
    a = answer
    pos = []
    for g in groups:
        i = a.find(', "' + g[0] + '": ')
        if i < 0: return None
        pos.append(i)
    head = a[:pos[0]]
    segs = [a[pos[i]:(pos[i + 1] if i + 1 < len(pos) else len(a))] for i in range(len(groups))]
    out = []
    for gi in range(len(groups)):
        txt = head + segs[gi]
        sent = None
        if gi + 1 < len(groups):
            txt += ', "' + groups[gi + 1][0] + '": ' + ('[' if groups[gi + 1][0] in S['items'] or S['types'].get(groups[gi + 1][0], '').startswith('arr') else '"') + 'x'
            sent = groups[gi + 1][0]
        r = replay(tok, sub_schema(S, groups, gi, after), txt.encode('utf-8'), sentinel=sent, fork_key=groups[gi][0])
        out.append(r)
    return out
