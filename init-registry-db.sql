-- Patient Risk Intelligence — registry-db
-- 12-table control-plane source of truth
-- Auto-runs on first Postgres container start

CREATE TABLE IF NOT EXISTS products (
    product_id   SERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    description  TEXT,
    owner_email  TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS connectors (
    connector_id   SERIAL PRIMARY KEY,
    product_id     INT REFERENCES products(product_id),
    connector_type TEXT NOT NULL CHECK (connector_type IN ('sql','vector')),
    backend_url    TEXT NOT NULL,
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mcp_servers (
    server_id    SERIAL PRIMARY KEY,
    product_id   INT REFERENCES products(product_id),
    connector_id INT REFERENCES connectors(connector_id),
    server_name  TEXT NOT NULL UNIQUE,
    domain       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','healthy','unhealthy','deploying')),
    kong_route   TEXT,
    port         INT,
    created_at   TIMESTAMPTZ DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tool_specs (
    tool_id      SERIAL PRIMARY KEY,
    server_id    INT REFERENCES mcp_servers(server_id),
    tool_name    TEXT NOT NULL,
    description  TEXT,
    input_schema JSONB,
    output_type  TEXT,
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rbac_mappings (
    mapping_id     SERIAL PRIMARY KEY,
    tool_id        INT REFERENCES tool_specs(tool_id),
    role_name      TEXT NOT NULL
                   CHECK (role_name IN (
                       'grp-clinical-viewer',
                       'grp-physician',
                       'grp-case-manager'
                   )),
    allowed        BOOLEAN NOT NULL DEFAULT false,
    required_scope TEXT,
    created_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS deployment_environments (
    env_id       SERIAL PRIMARY KEY,
    server_id    INT REFERENCES mcp_servers(server_id),
    env_name     TEXT NOT NULL CHECK (env_name IN ('dev','staging','prod')),
    deployed_at  TIMESTAMPTZ DEFAULT now(),
    deployed_by  TEXT,
    image_tag    TEXT,
    notes        TEXT
);

CREATE TABLE IF NOT EXISTS gateway_routes (
    route_id          SERIAL PRIMARY KEY,
    server_id         INT REFERENCES mcp_servers(server_id),
    kong_route        TEXT NOT NULL,
    kong_service      TEXT NOT NULL,
    rate_limit_minute INT,
    registered_at     TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_registry (
    api_id        SERIAL PRIMARY KEY,
    server_id     INT REFERENCES mcp_servers(server_id),
    backstage_ref TEXT,
    openapi_spec  JSONB,
    registered_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_integrations (
    integration_id SERIAL PRIMARY KEY,
    server_id      INT REFERENCES mcp_servers(server_id),
    agent_name     TEXT NOT NULL,
    mcp_client_url TEXT NOT NULL,
    registered_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_events (
    event_id          BIGSERIAL PRIMARY KEY,
    who               TEXT NOT NULL,
    what              TEXT NOT NULL,
    when_ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
    outcome           TEXT NOT NULL CHECK (outcome IN ('200','401','403','429')),
    reason            TEXT,
    purpose_of_access TEXT NOT NULL CHECK (
        purpose_of_access IN (
            'deterioration_review',
            'medication_reconciliation',
            'discharge_planning',
            'care_coordination',
            'routine_review'
        )
    ),
    trace_id    TEXT,
    server_name TEXT
);

CREATE TABLE IF NOT EXISTS health_checks (
    check_id   BIGSERIAL PRIMARY KEY,
    server_id  INT REFERENCES mcp_servers(server_id),
    checked_at TIMESTAMPTZ DEFAULT now(),
    status     TEXT NOT NULL CHECK (status IN ('healthy','unhealthy')),
    latency_ms INT,
    error_msg  TEXT
);

CREATE TABLE IF NOT EXISTS schema_snapshots (
    snapshot_id    SERIAL PRIMARY KEY,
    server_id      INT REFERENCES mcp_servers(server_id),
    captured_at    TIMESTAMPTZ DEFAULT now(),
    schema_json    JSONB NOT NULL,
    diff_from_prev JSONB
);

-- Useful indexes
CREATE INDEX IF NOT EXISTS idx_audit_who     ON audit_events(who);
CREATE INDEX IF NOT EXISTS idx_audit_when    ON audit_events(when_ts);
CREATE INDEX IF NOT EXISTS idx_audit_purpose ON audit_events(purpose_of_access);
CREATE INDEX IF NOT EXISTS idx_health_server ON health_checks(server_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_name      ON mcp_servers(server_name);

-- Seed the product and 4 MCP server rows so registry is pre-populated on startup
INSERT INTO products (name, description, owner_email) VALUES
    ('patient-risk-intelligence',
     'Patient Risk Intelligence MCP Platform',
     'platform@hospital.com')
ON CONFLICT (name) DO NOTHING;

INSERT INTO mcp_servers (product_id, server_name, domain, kong_route, port) VALUES
    (1, 'vitals_trends',            'vitals_trends', '/mcp/clinical/vitals-trends/dev',           8001),
    (1, 'labs_diagnoses',           'labs_diagnoses', '/mcp/clinical/labs-diagnoses/dev',          8002),
    (1, 'medications_interactions', 'medications_interactions', '/mcp/clinical/medications-interactions/dev', 8003),
    (1, 'clinical_notes_search',    'clinical_notes_search', '/mcp/clinical/clinical-notes-search/dev',   8004)
ON CONFLICT (server_name) DO NOTHING;
