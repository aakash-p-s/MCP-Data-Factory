"""
backend/registry/models.py

SQLAlchemy ORM models — mirrors init-registry-db.sql exactly.
12 tables total covering the full control-plane source of truth.

PRD reference: Section 7.4
"""

from sqlalchemy import (
    Column, Integer, BigInteger, Text, Boolean,
    TIMESTAMP, ForeignKey, func
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Product(Base):
    __tablename__ = "products"
    product_id  = Column(Integer, primary_key=True)
    name        = Column(Text, nullable=False, unique=True)
    description = Column(Text)
    owner_email = Column(Text, nullable=False)
    created_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())
    servers     = relationship("MCPServer", back_populates="product")


class Connector(Base):
    __tablename__ = "connectors"
    connector_id   = Column(Integer, primary_key=True)
    product_id     = Column(Integer, ForeignKey("products.product_id"))
    connector_type = Column(Text, nullable=False)
    backend_url    = Column(Text, nullable=False)
    created_at     = Column(TIMESTAMP(timezone=True), server_default=func.now())


class MCPServer(Base):
    __tablename__ = "mcp_servers"
    server_id    = Column(Integer, primary_key=True)
    product_id   = Column(Integer, ForeignKey("products.product_id"))
    connector_id = Column(Integer, ForeignKey("connectors.connector_id"))
    server_name  = Column(Text, nullable=False, unique=True)
    domain       = Column(Text, nullable=False)
    status       = Column(Text, nullable=False, default="pending")
    kong_route   = Column(Text)
    port         = Column(Integer)
    created_at   = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at   = Column(TIMESTAMP(timezone=True), server_default=func.now())
    product      = relationship("Product", back_populates="servers")
    tools        = relationship("ToolSpec", back_populates="server")
    health_checks = relationship("HealthCheck", back_populates="server")


class ToolSpec(Base):
    __tablename__ = "tool_specs"
    tool_id      = Column(Integer, primary_key=True)
    server_id    = Column(Integer, ForeignKey("mcp_servers.server_id"))
    tool_name    = Column(Text, nullable=False)
    description  = Column(Text)
    input_schema = Column(JSONB)
    output_type  = Column(Text)
    created_at   = Column(TIMESTAMP(timezone=True), server_default=func.now())
    server       = relationship("MCPServer", back_populates="tools")
    rbac_mappings = relationship("RBACMapping", back_populates="tool")


class RBACMapping(Base):
    __tablename__ = "rbac_mappings"
    mapping_id     = Column(Integer, primary_key=True)
    tool_id        = Column(Integer, ForeignKey("tool_specs.tool_id"))
    role_name      = Column(Text, nullable=False)
    allowed        = Column(Boolean, nullable=False, default=False)
    required_scope = Column(Text)
    created_at     = Column(TIMESTAMP(timezone=True), server_default=func.now())
    tool           = relationship("ToolSpec", back_populates="rbac_mappings")


class DeploymentEnvironment(Base):
    __tablename__ = "deployment_environments"
    env_id      = Column(Integer, primary_key=True)
    server_id   = Column(Integer, ForeignKey("mcp_servers.server_id"))
    env_name    = Column(Text, nullable=False)
    deployed_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    deployed_by = Column(Text)
    image_tag   = Column(Text)
    notes       = Column(Text)


class GatewayRoute(Base):
    __tablename__ = "gateway_routes"
    route_id          = Column(Integer, primary_key=True)
    server_id         = Column(Integer, ForeignKey("mcp_servers.server_id"))
    kong_route        = Column(Text, nullable=False)
    kong_service      = Column(Text, nullable=False)
    rate_limit_minute = Column(Integer)
    registered_at     = Column(TIMESTAMP(timezone=True), server_default=func.now())


class APIRegistry(Base):
    __tablename__ = "api_registry"
    api_id        = Column(Integer, primary_key=True)
    server_id     = Column(Integer, ForeignKey("mcp_servers.server_id"))
    backstage_ref = Column(Text)
    openapi_spec  = Column(JSONB)
    registered_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class AgentIntegration(Base):
    __tablename__ = "agent_integrations"
    integration_id = Column(Integer, primary_key=True)
    server_id      = Column(Integer, ForeignKey("mcp_servers.server_id"))
    agent_name     = Column(Text, nullable=False)
    mcp_client_url = Column(Text, nullable=False)
    registered_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    event_id          = Column(BigInteger, primary_key=True)
    who               = Column(Text, nullable=False)
    what              = Column(Text, nullable=False)
    when_ts           = Column(TIMESTAMP(timezone=True), server_default=func.now())
    outcome           = Column(Text, nullable=False)
    reason            = Column(Text)
    purpose_of_access = Column(Text, nullable=False)
    trace_id          = Column(Text)
    server_name       = Column(Text)


class HealthCheck(Base):
    __tablename__ = "health_checks"
    check_id   = Column(BigInteger, primary_key=True)
    server_id  = Column(Integer, ForeignKey("mcp_servers.server_id"))
    checked_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    status     = Column(Text, nullable=False)
    latency_ms = Column(Integer)
    error_msg  = Column(Text)
    server     = relationship("MCPServer", back_populates="health_checks")


class SchemaSnapshot(Base):
    __tablename__ = "schema_snapshots"
    snapshot_id    = Column(Integer, primary_key=True)
    server_id      = Column(Integer, ForeignKey("mcp_servers.server_id"))
    captured_at    = Column(TIMESTAMP(timezone=True), server_default=func.now())
    schema_json    = Column(JSONB, nullable=False)
    diff_from_prev = Column(JSONB)
