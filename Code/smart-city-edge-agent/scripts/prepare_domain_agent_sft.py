"""Generate SFT training datasets for all 5 domain agents.

This script creates supervised fine-tuning (SFT) data for each of the 5 domain agents:
  - energy: Power consumption, HVAC loads, grid events
  - air_quality: CO2, PM2.5, ventilation, indoor climate
  - water: Flow, pressure, quality, leaks, demand
  - weather: Outdoor temp, wind, humidity, heat stress
  - occupancy: People count, room state, network density

Each agent learns to:
  1. Receive a structured JSON evidence window for its domain
  2. Return a structured DomainAnalysis JSON (hypothesis, evidence, confidence, uncertainty, recommendation)
  3. NEVER claim a root cause or control equipment
  4. Always cite only provided evidence IDs

Usage (WSL):
  source .venv/bin/activate
  python3 scripts/prepare_domain_agent_sft.py --output data/processed/sft/

Generates:
  data/processed/sft/agent_energy.jsonl
  data/processed/sft/agent_air_quality.jsonl
  data/processed/sft/agent_water.jsonl
  data/processed/sft/agent_weather.jsonl
  data/processed/sft/agent_occupancy.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

random.seed(42)

# ─────────────────────────────────────────────────────────
# SYSTEM PROMPTS per agent
# ─────────────────────────────────────────────────────────
AGENT_SYSTEMS = {
    "energy": (
        "You are the Energy Domain Agent for a Smart City Monitoring System at IIIT Hyderabad campus. "
        "You receive sensor readings from energy meters and HVAC systems. "
        "Return ONLY valid JSON matching the DomainAnalysis schema. "
        "Cite ONLY the evidence_ids provided. Do NOT identify a root cause. "
        "Do NOT recommend shutting down, overriding, or directly controlling any equipment. "
        "State your uncertainty honestly."
    ),
    "air_quality": (
        "You are the Air Quality Domain Agent for a Smart City Monitoring System at IIIT Hyderabad campus. "
        "You receive indoor and outdoor air quality sensor readings (PM2.5, CO2, temperature, humidity). "
        "Return ONLY valid JSON matching the DomainAnalysis schema. "
        "Cite ONLY the evidence_ids provided. Do NOT identify a root cause. "
        "Do NOT recommend shutting down or directly controlling any equipment. "
        "State your uncertainty honestly."
    ),
    "water": (
        "You are the Water Infrastructure Domain Agent for a Smart City Monitoring System at IIIT Hyderabad campus. "
        "You receive water flow, pressure, quality, and tank level sensor readings. "
        "Return ONLY valid JSON matching the DomainAnalysis schema. "
        "Cite ONLY the evidence_ids provided. Do NOT identify a root cause. "
        "Do NOT recommend shutting off water supply without human authorization. "
        "State your uncertainty honestly."
    ),
    "weather": (
        "You are the Weather & Microclimate Domain Agent for a Smart City Monitoring System at IIIT Hyderabad campus. "
        "You receive outdoor weather station data (temperature, humidity, wind speed/direction, solar radiation). "
        "Return ONLY valid JSON matching the DomainAnalysis schema. "
        "Cite ONLY the evidence_ids provided. Do NOT identify a root cause. "
        "Focus on how weather conditions may be affecting or correlated with indoor infrastructure events. "
        "State your uncertainty honestly."
    ),
    "occupancy": (
        "You are the Occupancy & Mobility Domain Agent for a Smart City Monitoring System at IIIT Hyderabad campus. "
        "You receive people count, room state, and network node density data. "
        "Return ONLY valid JSON matching the DomainAnalysis schema. "
        "Cite ONLY the evidence_ids provided. Do NOT identify a root cause. "
        "Do NOT make recommendations that restrict people's movement or access without authorization. "
        "State your uncertainty honestly."
    ),
}

# ─────────────────────────────────────────────────────────
# SCENARIO LIBRARY — rich, diverse scenarios per domain
# ─────────────────────────────────────────────────────────
ENERGY_SCENARIOS = [
    {
        "event_id": "evt_energy_001",
        "building_id": "BH-01", "zone_id": "3A",
        "measurements": {
            "energy_kw": {"mean": 185.4, "max": 220.1, "min": 142.0, "trend": +8.2, "last_value": 219.8},
            "hvac_state_encoded": {"last_value": 2, "mean": 1.8},
            "indoor_temp_c": {"mean": 29.1, "max": 31.2, "min": 27.0, "last_value": 31.2},
        },
        "evidence_ids": ["ev_energy_kw_EM-BH01_t1001", "ev_hvac_state_BH01_t1001", "ev_indoor_temp_BH01_t1001"],
        "expected": {
            "domain": "energy",
            "hypothesis": "Energy consumption has risen 35% above the 60-minute mean, peaking at 220.1 kW. HVAC is in sustained cooling mode (encoded=2) while indoor temperature climbs to 31.2°C — suggesting the cooling system is working above rated capacity.",
            "evidence": ["ev_energy_kw_EM-BH01_t1001", "ev_hvac_state_BH01_t1001"],
            "confidence": 0.88,
            "uncertainty": "Cannot confirm whether the load increase originates from HVAC alone or if additional electrical loads (lighting, lab equipment) are active. Outdoor temperature data not included in this window.",
            "recommendation": "Request facility team to inspect HVAC compressor state and check whether non-essential electrical loads in Zone 3A are active."
        }
    },
    {
        "event_id": "evt_energy_002",
        "building_id": "LAB-02", "zone_id": "1B",
        "measurements": {
            "energy_kw": {"mean": 42.1, "max": 48.3, "min": 38.0, "trend": -0.5, "last_value": 41.2},
            "hvac_state_encoded": {"last_value": 0, "mean": 0.2},
            "indoor_temp_c": {"mean": 35.8, "max": 38.0, "min": 33.0, "last_value": 38.0},
        },
        "evidence_ids": ["ev_energy_kw_LAB02_t2001", "ev_hvac_state_LAB02_t2001", "ev_indoor_temp_LAB02_t2001"],
        "expected": {
            "domain": "energy",
            "hypothesis": "Energy consumption appears normal or slightly declining, yet indoor temperature has reached 38°C. HVAC is in OFF state (encoded=0), which is anomalous given the extreme heat. This may indicate an HVAC shutdown or fault rather than an energy overload event.",
            "evidence": ["ev_energy_kw_LAB02_t2001", "ev_hvac_state_LAB02_t2001", "ev_indoor_temp_LAB02_t2001"],
            "confidence": 0.79,
            "uncertainty": "HVAC shutdown could be scheduled maintenance, a trip fault, or a thermostat malfunction. Energy data alone cannot distinguish these cases.",
            "recommendation": "Request facilities team to physically inspect the HVAC unit in Lab 02 Zone 1B to determine if it is offline due to fault or scheduled maintenance."
        }
    },
    {
        "event_id": "evt_energy_003",
        "building_id": "ADMIN-01", "zone_id": "2F",
        "measurements": {
            "energy_kw": {"mean": 310.0, "max": 395.0, "min": 280.0, "trend": +22.0, "last_value": 395.0},
            "hvac_state_encoded": {"last_value": 2, "mean": 2.0},
            "indoor_temp_c": {"mean": 26.5, "max": 27.2, "min": 25.8, "last_value": 26.3},
            "ventilation_state_enc": {"last_value": 1, "mean": 0.9},
        },
        "evidence_ids": ["ev_energy_kw_ADMIN01_t3001", "ev_hvac_ADMIN01_t3001", "ev_temp_ADMIN01_t3001", "ev_vent_ADMIN01_t3001"],
        "expected": {
            "domain": "energy",
            "hypothesis": "Energy consumption is critically elevated at 395 kW with a strong upward trend (+22 kW/hr slope). HVAC is in continuous cooling with ventilation active. However, indoor temperature is normal at 26.3°C — suggesting the HVAC is operating correctly but drawing far more power than usual, possibly due to extreme outdoor heat load.",
            "evidence": ["ev_energy_kw_ADMIN01_t3001", "ev_hvac_ADMIN01_t3001", "ev_vent_ADMIN01_t3001"],
            "confidence": 0.83,
            "uncertainty": "The source of excess energy draw is unclear without outdoor weather data. The HVAC may be fighting high external thermal load. Building-level submetering would help isolate the source.",
            "recommendation": "Monitor consumption trend for the next 30 minutes. If it exceeds 420 kW, alert the facilities team to investigate external thermal load and check if all non-essential systems can be temporarily reduced."
        }
    },
    {
        "event_id": "evt_energy_004",
        "building_id": "HOST-03", "zone_id": "GF",
        "measurements": {
            "energy_kw": {"mean": 8.2, "max": 9.1, "min": 7.8, "trend": 0.0, "last_value": 8.4},
            "hvac_state_encoded": {"last_value": 1, "mean": 0.8},
            "indoor_temp_c": {"mean": 20.2, "max": 21.0, "min": 19.5, "last_value": 19.8},
        },
        "evidence_ids": ["ev_energy_kw_HOST03_t4001", "ev_hvac_HOST03_t4001"],
        "expected": {
            "domain": "energy",
            "hypothesis": "Energy consumption is well within normal operating range (8.4 kW, stable trend). HVAC is in heating mode with low indoor temperature — consistent with a cold night or early morning heating event. No anomalous energy pattern is present in this domain.",
            "evidence": ["ev_energy_kw_HOST03_t4001", "ev_hvac_HOST03_t4001"],
            "confidence": 0.92,
            "uncertainty": "Confident that energy is not anomalous. The heating demand is consistent with expected seasonal behavior.",
            "recommendation": "No action required from energy domain perspective. Monitor if heating load rises significantly above 10 kW."
        }
    },
]

AIR_QUALITY_SCENARIOS = [
    {
        "event_id": "evt_aq_001",
        "building_id": "BH-01", "zone_id": "3A",
        "measurements": {
            "indoor_pm25": {"mean": 88.5, "max": 145.0, "min": 22.0, "trend": +12.0, "last_value": 145.0},
            "indoor_co2": {"mean": 1480.0, "max": 1680.0, "min": 1100.0, "trend": +38.0, "last_value": 1680.0},
            "indoor_temp_c": {"mean": 29.5, "max": 31.0, "min": 28.0, "last_value": 31.0},
            "indoor_humidity": {"mean": 72.0, "max": 78.0, "min": 65.0, "last_value": 78.0},
            "ventilation_state_enc": {"last_value": 0, "mean": 0.1},
        },
        "evidence_ids": ["ev_aq_pm25_BH01_t1001", "ev_aq_co2_BH01_t1001", "ev_aq_temp_BH01_t1001", "ev_aq_vent_BH01_t1001"],
        "expected": {
            "domain": "air_quality",
            "hypothesis": "Indoor PM2.5 has surged to 145 µg/m³ (5.8× WHO 24h guideline of 25 µg/m³) with CO2 at 1680 ppm (above ASHRAE critical threshold of 1500 ppm). Ventilation appears to be OFF or near-OFF. The simultaneous rise of both PM2.5 and CO2 with ventilation inactive strongly suggests inadequate air exchange in Zone 3A.",
            "evidence": ["ev_aq_pm25_BH01_t1001", "ev_aq_co2_BH01_t1001", "ev_aq_vent_BH01_t1001"],
            "confidence": 0.91,
            "uncertainty": "Cannot determine whether PM2.5 source is internal (occupant activity, cooking, dust) or external infiltration without outdoor PM2.5 comparison. High humidity (78%) may also affect sensor readings.",
            "recommendation": "Request facilities team to inspect ventilation system in Zone 3A. Consider reducing occupancy until air quality improves."
        }
    },
    {
        "event_id": "evt_aq_002",
        "building_id": "LAB-04", "zone_id": "2C",
        "measurements": {
            "indoor_pm25": {"mean": 12.0, "max": 15.0, "min": 10.0, "trend": +0.5, "last_value": 14.2},
            "indoor_co2": {"mean": 850.0, "max": 920.0, "min": 800.0, "trend": +5.0, "last_value": 910.0},
            "indoor_temp_c": {"mean": 23.5, "max": 24.0, "min": 23.0, "last_value": 24.0},
            "ventilation_state_enc": {"last_value": 1, "mean": 1.0},
        },
        "evidence_ids": ["ev_aq_pm25_LAB04_t2001", "ev_aq_co2_LAB04_t2001"],
        "expected": {
            "domain": "air_quality",
            "hypothesis": "Air quality parameters are within normal ranges. PM2.5 at 14.2 µg/m³ is well below WHO guideline. CO2 at 910 ppm is below ASHRAE warning threshold of 1000 ppm. Ventilation is active and temperature is comfortable. No air quality anomaly is detected in this zone.",
            "evidence": ["ev_aq_pm25_LAB04_t2001", "ev_aq_co2_LAB04_t2001"],
            "confidence": 0.95,
            "uncertainty": "Parameters are currently normal but showing slight upward trends. If CO2 crosses 1000 ppm, further investigation would be warranted.",
            "recommendation": "No immediate action required. Continue monitoring CO2 trend — if it rises above 1000 ppm within the next 30 minutes, check occupancy levels."
        }
    },
    {
        "event_id": "evt_aq_003",
        "building_id": "ADMIN-01", "zone_id": "5A",
        "measurements": {
            "indoor_pm25": {"mean": 180.0, "max": 320.0, "min": 15.0, "trend": +45.0, "last_value": 320.0},
            "indoor_co2": {"mean": 520.0, "max": 560.0, "min": 490.0, "trend": +2.0, "last_value": 550.0},
            "indoor_temp_c": {"mean": 27.0, "max": 27.5, "min": 26.5, "last_value": 27.2},
            "ventilation_state_enc": {"last_value": 1, "mean": 1.0},
        },
        "evidence_ids": ["ev_aq_pm25_ADMIN01_t3001", "ev_aq_co2_ADMIN01_t3001", "ev_aq_vent_ADMIN01_t3001"],
        "expected": {
            "domain": "air_quality",
            "hypothesis": "PM2.5 has spiked dramatically to 320 µg/m³ — a hazardous level — while CO2 remains normal at 550 ppm. Ventilation is active. The combination of very high PM2.5 but normal CO2 with active ventilation suggests an external particulate source (e.g., outdoor construction, smoke, dust storm) is entering through the ventilation system, rather than an internal source.",
            "evidence": ["ev_aq_pm25_ADMIN01_t3001", "ev_aq_co2_ADMIN01_t3001", "ev_aq_vent_ADMIN01_t3001"],
            "confidence": 0.86,
            "uncertainty": "Cannot confirm external vs. internal PM2.5 source without outdoor air quality measurements. The ventilation system may be drawing in contaminated outdoor air.",
            "recommendation": "Request facilities team to check outdoor PM2.5 levels and consider temporarily switching ventilation to recirculation mode to prevent ingress of outdoor particulates."
        }
    },
]

WATER_SCENARIOS = [
    {
        "event_id": "evt_water_001",
        "building_id": "PALASH", "zone_id": "GF",
        "measurements": {
            "water_flow_lpm": {"mean": 340.0, "max": 420.0, "min": 12.0, "trend": +58.0, "last_value": 420.0},
            "water_pressure_kpa": {"mean": 185.0, "max": 320.0, "min": 45.0, "trend": -42.0, "last_value": 45.0},
            "water_level_m": {"mean": 3.2, "max": 3.8, "min": 2.8, "trend": -0.8, "last_value": 2.5},
        },
        "evidence_ids": ["ev_water_flow_WM-WF-PL00-70_t1001", "ev_water_pres_WM-WF-PL00-70_t1001", "ev_water_level_WM-WL-PL_t1001"],
        "expected": {
            "domain": "water",
            "hypothesis": "Flow rate has surged to 420 L/min while pressure has simultaneously dropped to 45 kPa (below the 150 kPa warning threshold), and tank level is declining at -0.8 m/hr. This pattern — high flow + dropping pressure + falling level — is consistent with an uncontrolled high-demand event or a pipe break downstream.",
            "evidence": ["ev_water_flow_WM-WF-PL00-70_t1001", "ev_water_pres_WM-WF-PL00-70_t1001", "ev_water_level_WM-WL-PL_t1001"],
            "confidence": 0.87,
            "uncertainty": "Cannot distinguish between a legitimate high-demand surge (e.g., scheduled irrigation or filling operations) and an actual pipe leak without isolating the circuit. Field inspection is required.",
            "recommendation": "Alert facilities team to inspect the water distribution network at Palash block for potential pipe breach or unintended high-flow events. Do not close supply valves without authorization."
        }
    },
    {
        "event_id": "evt_water_002",
        "building_id": "MAIN-BUILD", "zone_id": "B2",
        "measurements": {
            "water_flow_lpm": {"mean": 18.0, "max": 22.0, "min": 15.0, "trend": +0.3, "last_value": 19.5},
            "water_pressure_kpa": {"mean": 285.0, "max": 310.0, "min": 260.0, "trend": -1.0, "last_value": 275.0},
            "water_turbidity_ntu": {"mean": 0.4, "max": 0.6, "min": 0.3, "trend": +0.05, "last_value": 0.6},
        },
        "evidence_ids": ["ev_water_flow_MB_t2001", "ev_water_turb_MB_t2001"],
        "expected": {
            "domain": "water",
            "hypothesis": "Flow and pressure are within normal operating ranges. Water turbidity at 0.6 NTU remains below the WHO warning threshold of 1.0 NTU. No water infrastructure anomaly detected. Slight turbidity increase may warrant monitoring but does not indicate a current problem.",
            "evidence": ["ev_water_flow_MB_t2001", "ev_water_turb_MB_t2001"],
            "confidence": 0.93,
            "uncertainty": "Turbidity trend is slightly upward. If it continues to rise above 1.0 NTU, this could indicate pipe disturbance, construction nearby, or water quality degradation.",
            "recommendation": "No immediate action. Monitor turbidity trend over the next hour."
        }
    },
    {
        "event_id": "evt_water_003",
        "building_id": "HOSTEL-A", "zone_id": "RF",
        "measurements": {
            "water_flow_lpm": {"mean": 2.1, "max": 3.0, "min": 1.8, "trend": +0.1, "last_value": 2.5},
            "water_pressure_kpa": {"mean": 82.0, "max": 95.0, "min": 60.0, "trend": -15.0, "last_value": 60.0},
            "water_level_m": {"mean": 1.2, "max": 1.4, "min": 0.9, "trend": -0.3, "last_value": 0.9},
            "water_turbidity_ntu": {"mean": 3.8, "max": 4.5, "min": 3.0, "trend": +0.8, "last_value": 4.5},
        },
        "evidence_ids": ["ev_water_pres_HA_RF_t3001", "ev_water_level_HA_RF_t3001", "ev_water_turb_HA_RF_t3001"],
        "expected": {
            "domain": "water",
            "hypothesis": "Multiple simultaneous anomalies: tank level critically low at 0.9 m with declining trend (-0.3 m/hr), pressure dropped to 60 kPa (below warning threshold), and turbidity at 4.5 NTU exceeds the WHO critical threshold of 4.0 NTU. The high turbidity combined with low level suggests the tank may be nearly empty and drawing sediment from the tank bottom.",
            "evidence": ["ev_water_pres_HA_RF_t3001", "ev_water_level_HA_RF_t3001", "ev_water_turb_HA_RF_t3001"],
            "confidence": 0.90,
            "uncertainty": "Cannot confirm whether supply has failed (upstream issue) or consumption is unusually high. Turbidity source (sediment vs. contamination) requires laboratory confirmation.",
            "recommendation": "Alert facilities team urgently that rooftop tank in Hostel A is critically low and turbidity exceeds safe limits. Request inspection of supply fill valve and consider informing residents."
        }
    },
]

WEATHER_SCENARIOS = [
    {
        "event_id": "evt_weather_001",
        "building_id": "CAMPUS", "zone_id": "OUTDOOR",
        "measurements": {
            "outdoor_temp_c": {"mean": 41.2, "max": 43.5, "min": 38.0, "trend": +1.8, "last_value": 43.5},
            "outdoor_humidity": {"mean": 15.0, "max": 18.0, "min": 12.0, "trend": -0.5, "last_value": 13.0},
            "wind_mps": {"mean": 1.2, "max": 2.1, "min": 0.5, "trend": -0.2, "last_value": 0.8},
        },
        "evidence_ids": ["ev_weather_temp_WE_t1001", "ev_weather_hum_WE_t1001", "ev_weather_wind_WE_t1001"],
        "expected": {
            "domain": "weather",
            "hypothesis": "Outdoor temperature has reached 43.5°C — exceeding the campus critical heat stress threshold of 42°C — with near-zero wind speed (0.8 m/s) and extremely low humidity (13%). This combination creates maximum thermal stress conditions: minimal evaporative cooling, no wind-assisted cooling, and a rising temperature trend (+1.8°C/hr) indicating worsening conditions.",
            "evidence": ["ev_weather_temp_WE_t1001", "ev_weather_hum_WE_t1001", "ev_weather_wind_WE_t1001"],
            "confidence": 0.95,
            "uncertainty": "Weather forecast data not available. Cannot predict whether peak temperature has been reached or will continue rising.",
            "recommendation": "This extreme outdoor thermal condition is expected to impose heavy HVAC loads on all campus buildings and elevate heat stress risk for outdoor occupants. Notify facilities and campus management."
        }
    },
    {
        "event_id": "evt_weather_002",
        "building_id": "CAMPUS", "zone_id": "OUTDOOR",
        "measurements": {
            "outdoor_temp_c": {"mean": 27.8, "max": 29.0, "min": 26.5, "trend": +0.2, "last_value": 28.5},
            "outdoor_humidity": {"mean": 72.0, "max": 80.0, "min": 65.0, "trend": +3.0, "last_value": 80.0},
            "wind_mps": {"mean": 8.5, "max": 12.3, "min": 5.0, "trend": +1.5, "last_value": 12.0},
        },
        "evidence_ids": ["ev_weather_temp_WE_t2001", "ev_weather_hum_WE_t2001", "ev_weather_wind_WE_t2001"],
        "expected": {
            "domain": "weather",
            "hypothesis": "Outdoor conditions show moderate temperature (28.5°C) within normal campus operations range. However, humidity is elevated at 80% with a rising trend, and wind speed is high at 12 m/s (gusting). The high humidity combined with strong wind may be precursors to a rain event. This may impact outdoor structures and increase infiltration of humid air into buildings with open ventilation.",
            "evidence": ["ev_weather_temp_WE_t2001", "ev_weather_hum_WE_t2001", "ev_weather_wind_WE_t2001"],
            "confidence": 0.82,
            "uncertainty": "Cannot confirm imminent rain without barometric pressure data. Wind direction not available — unknown if humid air is campus-local or regional.",
            "recommendation": "Monitor weather trends. If humidity rises above 85% with continued strong wind, consider alerting facilities to close outdoor-vented areas to prevent moisture infiltration."
        }
    },
    {
        "event_id": "evt_weather_003",
        "building_id": "CAMPUS", "zone_id": "OUTDOOR",
        "measurements": {
            "outdoor_temp_c": {"mean": 22.0, "max": 23.0, "min": 21.0, "trend": 0.0, "last_value": 22.5},
            "outdoor_humidity": {"mean": 55.0, "max": 58.0, "min": 52.0, "trend": 0.0, "last_value": 55.0},
            "wind_mps": {"mean": 3.5, "max": 4.2, "min": 2.8, "trend": 0.0, "last_value": 3.6},
        },
        "evidence_ids": ["ev_weather_temp_WE_t3001", "ev_weather_hum_WE_t3001"],
        "expected": {
            "domain": "weather",
            "hypothesis": "Outdoor weather conditions are ideal — temperature 22.5°C, humidity 55%, gentle breeze 3.6 m/s. All parameters are stable with no trends. Weather conditions are not contributing to any campus infrastructure stress.",
            "evidence": ["ev_weather_temp_WE_t3001", "ev_weather_hum_WE_t3001"],
            "confidence": 0.98,
            "uncertainty": "Conditions are clearly benign. No uncertainty in this assessment.",
            "recommendation": "No action required from weather domain perspective. This is an optimal day for natural ventilation — campus facilities may benefit from opening windows to reduce HVAC load."
        }
    },
]

OCCUPANCY_SCENARIOS = [
    {
        "event_id": "evt_occ_001",
        "building_id": "BH-01", "zone_id": "3A",
        "measurements": {
            "occupancy_count": {"mean": 105.0, "max": 128.0, "min": 85.0, "trend": +8.0, "last_value": 128.0},
            "network_node_density": {"mean": 95.0, "max": 112.0, "min": 78.0, "trend": +7.0, "last_value": 112.0},
        },
        "evidence_ids": ["ev_occ_count_BH01_3A_t1001", "ev_occ_net_BH01_3A_t1001"],
        "expected": {
            "domain": "occupancy",
            "hypothesis": "Zone 3A occupancy has reached 128 persons — exceeding the critical threshold of 100 and the rated HVAC design capacity of 80. Network node density of 112 devices (corroborating the headcount) confirms high occupancy is real, not a sensor artifact. The rising trend (+8 persons/hr) suggests the zone is still filling.",
            "evidence": ["ev_occ_count_BH01_3A_t1001", "ev_occ_net_BH01_3A_t1001"],
            "confidence": 0.93,
            "uncertainty": "Occupancy sensor may have a ±5% accuracy margin. Network device count includes devices left unattended — may slightly overcount actual active occupants.",
            "recommendation": "Alert zone supervisor that occupancy has exceeded rated capacity. Recommend diverting new arrivals to adjacent zones. Do not forcibly restrict movement without proper authorization."
        }
    },
    {
        "event_id": "evt_occ_002",
        "building_id": "MAIN-BUILD", "zone_id": "LOBBY",
        "measurements": {
            "occupancy_count": {"mean": 12.0, "max": 18.0, "min": 5.0, "trend": -2.0, "last_value": 5.0},
            "network_node_density": {"mean": 8.0, "max": 12.0, "min": 4.0, "trend": -1.5, "last_value": 4.0},
        },
        "evidence_ids": ["ev_occ_count_MB_LOBBY_t2001"],
        "expected": {
            "domain": "occupancy",
            "hypothesis": "Lobby occupancy is low and declining — currently 5 persons, well below any threshold. No occupancy-related anomaly detected.",
            "evidence": ["ev_occ_count_MB_LOBBY_t2001"],
            "confidence": 0.96,
            "uncertainty": "Low occupancy at this time of day may be normal or may indicate an unusual event (e.g., evacuation drill, building closure). Context not available.",
            "recommendation": "No action required from occupancy domain perspective."
        }
    },
    {
        "event_id": "evt_occ_003",
        "building_id": "AUDITORIUM", "zone_id": "MAIN-HALL",
        "measurements": {
            "occupancy_count": {"mean": 488.0, "max": 512.0, "min": 460.0, "trend": +2.0, "last_value": 512.0},
            "network_node_density": {"mean": 495.0, "max": 520.0, "min": 470.0, "trend": +2.5, "last_value": 520.0},
        },
        "evidence_ids": ["ev_occ_count_AUD_t3001", "ev_occ_net_AUD_t3001"],
        "expected": {
            "domain": "occupancy",
            "hypothesis": "Auditorium is at or slightly above its rated capacity of ~500 persons. Network density confirms the headcount. This is a high-occupancy event that places heavy loads on HVAC, power, and fire-safety systems. The zone is at maximum rated capacity.",
            "evidence": ["ev_occ_count_AUD_t3001", "ev_occ_net_AUD_t3001"],
            "confidence": 0.91,
            "uncertainty": "Event type and scheduled duration are unknown — if this is a brief ceremony it may resolve naturally; if ongoing for hours, infrastructure stress will compound.",
            "recommendation": "Notify facilities that auditorium is at capacity. Ensure HVAC is on maximum setting, verify emergency exit accessibility, and monitor for further occupancy increase."
        }
    },
]

ALL_SCENARIOS: dict[str, list[dict]] = {
    "energy": ENERGY_SCENARIOS,
    "air_quality": AIR_QUALITY_SCENARIOS,
    "water": WATER_SCENARIOS,
    "weather": WEATHER_SCENARIOS,
    "occupancy": OCCUPANCY_SCENARIOS,
}

# ─────────────────────────────────────────────────────────
# SFT record builder
# ─────────────────────────────────────────────────────────
def build_user_message(scenario: dict) -> str:
    """Build the compact user-side message an agent receives."""
    return json.dumps({
        "event_id": scenario["event_id"],
        "building_id": scenario.get("building_id", "UNKNOWN"),
        "zone_id": scenario.get("zone_id", "UNKNOWN"),
        "measurements": scenario["measurements"],
        "evidence_ids": scenario["evidence_ids"],
        "instruction": "Analyse the provided measurements and return a DomainAnalysis JSON object. Cite only the provided evidence_ids. Do not identify a root cause. Require human follow-up."
    }, ensure_ascii=False)


def build_expected_output(expected: dict, event_id: str) -> str:
    """Build the full DomainAnalysis JSON the agent should emit."""
    output = {
        "event_id": event_id,
        **expected,
        "requires_human_approval": True,
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def build_sft_records(domain: str, scenarios: list[dict]) -> list[dict]:
    """Convert scenarios to SFT training format with train/dev/test splits."""
    records = []
    random.shuffle(scenarios)

    n = len(scenarios)
    n_train = max(1, int(n * 0.7))
    n_dev = max(1, int(n * 0.15))

    for i, scenario in enumerate(scenarios):
        if i < n_train:
            split = "train"
        elif i < n_train + n_dev:
            split = "dev"
        else:
            split = "test"

        user_msg = build_user_message(scenario)
        assistant_msg = build_expected_output(scenario["expected"], scenario["event_id"])

        records.append({
            "split": split,
            "domain": domain,
            "event_id": scenario["event_id"],
            "messages": [
                {"role": "system", "content": AGENT_SYSTEMS[domain]},
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_msg},
            ]
        })
    return records


def augment_scenarios(domain: str, scenarios: list[dict], target_count: int = 200) -> list[dict]:
    """Augment scenario list to reach target_count by randomly varying numeric parameters."""
    augmented = list(scenarios)
    while len(augmented) < target_count:
        base = random.choice(scenarios)
        new_scenario = json.loads(json.dumps(base))  # deep copy
        # Perturb all numeric measurement values by ±5-20%
        for field, stats in new_scenario["measurements"].items():
            for stat_key, val in stats.items():
                if isinstance(val, (int, float)):
                    noise = random.uniform(0.85, 1.15)
                    new_scenario["measurements"][field][stat_key] = round(val * noise, 2)
        # Generate a new event_id
        new_scenario["event_id"] = f"evt_{domain}_{len(augmented):04d}"
        augmented.append(new_scenario)
    return augmented


def main():
    parser = argparse.ArgumentParser(description="Generate SFT datasets for all 5 domain agents")
    parser.add_argument("--output", type=Path, default=Path("data/processed/sft"),
                        help="Output directory for SFT JSONL files")
    parser.add_argument("--target-count", type=int, default=200,
                        help="Target number of examples per domain (before splitting)")
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    total_written = 0
    for domain, scenarios in ALL_SCENARIOS.items():
        # Augment to get more training examples from the seed scenarios
        augmented = augment_scenarios(domain, scenarios, args.target_count)
        records = build_sft_records(domain, augmented)

        output_path = args.output / f"agent_{domain}.jsonl"
        with open(output_path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        train_count = sum(1 for r in records if r["split"] == "train")
        dev_count = sum(1 for r in records if r["split"] == "dev")
        test_count = sum(1 for r in records if r["split"] == "test")

        print(f"  ✓ {domain:12s} → {output_path}  "
              f"(train={train_count}, dev={dev_count}, test={test_count}, total={len(records)})")
        total_written += len(records)

    print(f"\n✅ Total SFT records written: {total_written}")
    print(f"   Directory: {args.output.resolve()}")
    print(f"\nNext step — train each domain adapter:")
    print(f"  wsl bash -c 'source .venv/bin/activate && make train-llama-roles DOMAIN=energy'")
    print(f"  wsl bash -c 'source .venv/bin/activate && make train-llama-roles DOMAIN=water'")
    print(f"  wsl bash -c 'source .venv/bin/activate && make train-llama-roles DOMAIN=weather'")
    print(f"  wsl bash -c 'source .venv/bin/activate && make train-llama-roles DOMAIN=occupancy'")


if __name__ == "__main__":
    main()
