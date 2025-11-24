-- Phase 3: Analytics and Monitoring Tables
-- This migration adds time-series analytics tables

-- Enable TimescaleDB extension
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Create analytics schema
CREATE SCHEMA IF NOT EXISTS analytics;

-- Request metrics table for tracking API performance
CREATE TABLE IF NOT EXISTS analytics.request_metrics (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(10) NOT NULL,
    status_code INTEGER NOT NULL,
    response_time FLOAT NOT NULL, -- in milliseconds
    user_id VARCHAR(255),
    user_agent TEXT,
    ip_address INET,
    request_size BIGINT,
    response_size BIGINT,
    cache_hit BOOLEAN DEFAULT FALSE,
    error_message TEXT
);

-- Create hypertable for request_metrics
SELECT create_hypertable('analytics.request_metrics', 'timestamp',
    chunk_time_interval => INTERVAL '1 hour');

-- Add indexes for efficient querying
CREATE INDEX idx_request_metrics_endpoint_time
    ON analytics.request_metrics (endpoint, timestamp DESC);
CREATE INDEX idx_request_metrics_status_time
    ON analytics.request_metrics (status_code, timestamp DESC);
CREATE INDEX idx_request_metrics_response_time
    ON analytics.request_metrics (response_time);

-- Domain extraction metrics table
CREATE TABLE IF NOT EXISTS analytics.extraction_metrics (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    job_id VARCHAR(255) NOT NULL,
    domain VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL, -- 'success', 'failed', 'timeout', 'retry'
    extraction_time FLOAT, -- in seconds
    cache_hit BOOLEAN DEFAULT FALSE,
    extraction_method VARCHAR(100),
    status_code INTEGER,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    concurrent_tasks INTEGER,
    worker_id VARCHAR(255)
);

-- Create hypertable for extraction_metrics
SELECT create_hypertable('analytics.extraction_metrics', 'timestamp',
    chunk_time_interval => INTERVAL '1 hour');

-- Add indexes
CREATE INDEX idx_extraction_metrics_domain_time
    ON analytics.extraction_metrics (domain, timestamp DESC);
CREATE INDEX idx_extraction_metrics_status_time
    ON analytics.extraction_metrics (status, timestamp DESC);
CREATE INDEX idx_extraction_metrics_job
    ON analytics.extraction_metrics (job_id);

-- System performance metrics table
CREATE TABLE IF NOT EXISTS analytics.system_metrics (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cpu_usage FLOAT, -- percentage
    memory_usage FLOAT, -- percentage
    disk_usage FLOAT, -- percentage
    active_connections INTEGER DEFAULT 0,
    queue_length INTEGER DEFAULT 0,
    workers_active INTEGER DEFAULT 0,
    workers_total INTEGER DEFAULT 0,
    redis_memory_usage BIGINT, -- in bytes
    redis_connected_clients INTEGER,
    database_connections INTEGER,
    database_size BIGINT -- in bytes
);

-- Create hypertable for system_metrics
SELECT create_hypertable('analytics.system_metrics', 'timestamp',
    chunk_time_interval => INTERVAL '5 minutes');

-- Domain statistics table (aggregated data)
CREATE TABLE IF NOT EXISTS analytics.domain_stats (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date DATE NOT NULL,
    total_domains_extracted INTEGER DEFAULT 0,
    successful_extractions INTEGER DEFAULT 0,
    failed_extractions INTEGER DEFAULT 0,
    cache_hits INTEGER DEFAULT 0,
    cache_misses INTEGER DEFAULT 0,
    avg_extraction_time FLOAT,
    unique_domains INTEGER DEFAULT 0,
    top_domains JSONB, -- top 10 domains by frequency
    error_types JSONB -- error types and counts
);

-- Create hypertable for domain_stats (daily aggregation)
SELECT create_hypertable('analytics.domain_stats', 'timestamp',
    chunk_time_interval => INTERVAL '1 day');

-- User activity metrics table
CREATE TABLE IF NOT EXISTS analytics.user_activity (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id VARCHAR(255) NOT NULL,
    action VARCHAR(100) NOT NULL, -- 'login', 'extract', 'upload', 'download'
    resource_type VARCHAR(100),
    resource_id VARCHAR(255),
    metadata JSONB,
    ip_address INET,
    user_agent TEXT
);

-- Create hypertable for user_activity
SELECT create_hypertable('analytics.user_activity', 'timestamp',
    chunk_time_interval => INTERVAL '1 hour');

-- Create indexes
CREATE INDEX idx_user_activity_user_time
    ON analytics.user_activity (user_id, timestamp DESC);
CREATE INDEX idx_user_activity_action_time
    ON analytics.user_activity (action, timestamp DESC);

