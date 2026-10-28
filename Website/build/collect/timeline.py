"""Timeline datasets: commits (git log, read-only), proof folders, project milestones."""
import subprocess
from _lib import *

S = __file__
T = "timeline"


def commits():
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "log", "--reverse", "--date=iso-strict", "--format=@@%h|%ad|%s", "--shortstat"],
                             capture_output=True, text=True, encoding="utf-8", timeout=60).stdout
    except Exception as e:
        out = ""
    rows, cur = [], None
    for line in out.splitlines():
        if line.startswith("@@"):
            h, d, s = line[2:].split("|", 2)
            cur = {"hash": h, "date": d, "subject": s, "files": 0, "insertions": 0, "deletions": 0}
            rows.append(cur)
        elif cur and "changed" in line:
            m = re.search(r"(\d+) files? changed", line); cur["files"] = int(m.group(1)) if m else 0
            m = re.search(r"(\d+) insertions?", line); cur["insertions"] = int(m.group(1)) if m else 0
            m = re.search(r"(\d+) deletions?", line); cur["deletions"] = int(m.group(1)) if m else 0
    write(T, "tl_commits", "Commits on the project (git log, read-only)", "files changed",
          [ser("commits", [pt(r["date"], r["files"], subject=r["subject"], hash=r["hash"], insertions=r["insertions"], deletions=r["deletions"]) for r in rows], "ours")],
          [".git (git log --shortstat)"], S, n=len(rows), chart={"type": "timeline"},
          notes="Work after the last commit (htpd window UX, refinements, long-range checks, retrain v2) is in the working tree and proofs/.")


def proofs():
    pts = []
    for p in sorted(PROOFS.iterdir()):
        if p.is_dir():
            files = [f for f in p.rglob("*") if f.is_file()]
            pts.append(pt(p.name[:10], len(files), folder=p.name, mb=round(sum(f.stat().st_size for f in files) / 1e6, 1),
                          results=[rel(f) for f in files if f.name in ("RESULTS.md", "DEVICE_RESULTS.md", "summary.json", "evaluate_test.md")]))
        else:
            pts.append(pt(p.name[:10], 1, folder=p.name, mb=round(p.stat().st_size / 1e6, 3)))
    write(T, "tl_proofs", "Proof folders (raw evidence kept locally)", "files", [ser("proof runs", pts, "ours")], [PROOFS], S, n=len(pts),
          chart={"type": "timeline"}, notes="Raw per-sample files (cases/prompts with sensor values) stay local; the site shows aggregates and scores.")


def milestones():
    ms = [("2026-09-17", "PRD v2.0 written (target architecture, Llama + Qwen)", "PRD.md"),
          ("2026-09-30", "initial commit, clean repo", "git"),
          ("2026-10-01", "plan: prove on laptop, then port; fine-tune as fallback; Go backend over adb", "plan.md, app.md, training_plan.md"),
          ("2026-10-07", "v1 fine-tune trained overnight (94% host pattern), first NPU export validated", "HANDBOOK 2.7"),
          ("2026-10-07", "quantisation gap closed to 82.6-85.2% (GPTQ + double-BOS fix)", "HANDBOOK 2.7"),
          ("2026-10-08", "native QIDK app via local adbd; event gate; NPU retries", "HANDBOOK 4.1"),
          ("2026-10-10", "problems_setup.md: every road taken on the board", "problems_setup.md"),
          ("2026-10-13", "latency plan v2; action derived (+3.7 pts); export identity guarded", "latency_roadmap.md, HANDBOOK 2.8-2.9"),
          ("2026-10-14", "latency day: ctx 2048, genied, trim, batch window; LADE/grammar/continuous batching rejected", "HANDBOOK 2.10-2.30"),
          ("2026-10-15", "stress testing through the app (238/240), night-run hardening, mid-evaluation deck", "HANDBOOK 2.31-2.35, ppt.md"),
          ("2026-10-15", "mid-evaluation; evaluators ask for evidence, GPU study, data", "HANDBOOK 2.36"),
          ("2026-10-16", "GPU/NPU/hybrid grid; htpd batched NPU daemon (12-agent chaos ≈ 47 s -> 20.7 s)", "HANDBOOK 2.37"),
          ("2026-10-16", "window study (4 h best), placement study (42% at 40 min), refinements, 12 h checks, AI titles", "HANDBOOK 2.38-2.39"),
          ("2026-10-17", "retrain v2 data built (35,946 rows, 6 roles), training started", "HANDBOOK 2.40"),
          ("2026-10-19", "retrain v2 at 56%+, best dev loss 0.066; evidence website agreed", "HANDBOOK 2.40, Website/SPEC.md")]
    write(T, "tl_milestones", "Project milestones", "-", [ser("milestones", [pt(d, i + 1, what=w, source=s) for i, (d, w, s) in enumerate(ms)], "ours")],
          [ROOT / "PRD.md", ROOT / "plan.md", HB, ROOT / "ppt.md", WEB / "SPEC.md"], S, n=len(ms), chart={"type": "timeline"})


def main():
    commits(); proofs(); milestones()


if __name__ == "__main__":
    main()
