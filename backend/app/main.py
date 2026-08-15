"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import Base, engine
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("starting", version=__version__, environment=settings.ENVIRONMENT)

    # Alembic owns the schema everywhere except local SQLite development,
    # where create_all keeps the skeleton runnable with no migration step.
    if settings.is_sqlite:
        import app.models  # noqa: F401 - registers models on Base.metadata

        Base.metadata.create_all(bind=engine)
        log.info("sqlite_schema_ready")

    yield

    log.info("shutting_down")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=__version__,
    description=(
        "Natural-language questions in, validated read-only SQL and analytics out."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {
        "name": settings.PROJECT_NAME,
        "version": __version__,
        "docs": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health",
    }
