"""Standing up a live, indexed connection for the harness to measure against.

The evaluation runs the *production* pipeline - same retrieval, same gates,
same execution - because a harness that reimplements any of that measures the
reimplementation. So it needs a real application database with a real indexed
connection, which is what this module builds.

Everything lives in a temporary directory and is thrown away. The harness must
never touch a developer's working database: a benchmark that writes 1,034
query rows into the app you are demoing tomorrow is its own kind of bug.
"""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@dataclass
class Bench:
    """A live app database with one indexed target connection."""

    db: Session
    connection: object
    user_id: str
    tables_indexed: int
    embedder: str


@contextmanager
def bench(target_db: Path | None = None) -> Iterator[Bench]:
    """Build a throwaway app database with the demo schema indexed.

    ``target_db`` overrides the target database, so Spider's per-question
    databases can be pointed at once they are downloaded.
    """
    import app.models  # noqa: F401 - registers models on Base.metadata
    from app.core.database import Base
    from app.models.connection import Connection, Dialect
    from app.models.user import User
    from app.services.connection.manager import Credentials, encrypt_credentials
    from app.services.linking.indexer import index_connection

    with tempfile.TemporaryDirectory(prefix="nlq_eval_") as workdir:
        root = Path(workdir)
        app_db = root / "eval_app.db"

        engine = create_engine(
            f"sqlite+pysqlite:///{app_db}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=engine)
        session = sessionmaker(bind=engine)()

        try:
            if target_db is None:
                from scripts.seed_demo_db import seed

                target_db = root / "demo_ecommerce.db"
                seed(target_db)

            user = User(email="harness@evaluation.local", hashed_password="x")
            session.add(user)
            session.flush()

            connection = Connection(
                user_id=user.id,
                name="Benchmark target",
                dialect=Dialect.SQLITE,
                host="localhost",
                port=0,
                database=str(target_db),
                encrypted_credentials=encrypt_credentials(Credentials()),
            )
            session.add(connection)
            session.flush()

            result = index_connection(session, connection)
            session.commit()

            yield Bench(
                db=session,
                connection=connection,
                user_id=user.id,
                tables_indexed=result.tables_indexed,
                embedder=result.embedder,
            )
        finally:
            session.close()
            engine.dispose()


__all__ = ["Bench", "bench"]
