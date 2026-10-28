# HVAC data findings (for the v2 HVAC agent)

Aggregates only; no raw values. Evidence: `proofs/2026-10-16_hvac_data/` (column and unit aggregates,
the scripts that produced them, the label check on real windows, and the test output).

## Sources
| Source | What it is | Used for |
|---|---|---|
| `data/series/hvac/AC-KH{00,01,02,03,95}.csv` (v1) | Per-floor aggregates: `ac_units_on`, `ac_units_reporting`, floor-mean `room_temp` | The current app (`AC-KH03` in sensors.json, `hvacFinding`). Too coarse for setpoint, cycling or stuck checks. |
| `ihub-clean-datasets/SR-AC.csv` (1.57 GB, 11.46 M rows) | One row per indoor-unit reading | Source of the new per-unit series |
| `data/series/hvac_units/SR-AC-*.csv` (new, gitignored) | 5-min per-unit series made by `training/v2/extract_hvac_units.py` | v2 HVAC agent |
| `data/series/occupancy/SR-OC-GW-KH95-*.csv` | 7 binary occupancy sensors | Optional context only (see below) |

## Units, coverage, sampling
- **87 indoor units** on 5 floors: KH00 (19 units), KH01 (20), KH02 (22), KH03 (22), KH95 (4).
- Coverage is **1 Jan to 31 Dec 2025** for every unit. All 12 months are present, so the Jan–Aug / Sep–Oct /
  Nov–Dec split works.
- Raw readings arrive every **3–6 min** (about 131k a year per unit). After bucketing there are about 101.7k
  5-min buckets per unit (97% of the year). Gaps are short: 98% of consecutive buckets are adjacent, and the
  longest gap is about 1 h.
- The cleaned file carries **interpolation residue**: status values like `1.39e-17` or `0.9998`, and
  fractional setpoints like `23.18`. The extractor rounds status to 0/1 and setpoints to 0.5 C.

## Signals (columns of SR-AC.csv)
| Column | Values | Verdict |
|---|---|---|
| Room Temp | 0.1 C resolution. 99% of readings are 15–45 C. 42.6k zeros and about 170k readings above 45 C are dropped as glitches | **Primary series** |
| Temp Adjust (setpoint) | 16–32 C. Most common: 22, 24, 25, 26 C | **Used** (comfort band) |
| Start Stop Status | 0/1. On in 7.2% of readings | **Used** (run state) |
| Thermo Status | 0/1. Non-zero on only 11 of 87 units | Used when present ("thermo n/a" otherwise) |
| Compressor Status | 0/1, but **identical across groups of units**: it belongs to the shared outdoor unit (VRF) | Not per-room evidence; not used |
| Air Con Mode | 1 cool (97%), 3 fan, 5 dry | Used: fan or dry mode is not expected to cool |
| Alarm / Malfunction Code | 34k alarm readings. Codes 37 (34k), 154, 146, 109, 118, 152 | Used (`unit_alarm`) |
| Indoor Fan Status | Mirrors on/off | Not needed |
| Elec Total Power, Gas Total Power | **All 0** | **No AC power or energy signal exists** |
| Forced Thermo OFF, Energy Efficiency, Heater | Constant 0 | Useless |

## How the units behave (5-min buckets)
- Only **21 of 87 units ever run**. **66 never run** all year (state always 0), but their room temperature is
  still logged.
- Units by on-share (train-month schedule profile): 18 office-hours units, 3 near-continuous ones (KH95-02 on
  89%, KH03-02 66%, KH03-14 67%), and 66 idle.
- Hour of day (IST, all units): on-share is 3.7% at 07:00 and peaks at 11.4% at 15:00. Floor level: Sunday on
  0.10, Saturday 0.35, Mon–Fri 0.41–0.46, so **Saturday is a working day** here.
- **Run lengths:** 9,117 runs. Median 25 buckets (about 2 h), p10 4 buckets (20 min). Runs of 1–2 buckets
  are 5.7% of all runs. Unit **KH02-02** has 246 of its 780 runs at 2 buckets or less: a genuine
  short-cycling unit.
- **Thermo cycles** while running (11 units): median 3 buckets (15 min). This is normal thermostat cycling.
- **Room minus setpoint after at least 30 min running:** p25 −1.0, p50 +0.1, p75 +1.2 C. Healthy units sit at
  about −1.6 to +1.3 C (p10–p90).
