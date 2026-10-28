"""RW6 held-out test: tonight's 6 sensor stories (2026-10-25_mixA50_realworld/sim.py) rebuilt as v3 reasoner prompts.
Series follow sim.py (same formulas, seed 7, one story step = one 5-min point, padded with the pre-story level);
agent findings keep the live model's pattern/status/cause and wording from sim_results.json, with numbers taken
from the rebuilt evidence. Gold is written by hand from the story truth. -> data/rw6.jsonl"""
import datetime as dt
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import families as F  # noqa: E402
import lib as L  # noqa: E402
import textbank as T  # noqa: E402
from prompts import SYSTEM_INCIDENT  # noqa: E402

random.seed(7)
G = random.gauss
END = dt.datetime(2026, 10, 22, 14, 35, tzinfo=L.IST)   # a Thursday afternoon (owner: hot afternoon, workday)


def pad(story, n=48):
    return [story[0]] * (n - len(story)) + story


def mk(fam):
    return F.Case(random.Random(1), fam, END, "heldout")


def story_series():
    s = {}
    s["class"] = [(450 + 70 * i + G(0, 15), 25 + 0.12 * i + G(0, .1), 3 + 0.25 * i + G(0, .1)) for i in range(1, 15)]
    s["leak"] = [(300 - 6 * i + G(0, 1.5), 5 + G(0, .3)) for i in range(1, 15)]
    s["dust"] = [(25 + 11 * i + G(0, 4), 45 + 25 * i + G(0, 8), 3 + 0.9 * i + G(0, .5)) for i in range(1, 13)]
    s["ph"] = [(7.2 - 0.17 * i + G(0, .03), 150 + 4 * i + G(0, 3)) for i in range(1, 11)]
    s["ac"] = [(25.3 + 0.35 * i + G(0, .1), 34 + G(0, .3)) for i in range(1, 15)]
    s["glitch"] = [2900 if i % 2 else 230 for i in range(1, 7)]
    return s


