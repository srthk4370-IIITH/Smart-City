# HVAC data + role check (2026-10-16)
Aggregates only (no raw values). Private data stayed on the laptop.
- source_column_aggregates.json: value counts/histograms of every SR-AC.csv column (prof_srac.py)
- unit_profile_aggregates.json: per-unit 5-min aggregates (prof_units.py over data/series/hvac_units)
- real_label_check.txt: hvac.py rules on real windows (4/8/12 h), injection success per pattern, evidence/number checks (realcheck.py)
- test_output.txt: training/v2/test_hvac.py
