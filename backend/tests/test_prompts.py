"""Prompt construction - what actually reaches the model."""

import pytest

from app.models.connection import Dialect
from app.services.generation import prompts
from app.services.generation.intent import analyze
from app.services.linking.indexer import index_connection
from app.services.linking.retriever import retrieve


@pytest.fixture
def indexed(db, demo_connection):
    index_connection(db, demo_connection)
    return demo_connection


def _build(db, connection, question: str, top_k: int = 6, hops: int = 1, **kwargs):
    intent = analyze(question)
    retrieval = retrieve(
        db, connection.id, intent.resolved_question, top_k=top_k, hops=hops
    )
    return prompts.build(
        db=db,
        connection_id=connection.id,
        question=question,
        intent=intent,
        retrieval=retrieval,
        dialect=Dialect.SQLITE,
        **kwargs,
    )


def test_schema_renders_as_ddl(db, indexed) -> None:
    schema = prompts.render_schema(db, indexed.id, ["orders"])

    assert "CREATE TABLE orders (" in schema
    assert "customer_id INTEGER" in schema
    assert schema.rstrip().endswith("rows")


def test_primary_and_foreign_keys_are_rendered(db, indexed) -> None:
    schema = prompts.render_schema(db, indexed.id, ["orders"])

    assert "PRIMARY KEY" in schema
    assert "REFERENCES customers(id)" in schema


def test_low_cardinality_values_reach_the_prompt(db, indexed) -> None:
    # Without these the model has to guess that status is 'completed'.
    schema = prompts.render_schema(db, indexed.id, ["orders"])
    assert "values:" in schema
    assert "completed" in schema


def test_high_cardinality_data_does_not_reach_the_prompt(db, indexed) -> None:
    schema = prompts.render_schema(db, indexed.id, ["customers"])
    assert "customer0001@example.com" not in schema


def test_schema_order_follows_retrieval_order(db, indexed) -> None:
    schema = prompts.render_schema(db, indexed.id, ["products", "orders"])
    assert schema.index("CREATE TABLE products") < schema.index("CREATE TABLE orders")


def test_unretrieved_tables_are_absent(db, indexed) -> None:
    # The whole point of schema linking: a 400-table schema must not be sent.
    # The demo schema has 8 tables, so the default top_k of 6 excludes little -
    # a tighter budget is what makes the exclusion observable here.
    prompt = _build(db, indexed, "How many customers do we have?", top_k=2, hops=0)

    assert "CREATE TABLE customers" in prompt.user
    assert "CREATE TABLE cust_ref_log_v2" not in prompt.user
    assert "CREATE TABLE suppliers" not in prompt.user


def test_empty_table_list_renders_a_note_not_a_crash(db, indexed) -> None:
    assert "no tables matched" in prompts.render_schema(db, indexed.id, [])


def test_dialect_rules_are_included(db, indexed) -> None:
    prompt = _build(db, indexed, "revenue by month")
    assert "SQLite" in prompt.user
    assert "strftime" in prompt.user


def test_postgres_and_sqlite_rules_differ(db, indexed) -> None:
    intent = analyze("revenue by month")
    retrieval = retrieve(db, indexed.id, intent.resolved_question)

    postgres = prompts.build(
        db=db,
        connection_id=indexed.id,
        question="revenue by month",
        intent=intent,
        retrieval=retrieval,
        dialect=Dialect.POSTGRES,
    )
    assert "DATE_TRUNC" in postgres.user
    assert "strftime" not in postgres.user


def test_join_paths_are_stated_explicitly(db, indexed) -> None:
    prompt = _build(db, indexed, "revenue by product category")
    assert "Valid join paths" in prompt.user


def test_relative_dates_are_spelled_out_in_the_prompt(db, indexed) -> None:
    prompt = _build(db, indexed, "revenue last quarter")
    assert "previous complete calendar quarter" in prompt.user


def test_explicit_limit_is_passed_through(db, indexed) -> None:
    prompt = _build(db, indexed, "top 3 products by price")
    assert "LIMIT 3" in prompt.user


def test_system_prompt_forbids_writes(db, indexed) -> None:
    prompt = _build(db, indexed, "How many orders?")
    for keyword in ("INSERT", "UPDATE", "DELETE", "DROP"):
        assert keyword in prompt.system


def test_few_shot_examples_are_included(db, indexed) -> None:
    prompt = _build(
        db,
        indexed,
        "How many customers?",
        examples=[("How many orders?", "SELECT COUNT(*) FROM orders")],
    )
    assert "SELECT COUNT(*) FROM orders" in prompt.user


def test_error_feedback_builds_a_repair_prompt(db, indexed) -> None:
    # The phase 3 self-correction loop reuses this builder.
    prompt = _build(
        db,
        indexed,
        "How many customers?",
        previous_sql="SELECT COUNT(*) FROM custmers",
        error_feedback="no such table: custmers",
    )
    assert "previous attempt failed" in prompt.user
    assert "no such table: custmers" in prompt.user


def test_prompt_reports_its_table_set(db, indexed) -> None:
    prompt = _build(db, indexed, "How many customers?")
    assert "customers" in prompt.table_names
    assert prompt.approx_tokens > 0
