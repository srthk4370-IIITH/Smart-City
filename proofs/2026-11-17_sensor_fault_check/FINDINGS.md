# Why so many sensor_fault incidents (2026-11-17, read-only check, no fix)
Board /api/incidents (last 300): 141 sensor_fault, 126 warning, 31 critical, 2 normal.
- 139/141 created 2026-10-13..17 (slider/demo era, older agent on NPU), 2 on live campus data (INC-0736, INC-0740).
- 130/141 air_quality, nearly all SR-AQ-KH03-03 co2 (demo-scenario target node). Window = one-sample step ~450 -> ~2000 ppm, then flat +-6.
  Campus API never had this: KH03-03 co2 max 923 (Oct 14), 784-1150 all AQ nodes, max 5-min jump 151 ppm.
- Who said it: agent SF + reasoner SF 133; reasoner overrode a non-SF agent 4 (e.g. INC-0717: agent "warning, normal conditions", reasoner "stuck");
  deterministic 4. Agent fault_kind bias 131, stuck 4.
- Retrieval: 119/141 had >=2 of 3 retrieved neighbours already sensor_fault (same node) -> self-reinforcing.
- Reasoner text: physically 44, offset/bias 37, repair/history 36, empty/vacant 29 (occupancy SR-OC-GW-KH95-01 linked to KH03 room).
- Live cases: SR-EM-KH04-01 power_kw: campus 'power' is W (2.6-3 W standby, 50-300 W spikes) -> kW = 0.003 -> 2-dp card -> 0.00 x 48 pts
  -> "flatline / stuck" -> sensor_fault. INC-0740 title "Normal operation: Power sensor fault, Wind speed sensor fault" (synth rejected by policy).
Raw: WSL /tmp/inc.json, /tmp/sfd/all.jsonl; scripts in session scratchpad sf*.sh/py.
