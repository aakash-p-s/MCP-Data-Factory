"""Pluggable Connector ABC — Codebase PRD §5.2.

One shared interface, two implementations: SQLConnector (TimescaleDB/Postgres,
used by 3 servers) and VectorConnector (Qdrant, used by clinical_notes_search).
Both MUST sit behind this exact interface — this is the architecture's core
'pluggable connector' proof. Do not add source-specific methods here.
"""

from abc import ABC, abstractmethod


class Connector(ABC):
    """Abstract base every data connector implements."""

    @abstractmethod
    async def connect(self) -> None:
        """Open the underlying connection/pool (DB pool or Qdrant client)."""
        ...

    @abstractmethod
    async def auth(self) -> None:
        """Authenticate to the backend, if it requires credentials."""
        ...

    @abstractmethod
    async def schema(self) -> dict:
        """Return source schema metadata.

        SQL: introspected tables/columns. Vector: collection vector size +
        metadata field names.
        """
        ...

    @abstractmethod
    async def query(self, params: dict) -> list[dict]:
        """Execute a read-only query and return rows.

        SQL: a parameterized SELECT (never raw string interpolation).
        Vector: a similarity search over the embedded query text.
        """
        ...
