"""Rebuild the demo account, connection, and sample learning data.

Written after a live failure worth recording: editing `.env` changed
`CREDENTIAL_ENCRYPTION_KEY`, and every stored connection immediately became
undecryptable — the app returned 500 on any query. That is correct behaviour
(credentials are encrypted at rest, and a changed key *should* make them
unreadable) but it leaves the demo dead with no obvious way back.

This puts it back in one command:

    python -m scripts.reset_demo_state

Idempotent. Safe to run immediately before a demo.
"""

import sys
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.connection import Connection, Dialect
from app.models.dashboard import Dashboard, DashboardTile
from app.models.learning import GlossaryTerm
from app.models.user import User
from app.services.connection.manager import Credentials, encrypt_credentials
from app.services.learning.corrections import record_correction
from app.services.linking.indexer import index_connection

DEMO_EMAIL = "demo4@example.com"
DEMO_PASSWORD = "correct-horse-battery"

REGION_SQL = "SELECT region, COUNT(*) AS n FROM customers GROUP BY region"
REVENUE_SQL = (
    "SELECT strftime('%Y-%m', created_at) AS month, SUM(total_amount) AS revenue "
    "FROM orders GROUP BY month ORDER BY month"
)


def main() -> int:
    target = Path(__file__).resolve().parent.parent / "demo_ecommerce.db"
    if not target.exists():
        print(f"Demo database missing at {target}")
        print("Run:  python -m scripts.seed_demo_db")
        return 1

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                hashed_password=hash_password(DEMO_PASSWORD),
                full_name="Demo User",
            )
            db.add(user)
            db.flush()
            print(f"created user   {DEMO_EMAIL}")
        else:
            # The password is reset too: a demo account nobody can log into is
            # the same problem this script exists to solve.
            user.hashed_password = hash_password(DEMO_PASSWORD)
            print(f"reset password {DEMO_EMAIL}")

        # Any existing connection may hold credentials encrypted under a key
        # that no longer exists. Replacing is the only recovery.
        for stale in db.scalars(
            select(Connection).where(Connection.user_id == user.id)
        ).all():
            db.delete(stale)
        db.flush()

        connection = Connection(
            user_id=user.id,
            name="Demo e-commerce",
            dialect=Dialect.SQLITE,
            host="localhost",
            port=0,
            database=str(target),
            encrypted_credentials=encrypt_credentials(Credentials()),
        )
        db.add(connection)
        db.flush()

        result = index_connection(db, connection)
        db.commit()
        print(
            f"indexed        {result.tables_indexed} tables, "
            f"{result.columns_indexed} columns ({result.embedder})"
        )

        db.add(
            GlossaryTerm(
                connection_id=connection.id,
                user_id=user.id,
                term="active customer",
                definition="a customer who has placed at least one order",
                sql_expression=(
                    "EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)"
                ),
            )
        )
        db.commit()
        print("glossary       1 term")

        record_correction(
            db,
            user_id=user.id,
            connection_id=connection.id,
            question="customers per region",
            corrected_sql=REGION_SQL,
            original_sql="SELECT * FROM customers",
            note="Needed a GROUP BY, not every row.",
        )
        print("corrections    1")

        dashboard = Dashboard(user_id=user.id, name="Sales overview", layout={})
        db.add(dashboard)
        db.flush()
        db.add(
            DashboardTile(
                dashboard_id=dashboard.id,
                connection_id=connection.id,
                title="Revenue by month",
                question="What is total revenue by month?",
                sql=REVENUE_SQL,
                position=1,
            )
        )
        db.commit()
        print("dashboard      1 with 1 tile")

        print(f"\nReady. Sign in as {DEMO_EMAIL} / {DEMO_PASSWORD}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