def build():
    S = story_series()
    items = []
    # 1 class fills up
    c = mk("rw6_class_fills_up")
    co2 = pad([round(x[0]) for x in S["class"]])
    pw = pad([round(x[2], 2) for x in S["class"]])
    s1 = c.add("air_quality", "co2", "SR-AQ-KH03-03", "KH building, level 03, indoor air sensor 03", co2, hist=True,
               agent=lambda s: F.ag("gradual_increase", "warning", "ventilation_insufficient", 0.80,
                                    ["CO2 climbing at %s ppm/h, now %s ppm [E4,E1]" % (T.parse(s)["slope"], T.parse(s)["last"]),
                                     "%s ppm exceeds the warning limit of 1000 ppm [E1]" % T.parse(s)["last"]]))
    s2 = c.add("power", "power_kw", "SR-EM-KH04-01", "KH building, level 04, room energy meter 01", pw, True,
               agent=lambda s: F.ag("gradual_increase", "warning", "gradual_load_growth", 0.75,
                                    ["Power climbing at %s kW/h, now %s kW [E4,E1]" % (T.parse(s)["slope"], T.parse(s)["last"])]))
    s3 = c.add("occupancy", "occ", "SR-OC-GW-KH95-01", "KH building, room occupancy sensor 01 (gateway KH95)", [0] * 34 + [1] * 14, False,
               "occupancy of the same area", agent=F.ag("arrival", "normal", "arrival", 0.9, ["Room becoming occupied [E4]"]))
    items.append((c, {"labels": {"occupancy_driven_load": 1.0, "ventilation_issue": 0.5}, "severities": {"warning": 1.0},
                      "root_metric": "co2", "required": [["inspect_ventilation"]], "forbidden": ["replace_sensor", "recalibrate_sensor", "none"],
                      "checks": [], "suspects": []}))
    # 2 slow tank leak
    c = mk("rw6_slow_tank_leak")
    lv = pad([round(x[0], 1) for x in S["leak"]])
    fl = pad([round(x[1], 2) for x in S["leak"]])
    s1 = c.add("water", "level", "WM-WL-KH98-00", "KH building, level 98, water tank level sensor 00", lv, hist=True,
               head=["TANK: high level above 186.5, overflow risk above 225.0; usual fill up to 90 min"],
               agent=lambda s: F.ag("gradual_decrease", "normal", "tank_draining", 0.70,
                                    ["Tank level keeps falling, %s level/h with r2 %s [E4]" % (T.parse(s)["slope"], T.parse(s)["r2"]),
                                     "Level %s level is past the high mark of 186.5; overflow risk [E2]" % T.parse(s)["max"]]))
    c.add("water", "flow", "WM-WF-KH98-40", "KH building, level 98, water flow meter 40", fl, False, "outflow to the building from the same tank",
          agent=lambda s: F.ag("stable", "normal", "normal_usage", 0.85, ["Flow steady around %s m3/h [E1,E4]" % T.parse(s)["last"]]))
    c.add("occupancy", "occ", "SR-OC-GW-KH95-01", "KH building, room occupancy sensor 01 (gateway KH95)", [0] * 48, False, "occupancy of the building",
          agent=F.ag("vacant", "normal", "vacant", 0.9, ["No presence detected [E2]"]))
    items.append((c, {"labels": {"water_leak_or_overuse": 1.0, "water_supply_issue": 0.3}, "severities": {"warning": 1.0, "critical": 0.5},
                      "root_metric": "level", "required": [["inspect_water_system"]], "forbidden": ["replace_sensor", "none"],
                      "checks": [["S1", ["corrected", "contradicted", "stale"]]], "suspects": []}))
    # 3 dust storm
    c = mk("rw6_dust_storm_ingress")
    pm25 = pad([round(x[0], 1) for x in S["dust"]])
    pm10 = pad([round(x[1], 1) for x in S["dust"]])
    wind = pad([round(x[2], 2) for x in S["dust"]])
    c.add("weather", "wind", "WE-VN04-00", "VN building, level 04, rooftop weather station", wind, True,
          agent=lambda s: F.ag("gradual_increase", "warning", "weather_front", 0.80,
                               ["Wind speed keeps rising, %s m/s/h with r2 %s [E4]" % (T.parse(s)["slope"], T.parse(s)["r2"]),
                                "Crossed the warning limit of 10 m/s: %s m/s [E1]" % T.parse(s)["last"]]))
    c.add("air_quality", "pm25", "AQ-KN00-00", "KN building, outdoor air station", pm25, True,
          agent=lambda s: F.ag("gradual_increase", "critical", "outdoor_pollution_ingress", 0.85,
                               ["PM2.5 climbing at %s ug/m3/h, now %s ug/m3 [E4,E1]" % (T.parse(s)["slope"], T.parse(s)["last"]),
                                "%s ug/m3 exceeds the critical limit of 120 ug/m3 [E1]" % T.parse(s)["last"]]))
    c.add("air_quality", "pm10", "AQ-KN00-00", "KN building, outdoor air station", pm10, True,
          agent=lambda s: F.ag("gradual_increase", "critical", "outdoor_pollution_ingress", 0.85,
                               ["PM10 climbing at %s ug/m3/h, now %s ug/m3 [E4,E1]" % (T.parse(s)["slope"], T.parse(s)["last"]),
                                "critical level: %s ug/m3 against a limit of 250 ug/m3 [E1]" % T.parse(s)["last"]]))
    items.append((c, {"labels": {"air_pollution_event": 1.0, "weather_driven": 0.5}, "severities": {"critical": 1.0},
                      "root_metric": "pm25|pm10", "required": [["inspect_ventilation", "request_facility_review"]], "forbidden": ["none"],
                      "checks": [], "suspects": []}))
    # 4 acidic water
    c = mk("rw6_acidic_water")
    ph = pad([round(x[0], 2) for x in S["ph"]])
    tds = pad([round(x[1]) for x in S["ph"]])
    c.add("water", "ph", "WM-WD-KH98-00", "KH building, level 98, water quality sensor 00", ph, hist=True,
          agent=lambda s: F.ag("gradual_decrease", "warning", "water_quality_issue", 0.70,
                               ["Gradual decline of %s pH/h; last %s pH [E4,E1]" % (T.parse(s)["slope"], T.parse(s)["last"]),
                                "Normal daily range for this sensor [E4]"]))
    c.add("water", "tds", "WM-WD-KH98-00", "KH building, level 98, water quality sensor 00", tds, False, "same water quality sensor",
          agent=lambda s: F.ag("gradual_increase", "normal", "normal_usage", 0.75, ["TDS rising at %s ppm/h [E4]" % T.parse(s)["slope"]]))
    last = ph[-1]
    sv = {"critical": 1.0, "warning": 0.5} if last < 6.0 else ({"warning": 1.0, "critical": 0.5} if last < 6.5 else {"warning": 1.0})
    items.append((c, {"labels": {"water_quality_issue": 1.0}, "severities": sv, "root_metric": "ph",
                      "required": [["request_facility_review", "inspect_water_system"]], "forbidden": ["none", "replace_sensor"],
                      "checks": [["S1", ["contradicted", "corrected", "unsupported"]]], "suspects": []}))
    # 5 AC fails on a hot day
    c = mk("rw6_ac_fails_hot_day")
    rt = pad([round(x[0], 1) for x in S["ac"]])
    wt = pad([round(x[1], 1) for x in S["ac"]])
    c.extra["outdoor"] = (L.fmt(wt[-1], 1), L.WEATHER[0], L.tstr(END))
    c.add("hvac", "room_temp", "SR-AC-KH02-24", "KH building, level 02, AC indoor unit 24", rt, True, ac=[1] * 48, setp=26.0, hist=True,
          agent=F.ag("stuck_on", "warning", "schedule_or_control_fault", 0.70,
                     ["Unit kept running at night/weekend though room is at setpoint 26.0 C [E5,E8]", "48 of 48 samples on, wasting energy [E5]"]))
    c.add("weather", "temp", L.WEATHER[0], L.WEATHER[1], wt, False, "outdoor conditions",
          agent=lambda s: F.ag("stable", "normal", "normal_weather", 0.85, ["Outdoor temperature steady around %s C [E1,E4]" % T.parse(s)["last"]]))
    items.append((c, {"labels": {"hvac_or_thermal_issue": 1.0}, "severities": {"warning": 1.0, "critical": 0.5}, "root_metric": "room_temp",
                      "required": [["inspect_hvac"]], "forbidden": ["none", "replace_sensor"],
                      "checks": [["S1", ["contradicted", "corrected"]]], "suspects": []}))
    # 6 CO2 sensor glitch
    c = mk("rw6_co2_sensor_glitch")
    co2 = [450] * 42 + S["glitch"]
    co2 = [round(v + (G(0, 8) if i < 42 else 0)) for i, v in enumerate(co2)]
    c.add("air_quality", "co2", "SR-AQ-KH03-03", "KH building, level 03, indoor air sensor 03", co2, True,
          agent=lambda s: F.ag("step_decrease", "sensor_fault", "sensor_fault", 0.80,
                               ["Level down from 450 to %s ppm, step at %s [E7,E5]" % (T.parse(s)["max"], T.parse(s)["jump_t"]),
                                "The new level appeared instantly at %s [E5,E8]" % T.parse(s)["jump_t"]]))
    c.add("occupancy", "occ", "SR-OC-GW-KH95-01", "KH building, room occupancy sensor 01 (gateway KH95)", [0] * 48, False, "occupancy of the same room",
          agent=F.ag("vacant", "normal", "vacant", 0.9, ["No presence detected [E2]"]))
    items.append((c, {"labels": {"sensor_fault": 1.0}, "severities": {"sensor_fault": 1.0}, "root_metric": "co2",
                      "required": [["check_sensor", "restart_or_reconnect_sensor", "recalibrate_sensor", "replace_sensor"]],
                      "forbidden": ["inspect_ventilation"], "checks": [["S1", ["corrected", "contradicted", "unsupported"]]], "suspects": ["S1"]}))
    rows = []
    for c, gold in items:
        case = {"end": END, "outdoor": c.extra.get("outdoor"), "inc_id": "INC-%04d" % (257 + len(rows)), "mode": "early", "win_h": "4",
                "sensors": c.sensors, "memory": [], "ask": "Write the cross-domain incident report JSON."}
        rows.append({"id": c.fam, "family": c.fam, "split": "rw6", "tools": "incident",
                     "messages": [{"role": "system", "content": SYSTEM_INCIDENT}, {"role": "user", "content": L.render(case)}], "gold": gold})
    with open(os.path.join(HERE, "..", "data", "rw6.jsonl"), "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("rw6", len(rows))


if __name__ == "__main__":
    build()
