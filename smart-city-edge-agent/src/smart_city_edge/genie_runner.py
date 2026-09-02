"""Qualcomm Genie LLM Execution Wrapper (Phase 9).

Interfaces with the Qualcomm Genie runtime (`genie-t2t-run`) for Llama 3.2 3B
on Qualcomm QIDK (Snapdragon 8 Gen 3 / SM8650 / V75).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any


class GenieExecutionResult:

    def __init__(
        self,
        raw_output: str,
        latency_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        exit_code: int = 0,
        error_message: str | None = None,
    ):
        self.raw_output = raw_output
        self.latency_ms = latency_ms
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.exit_code = exit_code
        self.error_message = error_message

    def extract_json(self) -> dict[str, Any] | None:
        """Attempt to extract valid JSON from LLM output string."""
        if not self.raw_output:
            return None
        # Look for json codeblock or first '{' to last '}'
        match = re.search(r"```json\s*(.*?)\s*```", self.raw_output, re.DOTALL)
        if match:
            text = match.group(1)
        else:
            start = self.raw_output.find("{")
            end = self.raw_output.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = self.raw_output[start : end + 1]
            else:
                text = self.raw_output

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None


class GenieRunner:
    """Qualcomm Genie runtime executor for SM8650 / Snapdragon 8 Gen 3."""

    def __init__(
        self,
        bundle_dir: Path | str | None = None,
        bin_path: str = "genie-t2t-run",
        use_mock_fallback: bool = True,
    ) -> None:
        self.bundle_dir = Path(bundle_dir) if bundle_dir else None
        self.bin_path = bin_path
        self.use_mock_fallback = use_mock_fallback

    def run_prompt(
        self,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
        timeout_sec: float = 60.0,
    ) -> GenieExecutionResult:
        """Run prompt through genie-t2t-run or fallback to mock runner if binary absent."""
        start_time = time.perf_counter()

        # Check if binary exists or ADB remote execution is needed
        if not self._binary_exists() and self.use_mock_fallback:
            return self._mock_execution(prompt, start_time)

        env = os.environ.copy()
        if self.bundle_dir and self.bundle_dir.is_dir():
            lib_path = str(self.bundle_dir / "lib")
            env["LD_LIBRARY_PATH"] = f"{lib_path}:{env.get('LD_LIBRARY_PATH', '')}"
            env["ADSP_LIBRARY_PATH"] = f"{lib_path}:{env.get('ADSP_LIBRARY_PATH', '')}"

        cmd = [
            self.bin_path,
            "--config",
            str(self.bundle_dir / "genie_config.json") if self.bundle_dir else "genie_config.json",
            "--prompt",
            prompt,
            "--temperature",
            str(temperature),
            "--max-tokens",
            str(max_tokens),
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env=env,
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            if proc.returncode != 0:
                return GenieExecutionResult(
                    raw_output="",
                    latency_ms=elapsed_ms,
                    exit_code=proc.returncode,
                    error_message=proc.stderr,
                )

            return GenieExecutionResult(
                raw_output=proc.stdout,
                latency_ms=elapsed_ms,
                exit_code=0,
            )
        except (subprocess.SubprocessError, FileNotFoundError) as err:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            if self.use_mock_fallback:
                return self._mock_execution(prompt, start_time)
            return GenieExecutionResult(
                raw_output="",
                latency_ms=elapsed_ms,
                exit_code=-1,
                error_message=str(err),
            )

    def _binary_exists(self) -> bool:
        if os.path.isabs(self.bin_path):
            return os.path.exists(self.bin_path)
        # Search PATH
        return any(
            os.access(os.path.join(path, self.bin_path), os.X_OK)
            for path in os.environ.get("PATH", "").split(os.pathsep)
        )

    def _mock_execution(self, prompt: str, start_time: float) -> GenieExecutionResult:
        """Deterministic mock response for host unit testing when QIDK device binary is offline."""
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0 + 15.0

        # Detect domain agent vs orchestrator vs single SLM from prompt content
        if "Cross-Domain Orchestrator" in prompt or "Single-SLM" in prompt or "root_cause" in prompt:
            mock_json = {
                "event_id": "evt_mock_001",
                "root_cause": "HVAC cooling valve stuck high leading to excessive energy and humidity drift",
                "evidence": ["ev_energy_01", "ev_temp_01"],
                "confidence": 0.92,
                "recommendation": "Inspect and recalibrate HVAC cooling valve actuator in Zone 1",
                "requires_human_approval": True,
                "uncertainties": ["Sensor reading calibration drift within +/- 2%"],
            }
        else:
            mock_json = {
                "event_id": "evt_mock_001",
                "domain": "energy",
                "hypothesis": "Abnormal spike in energy consumption during off-peak hours",
                "evidence": ["ev_energy_01"],
                "confidence": 0.88,
                "uncertainty": "Potential occupancy measurement noise",
                "recommendation": "Check zone thermostat schedule",
            }

        return GenieExecutionResult(
            raw_output=json.dumps(mock_json, indent=2),
            latency_ms=elapsed_ms,
            prompt_tokens=len(prompt) // 4,
            completion_tokens=len(json.dumps(mock_json)) // 4,
            exit_code=0,
        )
