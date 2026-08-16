"""Connection registration, testing, indexing, and schema retrieval."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.audit import AuditLog
from app.models.connection import Connection, ConnectionStatus
from app.models.schema_index import SchemaTable
from app.models.user import User
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionRead,
    ConnectionTestResponse,
    IndexResponse,
)
from app.schemas.schema_index import SchemaGraphEdge, SchemaResponse, TableRead
from app.services.cache.results import invalidate_connection
from app.services.connection.manager import (
    Credentials,
    check_connection,
    encrypt_credentials,
)
from app.services.linking.indexer import index_connection, load_graph, mark_index_failed

log = get_logger(__name__)
router = APIRouter()


def _owned_connection(connection_id: str, db: Session, user: User) -> Connection:
    """Fetch a connection, 404ing unless this user owns it.

    404 rather than 403 for someone else's connection: a 403 would confirm
    the id exists.
    """
    connection = db.get(Connection, connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found"
        )
    return connection


@router.post(
    "",
    response_model=ConnectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a database connection",
)
def create_connection(
    payload: ConnectionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConnectionRead:
    connection = Connection(
        user_id=user.id,
        name=payload.name,
        dialect=payload.dialect,
        host=payload.host,
        port=payload.port or 0,
        database=payload.database,
        encrypted_credentials=encrypt_credentials(
            Credentials(username=payload.username, password=payload.password)
        ),
        status=ConnectionStatus.PENDING,
    )
    db.add(connection)
    db.flush()

    # The payload holds a password, so log only non-secret identifiers.
    db.add(
        AuditLog(
            user_id=user.id,
            action="connection.create",
            payload={
                "connection_id": connection.id,
                "dialect": payload.dialect.value,
                "database": payload.database,
            },
        )
    )
    db.commit()
    db.refresh(connection)

    return ConnectionRead.model_validate(connection)


@router.get("", response_model=list[ConnectionRead], summary="List connections")
def list_connections(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ConnectionRead]:
    connections = db.scalars(
        select(Connection)
        .where(Connection.user_id == user.id)
        .order_by(Connection.created_at.desc())
    )
    return [ConnectionRead.model_validate(c) for c in connections]


@router.get("/{connection_id}", response_model=ConnectionRead, summary="Get one")
def get_connection(
    connection_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConnectionRead:
    return ConnectionRead.model_validate(_owned_connection(connection_id, db, user))


@router.post(
    "/{connection_id}/test",
    response_model=ConnectionTestResponse,
    summary="Verify connectivity",
)
def test(
    connection_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ConnectionTestResponse:
    connection = _owned_connection(connection_id, db, user)
    result = check_connection(connection)

    # Do not downgrade an already-indexed connection to merely "connected".
    if result.ok:
        if connection.status in (ConnectionStatus.PENDING, ConnectionStatus.FAILED):
            connection.status = ConnectionStatus.CONNECTED
        connection.last_error = None
    else:
        connection.status = ConnectionStatus.FAILED
        connection.last_error = result.error
    db.commit()

    return ConnectionTestResponse(
        ok=result.ok,
        latency_ms=result.latency_ms,
        server_version=result.server_version,
        error=result.error,
    )


@router.post(
    "/{connection_id}/index",
    response_model=IndexResponse,
    summary="Introspect and index the schema",
)
def index(
    connection_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IndexResponse:
    """Run introspection, description, and embedding.

    Synchronous for now. The proposal moves this to Celery, which matters
    for a 400-table schema; at demo scale it completes well inside a request.
    """
    connection = _owned_connection(connection_id, db, user)

    # Re-indexing means the schema moved. Results cached against the old shape
    # must not outlive it.
    invalidate_connection(connection.id)

    try:
        result = index_connection(db, connection)
    except Exception as exc:  # noqa: BLE001 - any failure must be recorded
        mark_index_failed(db, connection, str(exc))
        log.warning("indexing_failed", connection_id=connection_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Indexing failed: {exc}"[:500],
        ) from exc

    db.add(
        AuditLog(
            user_id=user.id,
            action="connection.index",
            payload={
                "connection_id": connection.id,
                "tables": result.tables_indexed,
            },
        )
    )
    db.commit()

    return IndexResponse(**result.__dict__)


@router.get(
    "/{connection_id}/schema",
    response_model=SchemaResponse,
    summary="Return the indexed schema graph",
)
def get_schema(
    connection_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SchemaResponse:
    connection = _owned_connection(connection_id, db, user)

    tables = list(
        db.scalars(
            select(SchemaTable)
            .where(SchemaTable.connection_id == connection.id)
            .order_by(SchemaTable.table_name)
        )
    )
    if not tables:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Schema not indexed yet. POST to /index first.",
        )

    graph = load_graph(db, connection.id)

    # Each undirected pair once, in a stable order.
    edges = sorted(
        {
            (min(a, b), max(a, b))
            for a, neighbors in graph.adjacency.items()
            for b in neighbors
        }
    )

    return SchemaResponse(
        connection_id=connection.id,
        table_count=len(tables),
        column_count=sum(len(t.columns) for t in tables),
        tables=[TableRead.model_validate(t) for t in tables],
        edges=[SchemaGraphEdge(from_table=a, to_table=b) for a, b in edges],
        isolated_tables=sorted(graph.isolated_tables),
    )


@router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a connection and its index",
)
def delete_connection(
    connection_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    connection = _owned_connection(connection_id, db, user)
    invalidate_connection(connection.id)

    # Remove the index explicitly; SQLite does not enforce ON DELETE CASCADE
    # unless foreign keys are switched on per connection.
    for table in db.scalars(
        select(SchemaTable).where(SchemaTable.connection_id == connection.id)
    ):
        db.delete(table)

    db.delete(connection)
    db.add(
        AuditLog(
            user_id=user.id,
            action="connection.delete",
            payload={"connection_id": connection_id},
        )
    )
    db.commit()
