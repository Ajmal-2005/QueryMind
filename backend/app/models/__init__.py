"""SQLAlchemy models.

Importing this package registers every model on ``Base.metadata``, which
Alembic autogenerate and ``create_all`` both rely on.
"""

from app.models.audit import AuditLog
from app.models.connection import Connection, ConnectionStatus, Dialect
from app.models.query import Query, QueryStatus
from app.models.user import User, UserRole

__all__ = [
    "AuditLog",
    "Connection",
    "ConnectionStatus",
    "Dialect",
    "Query",
    "QueryStatus",
    "User",
    "UserRole",
]
