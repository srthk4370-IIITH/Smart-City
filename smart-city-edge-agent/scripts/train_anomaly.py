"""Backward-compatible entry point for real per-domain anomaly training.

Deprecated name retained for older notes. Unlike the original prototype, this
never generates synthetic values and never writes an untrained model.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from smart_city_edge.training_data import SPECS
from train_domain_anomaly import train_one


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train deterministic per-domain anomaly models")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parents[1] / "models" / "anomaly")
    parser.add_argument("--domain", choices=[*SPECS, "all"], default="all")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--limit", type=int, default=5_000)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--assume-unlabeled-normal", action="store_true")
    args = parser.parse_args()
    for domain in (SPECS if args.domain == "all" else (args.domain,)):
        train_one(args.data_dir, args.output_dir, domain, None if args.full else args.limit, args.seed, args.epochs, args.assume_unlabeled_normal)