- **Pull-down in the first 30 min after a start:** median −3.2 C/h, p25 −5.2, p75 −0.7.
- **5-min noise:** median |step| is 0.0–0.1 C on most units. KH95-02 is noisy (median 0.4, p95 1.5).
- Idle rooms sit **exactly flat for 1–2 h** at a time, because of the 0.1 C resolution and slow change.

## Data quirks that shape the labels
1. **Hot thermistors.** KH01-04, KH01-10 and KH02-10 read **39–45 C while cooling** (median 41–43). That is
   a sensor placement or bias problem, not a room temperature. Idle units also read 34–45 C in still air: the
   thermistor sits in the ceiling unit, not the room. So an AC-off room is **never** labelled too hot unless
   occupancy says it is occupied.
2. **Steps with the unit off.** 2–6 C drops within 5 min with the state at 0 occur in about 2.6% of windows,
   mostly on never-run units. The likely cause is a change in airflow over the thermistor. They are not
   labelled bias faults (`is_ambiguous_real()` flags them so they are not used as "stable" examples).
3. **KH01-15** has malfunction code 37 for 26,858 buckets and reads about 15 C. This is a real faulty unit
   (`unit_alarm` / sensor examples).
4. **Setpoints change while units are off.** Never-run units log hundreds of setpoint changes a year, so a
   setpoint edit is not evidence that someone tried to start the unit.
5. **No room-level occupancy pairing.** P(occupied | AC on) is 0.09–0.22 against 0.05–0.11 when off, for every
   unit/sensor pair: only a time-of-day effect. The occupancy sensors (7, mostly vacant, 0–11% occupied) are not
   mapped to AC rooms. "Running in an empty room" can only be trained by attaching a real vacant sequence to a
   running window (synthetic pairing).

## Is the data good enough?
**Yes, for a per-unit agent:** it has room temperature, setpoint, run state, mode, alarms and (on 11 units)
thermo, for 12 months. Running windows are the scarce part: about 1.1k clean 4 h "on" bases at stride 96,
against 54k "off" bases. The generator can use stride 1–6 to get more.
**Not available:** AC power or energy, supply-air temperature, compressor state per unit, room occupancy. So
"running without cooling" is inferred only from the room temperature response, and "empty room" is synthetic.

## User decisions applied (2026-10-17)
| # | Decision | In hvac.py |
|---|---|---|
| D1 | Per-unit agent from the SR-AC.csv re-extraction; floor aggregate stays app CPU context | as built |
| D6 | fault_kind gains `quantised` | new pattern `quantised` (>= 1 h of whole-degree readings, >= 2 levels, >= 3 changes); 0 hits on real windows |
| D7 | calibration_drift tightened | >= 150 min (was 90), r2 >= 0.85 (was 0.7), >= 0.8 C/h, >= 2 C drop; real 4 h hits 330 -> 52 (0.07%); needs N >= 32 (`MIN_LEN`) |
| D9 | running_empty_room flagged with a switch-off recommendation | status warning, action **`switch_off_ac`** (new value, human approval; `NEW_ACTIONS`), "AC running in an empty room - recommend switching it off"; needs an occupancy feed, else "occupancy n/a" and it cannot fire |
| D10 | Same series format as other roles | ROOM TEMP and AC STATE as 10-min values, N/2 each, any N 24..144 step 6 |
| D11 | Faulty units = real fault examples only | ctx["faulty"]; never a base; `make_case`/`real_fault_case` keep a faulty unit's window only if the rules label it a fault/alarm. New pattern `biased_reading` (bias): >= 36 C after >= 1 h of cooling. Real yield (stride 96, 4 lengths): unit_alarm 1090, biased_reading 929, flatline 182, bias_jump 100, erratic 49; 9415 windows unused |
| D12 | Dense "unit on" sampling | `hvac_windows(..., on_stride=)` and `window_ends(unit, months, n, stride_off=12, stride_on=2)`; train months, 4 h: 257,639 running vs 427,900 off ends |

Real 4 h label rates after the changes (non-faulty, non-ambiguous units, 73,036 windows): normal 98.45%,
warning 0.83%, critical 0.08%, sensor_fault 0.64%.
