from pydantic import BaseModel, ConfigDict


class ColumnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    column_name: str
    data_type: str
    is_nullable: bool
    is_pk: bool
    is_indexed: bool
    fk_target: str | None
    sample_values: list | None


class TableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    table_name: str
    schema_name: str | None
    description: str
    row_estimate: int | None
    columns: list[ColumnRead]


class SchemaGraphEdge(BaseModel):
    from_table: str
    to_table: str


class SchemaResponse(BaseModel):
    """The indexed schema graph for one connection."""

    connection_id: str
    table_count: int
    column_count: int
    tables: list[TableRead]
    edges: list[SchemaGraphEdge]
    isolated_tables: list[str]
