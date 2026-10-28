-- Proposed device store for the reasoner's tools (design draft, 2026-10-23).
-- SQLite via modernc.org/sqlite (pure Go: keeps the backend's CGO_ENABLED=0 GOOS=linux GOARCH=arm64 build).
-- The JSONL store (state/incidents.jsonl) stays the source of truth for full incident records; these
-- tables are a derived, rebuildable index written in the same persist() path. Fog uses the same schema
-- (PostgreSQL + pgvector, or SQLite + sqlite-vec), plus an embeddings table.
PRAGMA journal_mode = WAL;        -- crash-safe under brownouts (HANDBOOK 2.34); readers never block the writer
PRAGMA synchronous = NORMAL;

-- One row per incident, ALL TIME (about 300 bytes each: 100k incidents ~ 30 MB). Kept even after the full
-- record leaves the 1000-incident retention window, so counting questions stay exact offline.
CREATE TABLE IF NOT EXISTS incident (
  id             TEXT PRIMARY KEY,            -- INC-0123
  version        INTEGER NOT NULL,            -- bumps on every persisted state change (sync key)
  created_wall   TEXT NOT NULL,               -- ISO-8601 IST, operator clock
  created_sim    INTEGER NOT NULL,            -- sensor-time epoch s (replay/demo clock)
  state          TEXT NOT NULL,               -- running | done | failed
  mode           INTEGER NOT NULL,
  severity       TEXT NOT NULL,               -- final (reasoner) severity
  severity_final INTEGER NOT NULL,
  rule_severity  TEXT,
  label          TEXT,                        -- cross-domain root-cause label
  root_cause     TEXT,
  title          TEXT,
  refine_stage   TEXT,                        -- early | 1.5h | 3h
  resolved_at    TEXT,
  approval       TEXT,                        -- pending | approved | dismissed
  approval_note  TEXT,
  injected       INTEGER NOT NULL DEFAULT 0,  -- demo injections are excluded by default
  full_on_device INTEGER NOT NULL DEFAULT 1,  -- 0 once archived out of the 1000-incident window
  synced_version INTEGER NOT NULL DEFAULT 0   -- highest version acknowledged by the fog
);
CREATE INDEX IF NOT EXISTS incident_time ON incident(created_wall);
CREATE INDEX IF NOT EXISTS incident_sev  ON incident(severity, created_wall);

-- One row per sensor in an incident (flagged or context) with the final finding used in the report.
CREATE TABLE IF NOT EXISTS incident_sensor (
  incident_id  TEXT NOT NULL REFERENCES incident(id),
  ref          TEXT NOT NULL,                 -- S1, S2 ...
  node         TEXT NOT NULL,
  metric       TEXT NOT NULL,
  domain       TEXT NOT NULL,
  location     TEXT,
  context      INTEGER NOT NULL,              -- 1 = pulled in by the orchestrator, not flagged
  source       TEXT NOT NULL,                 -- agent | rule (which finding the report used)
  pattern      TEXT,
  status       TEXT,                          -- normal | warning | critical | sensor_fault
  likely_cause TEXT,
  fault_kind   TEXT,                          -- v2 enum, only when status = sensor_fault
  onset        TEXT,
  PRIMARY KEY (incident_id, ref)
);
CREATE INDEX IF NOT EXISTS isens_metric ON incident_sensor(domain, metric, pattern);
CREATE INDEX IF NOT EXISTS isens_fault  ON incident_sensor(status, node);

-- Maintenance / asset log. NEW: today nothing records a sensor replacement, so "how many sensors had to
-- be changed" is unanswerable until the operator UI writes these rows (e.g. a "Sensor replaced" button
-- on approved sensor_fault incidents, or a maintenance form). Append-only; corrections are new rows.
CREATE TABLE IF NOT EXISTS maintenance (
  seq          INTEGER PRIMARY KEY AUTOINCREMENT,
  at_wall      TEXT NOT NULL,
  node         TEXT NOT NULL,
  metric       TEXT,                          -- NULL = whole device/node
  action       TEXT NOT NULL,                 -- replaced | recalibrated | repaired | inspected_ok | removed | installed
  incident_id  TEXT,                          -- the incident that triggered it, if any
  operator     TEXT,
  note         TEXT
);
CREATE INDEX IF NOT EXISTS maint_node ON maintenance(node, at_wall);

-- Readings beyond the engine's 13 h RAM history, for get_sensor_history.
-- Raw 5-min for 30 days (~30 series x 8640 = 260k rows), hourly rollups forever (~260k rows/year).
CREATE TABLE IF NOT EXISTS reading_5min (
  node TEXT NOT NULL, metric TEXT NOT NULL, t INTEGER NOT NULL, v REAL,
  PRIMARY KEY (node, metric, t)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS reading_hourly (
  node TEXT NOT NULL, metric TEXT NOT NULL, t INTEGER NOT NULL,
  n INTEGER, mean REAL, min REAL, max REAL, last REAL,
  PRIMARY KEY (node, metric, t)
) WITHOUT ROWID;

-- Every reasoner/chat tool call, for audit, evaluation and self-learning (like the agent call log).
CREATE TABLE IF NOT EXISTS tool_call (
  seq        INTEGER PRIMARY KEY AUTOINCREMENT,
  at_wall    TEXT NOT NULL,
  session    TEXT NOT NULL,                   -- chat session id or incident id
  tool       TEXT NOT NULL,
  args_json  TEXT NOT NULL,
  result_json TEXT NOT NULL,
  source     TEXT NOT NULL,                   -- device | fog
  ms         REAL
);

-- Sync outbox to the fog: one row per persisted change, deleted once acknowledged.
CREATE TABLE IF NOT EXISTS outbox (
  seq     INTEGER PRIMARY KEY AUTOINCREMENT,
  kind    TEXT NOT NULL,                      -- incident | maintenance | reading_hourly | tool_call
  key     TEXT NOT NULL,                      -- e.g. INC-0123@7
  body    BLOB NOT NULL                       -- gzip JSON
);

-- Example exact queries the executor issues (the LLM never writes SQL):
-- "How many CO2 spike incidents this year?"
--   SELECT COUNT(DISTINCT i.id) FROM incident i JOIN incident_sensor s ON s.incident_id = i.id
--   WHERE s.metric = 'co2' AND s.context = 0 AND s.pattern IN ('spike','exp_rise','step_increase')
--     AND i.injected = 0 AND i.created_wall >= '2026-01-01' AND i.created_wall < '2027-01-01';
--   (which patterns count as a "spike" is an executor-side synonym table, shown back in the answer)
-- "How many sensors were faulty at some time this year?"  (basis = ai)
--   SELECT COUNT(DISTINCT s.node || '/' || s.metric) FROM incident_sensor s JOIN incident i ON i.id = s.incident_id
--   WHERE s.status = 'sensor_fault' AND i.injected = 0 AND i.created_wall >= '2026-01-01';
-- "... and had to be changed?"  (basis = replaced)
--   SELECT COUNT(DISTINCT node || '/' || COALESCE(metric,'*')) FROM maintenance
--   WHERE action = 'replaced' AND at_wall >= '2026-01-01';
