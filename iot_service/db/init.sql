-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Table for telemetry metrics
CREATE TABLE IF NOT EXISTS metrics (\n    time TIMESTAMPTZ NOT NULL,
    machine_id TEXT NOT NULL,
    metric TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL
);

-- Convert to TimescaleDB hypertable partitioned by time
SELECT create_hypertable('metrics', 'time', if_not_exists => TRUE);

-- Compound index for rapid metric querying by machine and time
CREATE INDEX IF NOT EXISTS idx_metrics_machine_metric_time 
ON metrics (machine_id, metric, time DESC);

-- Table for system and machine events
CREATE TABLE IF NOT EXISTS events (\n    event_id UUID PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    machine_id TEXT NOT NULL,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    error_code TEXT NOT NULL,
    message TEXT NOT NULL,
    payload JSONB DEFAULT '{}'::jsonb,
    incident_id TEXT,
    repeat_count INTEGER DEFAULT 1,
    last_seen_ts TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for event querying
CREATE INDEX IF NOT EXISTS idx_events_machine_ts 
ON events (machine_id, ts DESC);

CREATE INDEX IF NOT EXISTS idx_events_machine_error_code 
ON events (machine_id, error_code, ts DESC);

-- Retention policy: keep metrics for 7 days
SELECT add_retention_policy('metrics', INTERVAL '7 days', if_not_exists => TRUE);

-- Phase 2 Tables: Incidents, Actions, Audit Log
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    severity TEXT NOT NULL DEFAULT 'medium',
    title TEXT NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    timeline JSONB NOT NULL DEFAULT '[]'::jsonb,
    root_cause TEXT,
    confidence DOUBLE PRECISION,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_incidents_machine_status
ON incidents (machine_id, status);

CREATE INDEX IF NOT EXISTS idx_incidents_opened_at
ON incidents (opened_at DESC);

CREATE TABLE IF NOT EXISTS actions (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(id),
    machine_id TEXT NOT NULL,
    command TEXT NOT NULL,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    decided_by TEXT,
    decided_at TIMESTAMPTZ,
    ack JSONB,
    auto_executed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_actions_incident
ON actions (incident_id);

CREATE INDEX IF NOT EXISTS idx_actions_status
ON actions (status);

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    machine_id TEXT NOT NULL,
    incident_id TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_audit_log_ts
ON audit_log (ts DESC);

-- Phase 3 Tables: Work Orders, Agent Steps
CREATE TABLE IF NOT EXISTS work_orders (
    id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(id),
    machine_id TEXT NOT NULL,
    title TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'medium',
    steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    parts JSONB NOT NULL DEFAULT '[]'::jsonb,
    citations JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_work_orders_incident
ON work_orders (incident_id);

CREATE INDEX IF NOT EXISTS idx_work_orders_machine
ON work_orders (machine_id);

CREATE TABLE IF NOT EXISTS agent_steps (
    id BIGSERIAL PRIMARY KEY,
    incident_id TEXT NOT NULL REFERENCES incidents(id),
    step_number INT NOT NULL,
    thought TEXT,
    tool TEXT,
    tool_args JSONB NOT NULL DEFAULT '{}'::jsonb,
    tool_result JSONB NOT NULL DEFAULT '{}'::jsonb,
    latency_ms FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_steps_incident
ON agent_steps (incident_id, step_number);
