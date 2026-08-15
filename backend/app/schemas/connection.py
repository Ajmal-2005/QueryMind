from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.connection import ConnectionStatus, Dialect


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    dialect: Dialect
    database: str = Field(min_length=1, max_length=255)
    host: str = Field(default="", max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str = Field(default="", max_length=255)
    password: str = Field(default="", max_length=512)

    @model_validator(mode="after")
    def _check_dialect_requirements(self) -> "ConnectionCreate":
        if self.dialect is Dialect.SQLITE:
            # A file path is the whole address; host/port are meaningless.
            self.host = self.host or "localhost"
            self.port = self.port or 0
            return self

        if not self.host:
            raise ValueError("host is required for postgres and mysql")
        if self.port is None:
            self.port = 5432 if self.dialect is Dialect.POSTGRES else 3306
        if not self.username:
            raise ValueError("username is required for postgres and mysql")
        return self


class ConnectionRead(BaseModel):
    """A connection as returned to the client.

    Deliberately has no credentials field of any kind.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    dialect: Dialect
    host: str
    port: int
    database: str
    status: ConnectionStatus
    last_error: str | None
    last_indexed_at: datetime | None
    created_at: datetime


class ConnectionTestResponse(BaseModel):
    ok: bool
    latency_ms: float
    server_version: str | None = None
    error: str | None = None


class IndexResponse(BaseModel):
    connection_id: str
    tables_indexed: int
    columns_indexed: int
    foreign_keys: int
    isolated_tables: int
    embedder: str
    introspection_ms: float
    embedding_ms: float
    total_ms: float
