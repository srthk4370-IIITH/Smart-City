"""Shared constants for the P0 host reasoner/chat benchmark (2026-10-22).

Everything here is local: the store is built from proofs/ incident JSONs plus a seeded synthetic year.
"""
import datetime as dt
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
PROOFS = os.path.join(REPO, "proofs")
STORE = os.path.join(HERE, "data", "store.sqlite")

# Device clock for every relative time preset ("this year", "last month" ...). IST, naive.
NOW = dt.datetime(2026, 10, 22, 12, 0, 0)
YEAR_START = dt.datetime(2026, 1, 1)
READINGS_FROM = dt.datetime(2026, 8, 23)   # hourly rollups kept on the device from this date (60 days)
FIVEMIN_FROM = dt.datetime(2026, 10, 19)   # raw 5-min readings for the last ~3 days

REPORT_LABELS = ["ventilation_issue", "hvac_or_thermal_issue", "occupancy_driven_load", "air_pollution_event",
                 "water_leak_or_overuse", "water_supply_issue", "water_quality_issue", "power_load_anomaly",
                 "power_quality_issue", "weather_driven", "sensor_fault", "normal_operation", "unknown"]
# backend features.go Actions + the three sensor steps proposed in APPROVAL_AND_MEMORY.md 3.2
ACTIONS = ["none", "monitor", "inspect_ventilation", "inspect_hvac", "check_sensor", "inspect_water_system",
           "inspect_electrical", "review_schedule", "request_facility_review", "replace_sensor",
           "recalibrate_sensor", "restart_or_reconnect_sensor"]
SENSOR_ACTIONS = {"check_sensor", "replace_sensor", "recalibrate_sensor", "restart_or_reconnect_sensor"}
SEVERITIES = ["critical", "warning", "normal", "sensor_fault"]
FAULT_KINDS = ["stuck", "bias", "drift", "noise", "dropout", "saturation", "quantised"]
DOMAINS = ["air_quality", "water", "power", "occupancy", "weather", "hvac"]

# "spike" synonym table owned by the executor (REASONER_DESIGN A.6); agent pattern enum names
PATTERN_SYNONYMS = {
    "spike": ["spike", "exponential_increase", "step_increase"],
    "exp_rise": ["exponential_increase"],
    "flatline": ["flatline"],
    "drift": ["gradual_increase", "gradual_decrease"],
    "dip": ["dip", "step_decrease"],
}

# Sensor catalogue: the 13 real series seen in the app tests plus the same kinds of sensors in other buildings.
# (node, metric, domain, location, unit)
CATALOG = [
    ("SR-AQ-KH03-03", "co2", "air_quality", "KH building, level 03, indoor air sensor 03", "ppm"),
    ("SR-AQ-KH03-03", "temp", "air_quality", "KH building, level 03, indoor air sensor 03", "C"),
    ("SR-AQ-KH03-03", "rh", "air_quality", "KH building, level 03, indoor air sensor 03", "%"),
    ("SR-AQ-KH03-01", "co2", "air_quality", "KH building, level 03, indoor air sensor 01", "ppm"),
    ("SR-AQ-KH03-01", "pm25", "air_quality", "KH building, level 03, indoor air sensor 01", "ug/m3"),
    ("SR-AQ-VN02-01", "co2", "air_quality", "VN building, level 02, indoor air sensor 01", "ppm"),
    ("SR-AQ-VN02-01", "temp", "air_quality", "VN building, level 02, indoor air sensor 01", "C"),
    ("SR-AQ-BK01-02", "co2", "air_quality", "BK building, level 01, indoor air sensor 02", "ppm"),
    ("SR-AQ-BK01-02", "pm25", "air_quality", "BK building, level 01, indoor air sensor 02", "ug/m3"),
    ("AQ-KN00-00", "pm25", "air_quality", "KN building, outdoor air station", "ug/m3"),
    ("AQ-KN00-00", "pm10", "air_quality", "KN building, outdoor air station", "ug/m3"),
    ("WM-WL-KH98-00", "level", "water", "KH building, level 98, water tank level sensor 00", "%"),
    ("WM-WF-KH98-40", "flow", "water", "KH building, level 98, water flow meter 40", "m3/h"),
    ("WM-WL-VN98-00", "level", "water", "VN building, level 98, water tank level sensor 00", "%"),
    ("WM-WF-VN98-10", "flow", "water", "VN building, level 98, water flow meter 10", "m3/h"),
    ("WM-WQ-KH98-01", "tds", "water", "KH building, level 98, water quality probe 01", "ppm"),
    ("WM-WQ-KH98-01", "ph", "water", "KH building, level 98, water quality probe 01", "pH"),
    ("SR-EM-KH04-01", "power_kw", "power", "KH building, level 04, room energy meter 01", "kW"),
    ("SR-EM-VN01-02", "power_kw", "power", "VN building, level 01, room energy meter 02", "kW"),
    ("SR-EM-VN01-02", "pf", "power", "VN building, level 01, room energy meter 02", ""),
    ("EM-CR-SB00-00", "power_kw", "power", "SB00 substation, 11 kV feeder meter", "kW"),
    ("EM-CR-SB00-00", "pf", "power", "SB00 substation, 11 kV feeder meter", ""),
    ("SR-OC-GW-KH95-01", "occ", "occupancy", "KH building, room occupancy sensor 01 (gateway KH95)", "0/1"),
    ("SR-OC-GW-VN95-02", "occ", "occupancy", "VN building, room occupancy sensor 02 (gateway VN95)", "0/1"),
    ("SR-OC-GW-BK95-01", "occ", "occupancy", "BK building, room occupancy sensor 01 (gateway BK95)", "0/1"),
    ("WE-VN04-00", "temp", "weather", "VN building, level 04, rooftop weather station", "C"),
    ("WE-VN04-00", "rh", "weather", "VN building, level 04, rooftop weather station", "%"),
    ("WE-VN04-00", "wind", "weather", "VN building, level 04, rooftop weather station", "m/s"),
    ("AC-KH03", "ac_units_on", "hvac", "KH building, level 03, AC units", "units"),
    ("AC-KH03", "room_temp", "hvac", "KH building, level 03, AC units", "C"),
    ("AC-VN02", "ac_units_on", "hvac", "VN building, level 02, AC units", "units"),
    ("AC-VN02", "room_temp", "hvac", "VN building, level 02, AC units", "C"),
]
CAT = {(n, m): (d, loc, u) for n, m, d, loc, u in CATALOG}


def building_of(node):
    """KH03 -> KH (segments like KH03, VN98, SB00)."""
    for seg in node.split("-"):
        if len(seg) == 4 and seg[:2] in ("KH", "VN", "BK", "KN", "SB") and seg[2:].isdigit():
            return seg[:2]
    return "?"
