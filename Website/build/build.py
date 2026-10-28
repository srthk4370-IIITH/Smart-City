#!/usr/bin/env python3
"""Build the evidence site: collect -> validate -> gzip -> encrypt -> dist/.

    SITE_PASSWORD=... py -3 Website/build/build.py [--no-collect] [--mock] [--out DIR]

What it does
  1. collect   runs Website/build/collect/run_all.py (DATA agent) unless --no-collect
  2. validate  every data/**/*.json parses, has {meta, series} (datasets), no forbidden raw-data keys
  3. encrypt   every file under data/ and src/pages/ -> dist/<same path>.enc
               format: IV(12 random bytes) || AES-256-GCM(gzip(file)) with AAD = "<site path>"
               key  = PBKDF2-HMAC-SHA256(password, random 16-byte salt, 600,000 iterations, 32 bytes)
  4. auth      dist/auth.json = {bcrypt hash (cost 12), pbkdf2 salt + iterations}; check.txt.enc canary
  5. shell     copies index.html, css/, js/, vendor/ in plain (no content in them) + Cloudflare _headers
  6. checks    password never appears in dist/, dist/data and dist/pages hold only *.enc

The password is read from the environment only and is never written or printed.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import bcrypt
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
except ImportError:  # pragma: no cover
    sys.exit("Missing build deps. Run:  py -3 -m pip install bcrypt cryptography")

WEB = Path(__file__).resolve().parents[1]           # Website/
SRC = WEB / "src"
DATA = WEB / "data"
MOCK = SRC / "dev-mock" / "data"
COLLECT = WEB / "build" / "collect"

PBKDF2_ITER = 600_000
BCRYPT_COST = 12
PLAIN_DIRS = ["css", "js", "vendor"]                 # shell + libraries: no project content
PLAIN_FILES = ["index.html", "favicon.svg"]
SKIP_SUFFIXES = {".md", ".map"}
FORBIDDEN_KEYS = {"xs", "base", "prompt", "prompts", "raw", "text", "observations",
                  "values", "series_values", "readings"}

HEADERS = """/*
  Content-Security-Policy: default-src 'self'; script-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self'; connect-src 'self' blob:; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  X-Frame-Options: DENY
  X-Robots-Tag: noindex, nofollow
  Permissions-Policy: camera=(), microphone=(), geolocation=()

/
  Cache-Control: no-cache, no-store, must-revalidate

/index.html
  Cache-Control: no-cache, no-store, must-revalidate

/auth.json
  Cache-Control: no-cache, no-store, must-revalidate

/check.txt.enc
  Cache-Control: no-cache

/js/*
  Cache-Control: no-cache

/css/*
  Cache-Control: no-cache

/data/*
  Cache-Control: no-cache

/pages/*
  Cache-Control: no-cache

/vendor/*
  Cache-Control: public, max-age=604800
"""


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


# ------------------------------------------------------------------ crypto
def derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITER)
    return kdf.derive(password.encode("utf-8"))


def encrypt_to(aes: AESGCM, plain: bytes, site_path: str, out: Path) -> None:
    """site_path = path the browser asks for, without .enc (also the AAD)."""
    gz = gzip.compress(plain, compresslevel=9, mtime=0)
    iv = os.urandom(12)
    ct = aes.encrypt(iv, gz, site_path.encode("utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(iv + ct)


# ------------------------------------------------------------------ steps
def run_collect() -> None:
    runner = COLLECT / "run_all.py"
    if runner.exists():
        log("collect: run_all.py")
        r = subprocess.run([sys.executable, str(runner)], cwd=str(WEB.parent))
        if r.returncode != 0:
            log(f"collect: run_all.py exited {r.returncode} - continuing with the data already in data/")
        return
    scripts = sorted(p for p in COLLECT.glob("*.py") if not p.name.startswith("_"))
    for p in scripts:
        log(f"collect: {p.name}")
        r = subprocess.run([sys.executable, str(p)], cwd=str(WEB.parent))
        if r.returncode != 0:
            log(f"collect: {p.name} exited {r.returncode} - continuing")


def forbidden_keys(obj, path="") -> list[str]:
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            # a single number (e.g. a count of readings) is an aggregate, not raw data; lists/strings still fail
            if k in FORBIDDEN_KEYS and not (isinstance(v, (int, float)) and not isinstance(v, bool)):
                hits.append(f"{path}/{k}")
            hits += forbidden_keys(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5000]):
            hits += forbidden_keys(v, f"{path}[{i}]")
    return hits


def _load_shared_check():
    """Use the DATA agent's own raw-data check (collect/_lib.py: check_no_raw) as well, so both agree."""
    try:
        sys.path.insert(0, str(COLLECT))
        from _lib import check_no_raw  # type: ignore
        return check_no_raw
    except Exception:  # noqa: BLE001
        return None
    finally:
        if sys.path and sys.path[0] == str(COLLECT):
            sys.path.pop(0)


_shared_check = None


def validate(data_dir: Path) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    for f in sorted(data_dir.rglob("*.json")):
        rel = f.relative_to(data_dir).as_posix()
        if rel.startswith("raw/"):   # SPEC data policy item 3: raw explorer data (encrypted like all data); guard skipped here only
            continue
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{rel}: invalid JSON ({e})")
            continue
        hits = forbidden_keys(obj)
        if _shared_check:
            hits = sorted(set(hits) | set(_shared_check(obj)))
        if hits:
            errors.append(f"{rel}: forbidden raw-data keys {hits[:5]}")
        if "/" in rel and not rel.startswith("packs/"):          # a dataset file: data/<topic>/<id>.json
            if not isinstance(obj, dict) or "meta" not in obj or "series" not in obj:
                warnings.append(f"{rel}: not a {{meta, series}} dataset")
            elif not obj["meta"].get("source_files"):
                warnings.append(f"{rel}: meta.source_files is empty")
    cat = data_dir / "catalog.json"
    if cat.exists():
        try:
            entries = json.loads(cat.read_text(encoding="utf-8"))
            entries = entries if isinstance(entries, list) else entries.get("datasets", [])
            for e in entries:
                if not (data_dir / e.get("topic", "?") / f"{e.get('id', '?')}.json").exists():
                    warnings.append(f"catalog.json: {e.get('id')} has no file {e.get('topic')}/{e.get('id')}.json")
        except Exception as e:  # noqa: BLE001
            errors.append(f"catalog.json: {e}")
    else:
        warnings.append("data/catalog.json missing (pages that load datasets by id will show 'data missing')")
    for name in ("status.json", "decisions.json", "route.json", "qa.json"):
        if not (data_dir / name).exists():
            warnings.append(f"data/{name} missing")
    return errors, warnings


def copy_plain(out: Path) -> None:
    for name in PLAIN_FILES:
        shutil.copy2(SRC / name, out / name)
    for d in PLAIN_DIRS:
        for f in (SRC / d).rglob("*"):
            if f.is_file() and f.suffix not in SKIP_SUFFIXES:
                dst = out / d / f.relative_to(SRC / d)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
    # licences must ship with the vendored code
    for f in (SRC / "vendor").rglob("*"):
        if f.is_file() and (f.name.upper().startswith(("LICENSE", "NOTICE")) or f.name == "VERSIONS.md" or f.name == "README.upstream.md"):
            dst = out / "vendor" / f.relative_to(SRC / "vendor")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
    (out / "_headers").write_text(HEADERS, encoding="utf-8")


def page_manifest(pages_dir: Path) -> dict:
    pages = {}
    assets = []
    for f in sorted(pages_dir.rglob("*")):
        if not f.is_file() or f.name.startswith("_") or f.suffix == ".md":
            continue
        rel = f.relative_to(pages_dir).as_posix()
        if "/" not in rel and f.suffix in (".html", ".js", ".css"):
            pages.setdefault(f.stem, {})[f.suffix[1:]] = True
        else:
            assets.append(rel)
    return {"pages": pages, "assets": assets}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-collect", action="store_true", help="skip build/collect (use data/ as it is)")
    ap.add_argument("--mock", action="store_true", help="use src/dev-mock/data instead of data/")
    ap.add_argument("--out", default=str(WEB / "dist"))
    args = ap.parse_args()

    password = os.environ.get("SITE_PASSWORD", "")
    if len(password) < 8:
        sys.exit("SITE_PASSWORD is not set (or shorter than 8 characters). Example:\n"
                 "  SITE_PASSWORD='...' py -3 Website/build/build.py")

    out = Path(args.out).resolve()
    if out == WEB or out == SRC or WEB not in out.parents and out.name != "dist":
        sys.exit(f"refusing to write to {out}")

    if not args.no_collect and not args.mock:
        run_collect()

    data_dir = MOCK if args.mock else DATA
    if not args.mock and (not DATA.exists() or not any(DATA.rglob("*.json"))):
        log("data/ is empty - falling back to src/dev-mock/data (MOCK numbers!)")
        data_dir = MOCK
    global _shared_check
    _shared_check = _load_shared_check()
    errors, warnings = validate(data_dir)
    for w in warnings:
        log("warn: " + w)
    if errors:
        for e in errors:
            log("ERROR: " + e)
        return 1

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    salt = os.urandom(16)
    key = derive_key(password, salt)
    aes = AESGCM(key)
    bhash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_COST)).decode("ascii")
    bhash = "$2a$" + bhash[4:]          # same algorithm; the 2a prefix is accepted by every bcryptjs version
    auth = {
        "v": 1,
        "bcrypt": bhash,
        "pbkdf2": {"hash": "SHA-256", "iterations": PBKDF2_ITER, "salt": base64.b64encode(salt).decode("ascii")},
        "cipher": "AES-256-GCM, 96-bit random IV prefix, AAD = site path, gzip inside",
        "built_at": dt.datetime.now().replace(microsecond=0).isoformat(),
    }
    (out / "auth.json").write_text(json.dumps(auth, indent=1), encoding="utf-8")
    encrypt_to(aes, b"ok", "check.txt", out / "check.txt.enc")

    # data
    n_data = 0
    for f in sorted(data_dir.rglob("*")):
        if f.is_file():
            rel = "data/" + f.relative_to(data_dir).as_posix()
            encrypt_to(aes, f.read_bytes(), rel, out / (rel + ".enc"))
            n_data += 1

    # pages (html/js/css/images) + manifest + glossary
    pages_dir = SRC / "pages"
    n_pages = 0
    for f in sorted(pages_dir.rglob("*")):
        if f.is_file() and f.suffix != ".md":
            rel = "pages/" + f.relative_to(pages_dir).as_posix()
            encrypt_to(aes, f.read_bytes(), rel, out / (rel + ".enc"))
            n_pages += 1
    manifest = page_manifest(pages_dir)
    manifest["built_at"] = auth["built_at"]
    manifest["data_source"] = "mock" if data_dir == MOCK else "data"
    encrypt_to(aes, json.dumps(manifest).encode("utf-8"), "pages/_manifest.json", out / "pages" / "_manifest.json.enc")

    copy_plain(out)

    # ---- leak checks
    pw_bytes = password.encode("utf-8")
    bad = []
    for f in out.rglob("*"):
        if not f.is_file():
            continue
        blob = f.read_bytes()
        if pw_bytes in blob:
            bad.append(f"password found in {f.relative_to(out)}")
        top = f.relative_to(out).parts[0]
        if top in ("data", "pages") and f.suffix != ".enc":
            bad.append(f"plain file in encrypted area: {f.relative_to(out)}")
    if bad:
        for b in bad:
            log("LEAK: " + b)
        shutil.rmtree(out)
        return 2

    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    log(f"ok: {n_data} data files + {n_pages} page files encrypted, data from "
        f"{'src/dev-mock (MOCK)' if data_dir == MOCK else 'data/'}; dist = {size / 1e6:.1f} MB at {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
