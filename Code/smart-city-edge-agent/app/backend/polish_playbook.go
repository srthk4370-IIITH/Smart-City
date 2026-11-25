package main

// Standard playbook per metric and location kind (owner 2026-11-19 #4). The static checklist used to be keyed by domain
// and level only ("increase ventilation" for outdoor PM2.5 is wrong: the fix is to close windows and shut the fresh-air
// intake). Used only when the report and the agents give no usable action; the reasoner's own checklist always wins.

import (
	"fmt"
	"strings"
)

// locationKind: "outdoor" (outdoor station, rooftop weather station) or "indoor" (room sensors), else "".
func locationKind(role, location string) string {
	l := strings.ToLower(location)
	switch {
	case role == "weather", strings.Contains(l, "outdoor"), strings.Contains(l, "rooftop"):
		return "outdoor"
	case strings.Contains(l, "indoor"), strings.Contains(l, "room"), strings.Contains(l, "classroom"), strings.Contains(l, "lab"):
		return "indoor"
	}
	return ""
}

var playbookOutdoorPM = []string{
	"Close windows and shut the fresh-air intake (set the air handlers to recirculate)",
	"Warn the occupants: sensitive people stay indoors, masks outside",
	"Check for an outdoor source (burning, construction dust, traffic, a generator)"}

var playbookWaterQuality = []string{
	"Take a water sample and test it with a kit",
	"Stop drinking use of this water until it has been tested",
	"Check the dosing and treatment (chemical feed, filters) and the source"}

var playbookTank = []string{
	"Inspect the tank, the pumps and the valves",
	"Check for a leak or an overflow, and compare with the pump schedule",
	"Confirm the level sensor with a manual reading"}

var playbookPower = []string{
	"Ask an electrician to inspect the feeder, the panel and the meter",
	"Check which loads are running against the schedule and for overloaded circuits",
	"Agree with facilities which non-essential loads can be shed"}

var playbookIndoorCO2 = []string{
	"Ventilate the room now (open windows or doors, raise the fresh-air supply)",
	"Check occupancy against the room's capacity and reduce it if it is crowded",
	"Re-check CO2 over the next 30 min"}

var playbookTemperature = []string{
	"Check the AC / HVAC unit: setpoint, schedule, filters and whether it is running",
	"Compare the room temperature with the setpoint and with a nearby room",
	"If the room is empty, switch the unit off or to its schedule (operator decision)"}

// metricPlaybookFor: the playbook for one sensor, nil when this metric has no specific one.
func metricPlaybookFor(role, metric, location string) []string {
	kind := locationKind(role, location)
	switch metric {
	case "pm25", "pm10":
		if kind == "indoor" {
			return []string{"Ventilate the room and look for an indoor source (cleaning, construction, cooking, printers)",
				"Run the air purifiers if there are any and keep occupancy low", "Re-check PM over the next 30 min"}
		}
		return playbookOutdoorPM
	case "ph", "tds":
		return playbookWaterQuality
	case "level":
		return playbookTank
	case "power_kw", "pf":
		return playbookPower
	case "co2":
		if kind != "outdoor" {
			return playbookIndoorCO2
		}
	case "temp", "room_temp", "ac_units_on", "ac_on":
		if role == "air_quality" || role == "hvac" {
			return playbookTemperature
		}
	}
	return nil
}

// metricPlaybook picks the worst flagged sensor of the incident and returns its playbook with the "why" text.
func metricPlaybook(inc *Incident, level string) ([]string, string) {
	var pick *SensorRef
	for i := range inc.Sensors {
		s := &inc.Sensors[i]
		if s.Context {
			continue
		}
		if pick == nil || reportRank[normSeverity(s.Rule.Status)] > reportRank[normSeverity(pick.Rule.Status)] {
			pick = s
		}
	}
	if pick == nil {
		return nil, ""
	}
	list := metricPlaybookFor(pick.Role, pick.Metric, pick.Location)
	if list == nil {
		return nil, ""
	}
	where := locationKind(pick.Role, pick.Location)
	if where != "" {
		where += " "
	}
	return list, fmt.Sprintf("Standard steps for a %s %s%s alarm (no specific AI recommendation)", level, where, metricWord(pick.Metric))
}
