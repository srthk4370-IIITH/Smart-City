# Smart City Edge Agent

An event-driven, on-device smart-city reasoning prototype for Qualcomm QIDK.

The intended host development environment is WSL2 Ubuntu 22.04, because that is the QIDK-documented build environment. Runtime inference and the Android application target the connected SM8650 QIDK (`arm64-v8a`, HTP V75, Android 14). The host is not part of the production inference path.

### Observed local environment — 2026-08-20

- WSL2 has `Ubuntu 24.04.4 LTS` with Python 3.12.3, not Ubuntu 22.04.
- Docker Desktop's WSL integration is disabled for that distribution, so `docker` cannot run in WSL yet.

Before using QIDK Docker, install/enable a supported Ubuntu 22.04 WSL distribution and enable it in Docker Desktop → Settings → Resources → WSL Integration. Do not use the host Windows Python runtime for the QIDK build.

## Current milestone

The repository now contains the data contract, device/run configuration, deployment scripts, and tests. It deliberately does not invent sensor data or model artifacts. When data is supplied, implement ingestion, feature extraction, rules, anomaly training, and the matched rule/single-SLM/multi-agent evaluation on top of this contract.

## References in the adjacent QIDK checkout

- `../qidk/GenAI-Solutions/AI-Assistant`: Genie C++/JNI reference.
- `../qidk/GenAI-Solutions/ASR-LLM-TTS`: Llama 3.2 3B and optional ASR/TTS reference.
- `../qidk/Tools/qairt_docker`: supported Ubuntu/Docker build environment.

## Setup in WSL2

```bash
cd /mnt/c/Users/hp/Desktop/qidk/smart-city-edge-agent
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
pytest -q
```

Start the QIDK container from the adjacent QIDK checkout only after Docker is configured:

```bash
../qidk/Tools/qairt_docker/run_qairt_docker.sh \
  -m /mnt/c/Users/hp/Desktop/qidk \
  -t /local
```

See `../steps.md` for the ordered implementation and validation gates.
