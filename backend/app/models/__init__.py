"""SQLAlchemy models.

Importing this package registers every model on ``Base.metadata``, which
Alembic autogenerate and ``create_all`` both rely on.
"""

from app.models.audit import AuditLog
from app.models.connection import Connection, ConnectionStatus, Dialect
from app.models.query import Query, QueryStatus
from app.models.schema_index import EMBEDDING_DIM, SchemaColumn, SchemaTable
from app.models.user import User, UserRole

__all__ = [
    "EMBEDDING_DIM",
    "AuditLog",
    "Connection",
    "ConnectionStatus",
    "Dialect",
    "Query",
    "QueryStatus",
    "SchemaColumn",
    "SchemaTable",
    "User",
    "UserRole",
]
