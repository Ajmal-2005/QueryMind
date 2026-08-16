"""Token and cost tracking (F29), and the audit trail.

Appendix B lists `GET /api/v1/usage`. Every ingredient already existed — the
`queries` table records `tokens_used` per question and `audit_log` records
every security-relevant action — but nothing read them back, so nobody could
answer "what has this cost?" without opening the database.

Costs are computed from a published price table rather than stored per row.
Prices change, and a stored figure would silently become wrong; a rate applied
at read time is at least wrong in a way you can see and correct. The rates in
force are returned with every response for exactly that reason.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.audit import AuditLog
from app.models.query import Query as QueryRow
from app.models.query import QueryStatus
from app.models.user import User, UserRole
from app.schemas.usage import (
    AuditEntry,
    ModelRate,
    UsageByUser,
    UsageResponse,
    UsageTotals,
)

router = APIRouter()

# USD per million tokens. Published rates for the models this system calls;
# update alongside any model change. Returned with every response so a figure
# can always be traced to the rate that produced it.
RATES: dict[str, tuple[float, float]] = {
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-5": (15.00, 75.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    # The offline providers cost nothing, and saying so explicitly keeps them
    # out of the "unknown model" bucket.
    "stub": (0.0, 0.0),
    "template": (0.0, 0.0),
}

DEFAULT_MODEL = "claude-sonnet-5"

# `queries.tokens_used` is a single total — the schema predates the split, and
# a migration to separate columns is not worth it for an estimate. Generation
# prompts are heavily input-weighted: a schema subgraph in, one statement out.
ASSUMED_INPUT_SHARE = 0.85


def estimate_cost(tokens: int, model: str = DEFAULT_MODEL) -> float:
    """Estimated USD for a token count.

    Deliberately named an estimate. It splits a combined token count by an
    assumed ratio, so it is indicative of spend, not an invoice.
    """
    input_rate, output_rate = RATES.get(model, RATES[DEFAULT_MODEL])
    input_tokens = tokens * ASSUMED_INPUT_SHARE
    output_tokens = tokens - input_tokens
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


@router.get("", response_model=UsageResponse, summary="Token and cost tracking")
def usage(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UsageResponse:
    """This user's spend, or everyone's for an admin.

    Scoped by role rather than by a flag: a viewer or analyst seeing another
    user's question volume is a privacy leak, not a reporting feature.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    is_admin = user.role is UserRole.ADMIN

    scope = [QueryRow.created_at >= since]
    if not is_admin:
        scope.append(QueryRow.user_id == user.id)

    rows = db.execute(
        select(
            func.count(QueryRow.id),
            func.coalesce(func.sum(QueryRow.tokens_used), 0),
            func.coalesce(func.avg(QueryRow.latency_ms), 0.0),
        ).where(*scope)
    ).one()
    total_queries, total_tokens, mean_latency = rows

    executed = db.scalar(
        select(func.count(QueryRow.id)).where(
            *scope, QueryRow.status == QueryStatus.EXECUTED
        )
    )
    rejected = db.scalar(
        select(func.count(QueryRow.id)).where(
            *scope, QueryRow.status == QueryStatus.REJECTED
        )
    )
    corrected = db.scalar(
        select(func.count(QueryRow.id)).where(*scope, QueryRow.correction_attempts > 0)
    )

    per_user: list[UsageByUser] = []
    if is_admin:
        breakdown = db.execute(
            select(
                QueryRow.user_id,
                User.email,
                func.count(QueryRow.id),
                func.coalesce(func.sum(QueryRow.tokens_used), 0),
            )
            .join(User, User.id == QueryRow.user_id)
            .where(QueryRow.created_at >= since)
            .group_by(QueryRow.user_id, User.email)
            .order_by(func.coalesce(func.sum(QueryRow.tokens_used), 0).desc())
        ).all()

        per_user = [
            UsageByUser(
                user_id=user_id,
                email=email,
                queries=count,
                tokens=tokens,
                estimated_cost_usd=round(estimate_cost(tokens), 4),
            )
            for user_id, email, count, tokens in breakdown
        ]

    return UsageResponse(
        window_days=days,
        scope="all users" if is_admin else "you",
        totals=UsageTotals(
            queries=total_queries,
            executed=executed or 0,
            rejected=rejected or 0,
            recovered_by_correction=corrected or 0,
            tokens=int(total_tokens),
            estimated_cost_usd=round(estimate_cost(int(total_tokens)), 4),
            mean_latency_ms=round(float(mean_latency or 0.0), 1),
        ),
        by_user=per_user,
        rates=[
            ModelRate(model=model, input_per_mtok=rate[0], output_per_mtok=rate[1])
            for model, rate in sorted(RATES.items())
        ],
        cost_note=(
            "Estimated. `queries.tokens_used` is a combined total, split "
            f"{ASSUMED_INPUT_SHARE:.0%}/{1 - ASSUMED_INPUT_SHARE:.0%} "
            "input/output by assumption. Indicative of spend, not an invoice."
        ),
    )


@router.get(
    "/audit",
    response_model=list[AuditEntry],
    summary="Audit trail (admin only)",
)
def audit(
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
    # The audit log records who did what across every user. Reading it is an
    # administrative act, and this is the first endpoint in the system to say
    # so — `require_roles` has existed since Phase 0 and was never wired up.
    user: User = Depends(require_roles(UserRole.ADMIN)),
) -> list[AuditEntry]:
    rows = db.scalars(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    ).all()

    return [
        AuditEntry(
            id=row.id,
            user_id=row.user_id,
            action=row.action,
            payload=row.payload or {},
            created_at=row.created_at,
        )
        for row in rows
    ]