-- Alerts table for monitoring
CREATE TABLE IF NOT EXISTS analytics.alerts (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    alert_type VARCHAR(100) NOT NULL,
    message TEXT NOT NULL,
    details JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved', 'acknowledged')),
    acknowledged_by VARCHAR(255),
    acknowledged_at TIMESTAMPTZ,
    resolved_by VARCHAR(255),
    tags TEXT[]
);

-- Add indexes for alerts
CREATE INDEX idx_alerts_status_severity
    ON analytics.alerts (status, severity, created_at DESC);
CREATE INDEX idx_alerts_type
    ON analytics.alerts (alert_type, created_at DESC);

-- Create views for common analytics queries

-- Hourly extraction performance view
CREATE OR REPLACE VIEW analytics.hourly_extraction_stats AS
SELECT
    time_bucket('1 hour', timestamp) AS hour,
    COUNT(*) AS total_extractions,
    COUNT(*) FILTER (WHERE status = 'success') AS successful,
    COUNT(*) FILTER (WHERE status = 'failed') AS failed,
    AVG(extraction_time) AS avg_extraction_time,
    MAX(extraction_time) AS max_extraction_time,
    COUNT(*) FILTER (WHERE cache_hit = true) AS cache_hits,
    COUNT(*) FILTER (WHERE cache_hit = false) AS cache_misses
FROM analytics.extraction_metrics
GROUP BY hour
ORDER BY hour DESC;

-- Daily API performance view
CREATE OR REPLACE VIEW analytics.daily_api_stats AS
SELECT
    time_bucket('1 day', timestamp) AS day,
    endpoint,
    COUNT(*) AS total_requests,
    AVG(response_time) AS avg_response_time,
    MAX(response_time) AS max_response_time,
    MIN(response_time) AS min_response_time,
    percentile_cont(0.95) WITHIN GROUP (ORDER BY response_time) AS p95_response_time,
    COUNT(*) FILTER (WHERE status_code >= 400) AS error_count,
    COUNT(*) FILTER (WHERE cache_hit = true) AS cache_hits
FROM analytics.request_metrics
GROUP BY day, endpoint
ORDER BY day DESC, endpoint;

-- Error rate trends view
CREATE OR REPLACE VIEW analytics.error_rate_trends AS
SELECT
    time_bucket('1 hour', timestamp) AS hour,
    COUNT(*) AS total_requests,
    COUNT(*) FILTER (WHERE status_code >= 400) AS errors,
    (COUNT(*) FILTER (WHERE status_code >= 400) * 100.0 / COUNT(*)) AS error_percentage
FROM analytics.request_metrics
GROUP BY hour
ORDER BY hour DESC;

-- Set up data retention policies
-- Keep detailed metrics for 30 days, then aggregate to hourly
SELECT add_retention_policy('analytics.request_metrics', INTERVAL '30 days');
SELECT add_retention_policy('analytics.extraction_metrics', INTERVAL '30 days');
SELECT add_retention_policy('analytics.system_metrics', INTERVAL '7 days');
SELECT add_retention_policy('analytics.user_activity', INTERVAL '90 days');

-- Create continuous aggregates for hourly data
CREATE MATERIALIZED VIEW analytics.hourly_request_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', timestamp) AS hour,
    endpoint,
    COUNT(*) AS request_count,
    AVG(response_time) AS avg_response_time,
    MAX(response_time) AS max_response_time,
    COUNT(*) FILTER (WHERE status_code >= 400) AS error_count
FROM analytics.request_metrics
GROUP BY hour, endpoint;

-- Create continuous aggregates for daily data
CREATE MATERIALIZED VIEW analytics.daily_domain_stats
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', timestamp) AS day,
    COUNT(DISTINCT domain) AS unique_domains,
    COUNT(*) AS total_extractions,
    COUNT(*) FILTER (WHERE status = 'success') AS successful,
    AVG(extraction_time) AS avg_extraction_time
FROM analytics.extraction_metrics
GROUP BY day;

-- Add comments for documentation
COMMENT ON TABLE analytics.request_metrics IS 'Tracks all API requests for performance analytics';
COMMENT ON TABLE analytics.extraction_metrics IS 'Tracks domain extraction performance and outcomes';
COMMENT ON TABLE analytics.system_metrics IS 'System resource usage and performance indicators';
COMMENT ON TABLE analytics.domain_stats IS 'Daily aggregated domain extraction statistics';
COMMENT ON TABLE analytics.user_activity IS 'User activity tracking for engagement analytics';
COMMENT ON TABLE analytics.alerts IS 'System alerts and notifications for monitoring';

-- Grant permissions (adjust as needed)
-- GRANT USAGE ON SCHEMA analytics TO domain_user;
-- GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA analytics TO domain_user;