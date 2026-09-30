"""Train real, deterministic per-domain autoencoders from historical telemetry."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from smart_city_edge.anomaly_model import DenoisingAutoencoder, export_to_onnx
from smart_city_edge.training_data import SPECS, load_domain_features


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def train_one(data_dir: Path, output_dir: Path, domain: str, limit: int | None, seed: int, epochs: int, assume_unlabeled_normal: bool) -> None:
    if not assume_unlabeled_normal:
        raise ValueError("Refusing to treat unlabelled history as normal. Pass --assume-unlabeled-normal only after documenting the assumption.")
    try:
        import torch
    except ImportError as exc:
        raise SystemExit("PyTorch is required. Install requirements-training.txt in the supported WSL environment.") from exc
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    spec, raw = load_domain_features(data_dir, domain, limit)
    # Chronological 70/15/15 split: future rows cannot leak into model fitting.
    n = len(raw); train_end = int(n * .70); dev_end = int(n * .85)
    train_raw, dev_raw, test_raw = raw[:train_end], raw[train_end:dev_end], raw[dev_end:]
    medians = np.nanmedian(train_raw, axis=0)
    def impute(values: np.ndarray) -> np.ndarray:
        return np.where(np.isnan(values), medians, values).astype(np.float32)
    train_raw, dev_raw, test_raw = impute(train_raw), impute(dev_raw), impute(test_raw)
    mean = train_raw.mean(axis=0); std = train_raw.std(axis=0); std[std < 1e-6] = 1.0
    train, dev, test = (train_raw - mean) / std, (dev_raw - mean) / std, (test_raw - mean) / std
    model = DenoisingAutoencoder(input_dim=len(spec.fields))
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-5)
    criterion = torch.nn.MSELoss()
    tensor = torch.from_numpy(train)
    losses: list[float] = []
    model.train()
    for _ in range(epochs):
        permutation = torch.randperm(len(tensor))
        batch_losses = []
        for indexes in permutation.split(256):
            batch = tensor[indexes]
            noisy = batch + torch.randn_like(batch) * 0.02
            optimizer.zero_grad(); loss = criterion(model(noisy), batch); loss.backward(); optimizer.step()
            batch_losses.append(float(loss.detach()))
        losses.append(float(np.mean(batch_losses)))
    train_loss = model.compute_reconstruction_error(train)
    dev_loss = model.compute_reconstruction_error(dev)
    test_loss = model.compute_reconstruction_error(test)
    threshold = float(np.percentile(dev_loss, 99.0))
    target = output_dir / domain; target.mkdir(parents=True, exist_ok=True)
    onnx_path = export_to_onnx(model, len(spec.fields), target / "model.onnx")
    metadata = {
        "artifact_version": "2.0", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "unlabelled_normality_assumption", "domain": domain,
        "source_file": spec.filename, "source_sha256": _sha256(data_dir / spec.filename),
        "feature_order": list(spec.fields), "feature_units": list(spec.units),
        "imputation": "train_split_median", "split": "chronological_70_15_15", "seed": seed,
        "epochs": epochs, "train_samples": len(train), "dev_samples": len(dev), "test_samples": len(test),
        "normalization_mean": mean.tolist(), "normalization_std": std.tolist(), "normalization_median": medians.tolist(),
        "training_loss_by_epoch": losses, "threshold_source": "dev_99th_percentile", "threshold": threshold,
        "train_loss_mean": float(train_loss.mean()), "dev_loss_mean": float(dev_loss.mean()), "test_loss_mean": float(test_loss.mean()),
        "test_empirical_alert_rate": float((test_loss > threshold).mean()), "model_sha256": _sha256(onnx_path),
        "metrics_limit": "No incident labels were supplied; precision, recall, delay, and root-cause accuracy are intentionally not claimed.",
    }
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"{domain}: {len(train)}/{len(dev)}/{len(test)} train/dev/test; threshold={threshold:.6f}; model={onnx_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("models/anomaly"))
    parser.add_argument("--domain", choices=[*SPECS, "all"], default="all")
    parser.add_argument("--limit", type=int, default=50_000)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--assume-unlabeled-normal", action="store_true")
    args = parser.parse_args()
    for name in (SPECS if args.domain == "all" else (args.domain,)):
        train_one(args.data_dir, args.output_dir, name, args.limit, args.seed, args.epochs, args.assume_unlabeled_normal)
