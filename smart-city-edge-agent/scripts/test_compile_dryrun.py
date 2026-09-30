import os
import sys
from pathlib import Path

# Verify HF Token
cached_token = Path.home() / ".cache" / "huggingface" / "token"
print("Cached token exists:", cached_token.exists())
if cached_token.exists():
    print("Token starts with:", cached_token.read_text().strip()[:8] + "...")

# Check local model paths
merged = Path("models/merged/llama-orchestrator-agent").resolve()
base = Path("models/base/llama-3.2-3b-instruct").resolve()
print("Local merged exists:", merged.exists(), (merged / "config.json").exists())
print("Local base exists:", base.exists(), (base / "config.json").exists())

# Check qai_hub client
import qai_hub
print("qai_hub version:", getattr(qai_hub, "__version__", "unknown"))
devices = qai_hub.get_devices()
print("Successfully connected to Qualcomm AI Hub! Available device count:", len(devices))
