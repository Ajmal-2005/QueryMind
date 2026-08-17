"""Saved dashboards (F18).

A dashboard is a set of pinned queries that re-run when it is opened. Nothing
is precomputed and nothing is stored but the SQL - a dashboard showing figures
from last Tuesday is worse than no dashboard, and a cache with a five-minute
TTL already covers the cost of several people opening the same board at once.

Refresh is deliberately forgiving at the tile level and strict at the gate
level: one broken tile shows as a broken tile beside five working ones, but
every tile's SQL is re-validated on every refresh. A query that was safe when
pinned is not assumed safe now - the schema may have been re-indexed, and a
column it referenced may be gone.
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.models.audit import AuditLog
from app.models.connection import Connection
from app.models.dashboard import Dashboard, DashboardTile
from app.models.user import User
from app.schemas.analytics import to_analysis_read
from app.schemas.dashboard import (
    DashboardCreate,
    DashboardDetail,
    DashboardRead,
    DashboardRefresh,
    DashboardUpdate,
    TileCreate,
    TileRead,
    TileResult,
)
from app.schemas.query import ResultRead, ValidationRead
from app.services.analytics.analyze import analyze
from app.services.cache.results import run_cached
from app.services.generation import pipeline
from app.services.validation.gates import validate

log = get_logger(__name__)

router = APIRouter()

MAX_TILES = 24


def _owned(dashboard_id: str, db: Session, user: User) -> Dashboard:
    dashboard = db.get(Dashboard, dashboard_id)
    if dashboard is None or dashboard.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dashboard not found"
        )
    return dashboard


def _read(dashboard: Dashboard) -> DashboardRead:
    return DashboardRead(
        id=dashboard.id,
        name=dashboard.name,
        description=dashboard.description,
        layout=dashboard.layout or {},
        tile_count=len(dashboard.tiles),
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
    )


def _tile_read(tile: DashboardTile, connection_names: dict[str, str]) -> TileRead:
    return TileRead(
        id=tile.id,
        title=tile.title,
        connection_id=tile.connection_id,
        connection_name=connection_names.get(tile.connection_id or ""),
        question=tile.question,
        sql=tile.sql,
        chart=tile.chart or {},
        position=tile.position,
        created_at=tile.created_at,
    )


def _connection_names(db: Session, user: User) -> dict[str, str]:
    return dict(
        db.execute(
            select(Connection.id, Connection.name).where(Connection.user_id == user.id)
        ).all()
    )


@router.post(
    "",
    response_model=DashboardRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dashboard",
)
def create_dashboard(
    payload: DashboardCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DashboardRead:
    dashboard = Dashboard(
        user_id=user.id, name=payload.name, description=payload.description, layout={}
    )
    db.add(dashboard)
    db.commit()
    db.refresh(dashboard)
    return _read(dashboard)


@router.get("", response_model=list[DashboardRead], summary="List dashboards")
def list_dashboards(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[DashboardRead]:
    dashboards = db.scalars(
        select(Dashboard)
        .where(Dashboard.user_id == user.id)
        .order_by(Dashboard.updated_at.desc())
    ).all()
    return [_read(d) for d in dashboards]


@router.get("/{dashboard_id}", response_model=DashboardDetail, summary="One dashboard")
def get_dashboard(
    dashboard_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DashboardDetail:
    dashboard = _owned(dashboard_id, db, user)
    names = _connection_names(db, user)
    return DashboardDetail(
        **_read(dashboard).model_dump(),
        tiles=[_tile_read(t, names) for t in dashboard.tiles],
    )


@router.patch(
    "/{dashboard_id}", response_model=DashboardRead, summary="Rename or re-lay-out"
)
def update_dashboard(
    dashboard_id: str,
    payload: DashboardUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DashboardRead:
    dashboard = _owned(dashboard_id, db, user)

    if payload.name is not None:
        dashboard.name = payload.name
    if payload.description is not None:
        dashboard.description = payload.description
    if payload.layout is not None:
        dashboard.layout = payload.layout

    db.commit()
    db.refresh(dashboard)
    return _read(dashboard)


@router.delete(
    "/{dashboard_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a dashboard",
)
def delete_dashboard(
    dashboard_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    dashboard = _owned(dashboard_id, db, user)
    db.delete(dashboard)
    db.add(
        AuditLog(
            user_id=user.id,
            action="dashboard.delete",
            payload={"dashboard_id": dashboard_id, "name": dashboard.name},
        )
    )
    db.commit()


@router.post(
    "/{dashboard_id}/tiles",
    response_model=TileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Pin a query to a dashboard",
)
def add_tile(
    dashboard_id: str,
    payload: TileCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TileRead:
    dashboard = _owned(dashboard_id, db, user)

    if len(dashboard.tiles) >= MAX_TILES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A dashboard holds at most {MAX_TILES} tiles.",
        )

    connection = db.get(Connection, payload.connection_id)
    if connection is None or connection.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found"
        )

    # Validate at pin time as well as at refresh time, so a tile that could
    # never work is refused where the user can still see what they pinned.
    index = pipeline.build_schema_index(db, connection.id)
    validation = validate(
        payload.sql, connection.dialect, index, max_rows=settings.MAX_RESULT_ROWS
    )
    if not validation.ok:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Blocked by the {validation.failure.gate.value} gate: "
            f"{validation.failure.message}",
        )

    next_position = (
        db.scalar(
            select(func.max(DashboardTile.position)).where(
                DashboardTile.dashboard_id == dashboard.id
            )
        )
        or 0
    ) + 1

    tile = DashboardTile(
        dashboard_id=dashboard.id,
        connection_id=connection.id,
        query_id=payload.query_id,
        title=payload.title,
        question=payload.question,
        # Store the validated SQL - the same text the gates approved, with any
        # LIMIT they added, so refresh runs exactly what was pinned.
        sql=validation.sql,
        chart=payload.chart,
        position=next_position,
    )
    db.add(tile)
    dashboard.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(tile)

    return _tile_read(tile, _connection_names(db, user))


@router.delete(
    "/{dashboard_id}/tiles/{tile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a tile",
)
def delete_tile(
    dashboard_id: str,
    tile_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    dashboard = _owned(dashboard_id, db, user)

    tile = db.get(DashboardTile, tile_id)
    if tile is None or tile.dashboard_id != dashboard.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tile not found"
        )

    db.delete(tile)
    dashboard.updated_at = datetime.now(timezone.utc)
    db.commit()


def _refresh_tile(tile: DashboardTile, db: Session, user: User) -> TileResult:
    if tile.connection_id is None:
        return TileResult(
            tile_id=tile.id,
            ok=False,
            error="The database this tile was built against has been removed.",
        )

    connection = db.get(Connection, tile.connection_id)
    if connection is None or connection.user_id != user.id:
        return TileResult(tile_id=tile.id, ok=False, error="Connection not found.")

    index = pipeline.build_schema_index(db, connection.id)
    validation = validate(
        tile.sql, connection.dialect, index, max_rows=settings.MAX_RESULT_ROWS
    )
    if not validation.ok:
        failure = validation.failure
        return TileResult(
            tile_id=tile.id,
            ok=False,
            validation=ValidationRead(
                ok=False,
                sql=tile.sql,
                gate=failure.gate.value,
                message=failure.message,
                retryable=failure.retryable,
            ),
            error=f"Blocked by the {failure.gate.value} gate: {failure.message}",
        )

    result = run_cached(connection, validation.sql)
    if not result.ok:
        return TileResult(tile_id=tile.id, ok=False, error=result.error)

    analysis = analyze(result.columns, result.rows, truncated=result.truncated)
    analysis_read = to_analysis_read(analysis)

    return TileResult(
        tile_id=tile.id,
        ok=True,
        result=ResultRead(
            columns=result.columns,
            rows=result.rows,
            row_count=result.row_count,
            truncated=result.truncated,
            duration_ms=round(result.duration_ms, 1),
            cached=result.cached,
        ),
        analysis=analysis_read,
        chart=analysis_read.chart,
        cached=result.cached,
    )


@router.post(
    "/{dashboard_id}/refresh",
    response_model=DashboardRefresh,
    summary="Re-run every tile",
)
def refresh(
    dashboard_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DashboardRefresh:
    dashboard = _owned(dashboard_id, db, user)
    started = time.perf_counter()

    tiles = [_refresh_tile(tile, db, user) for tile in dashboard.tiles]
    elapsed = (time.perf_counter() - started) * 1000

    log.info(
        "dashboard_refreshed",
        dashboard_id=dashboard.id,
        tiles=len(tiles),
        failed=sum(1 for t in tiles if not t.ok),
        duration_ms=round(elapsed, 1),
    )

    return DashboardRefresh(
        dashboard_id=dashboard.id,
        refreshed_at=datetime.now(timezone.utc),
        tiles=tiles,
        duration_ms=round(elapsed, 1),
    )
