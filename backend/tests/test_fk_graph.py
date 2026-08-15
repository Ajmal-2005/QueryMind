"""The foreign-key graph and one-hop expansion."""

from app.models.connection import Dialect
from app.services.introspect.introspector import introspect
from app.services.linking.graph import ForeignKeyGraph


def _graph(engine) -> ForeignKeyGraph:
    return ForeignKeyGraph.from_tables(introspect(engine, Dialect.SQLITE).tables)


def test_every_table_appears_as_a_node(demo_engine) -> None:
    graph = _graph(demo_engine)
    assert "orders" in graph.adjacency
    assert "cust_ref_log_v2" in graph.adjacency


def test_edges_are_traversable_in_both_directions(demo_engine) -> None:
    graph = _graph(demo_engine)

    assert "customers" in graph.neighbors("orders")
    assert "orders" in graph.neighbors("customers")


def test_expansion_pulls_in_the_junction_table(demo_engine) -> None:
    # The whole reason FK expansion exists: retrieval finds products and
    # suppliers but misses the table that actually joins them.
    graph = _graph(demo_engine)
    expanded = graph.expand({"products", "suppliers"}, hops=1)

    assert "product_suppliers" in expanded


def test_expansion_reaches_customers_from_order_items(demo_engine) -> None:
    graph = _graph(demo_engine)

    one_hop = graph.expand({"order_items"}, hops=1)
    assert "orders" in one_hop
    assert "customers" not in one_hop

    two_hops = graph.expand({"order_items"}, hops=2)
    assert "customers" in two_hops


def test_zero_hops_returns_the_input_unchanged(demo_engine) -> None:
    graph = _graph(demo_engine)
    assert graph.expand({"orders"}, hops=0) == {"orders"}


def test_expansion_never_drops_the_original_tables(demo_engine) -> None:
    graph = _graph(demo_engine)
    assert {"products", "suppliers"} <= graph.expand({"products", "suppliers"})


def test_expansion_terminates_on_a_self_referencing_table(demo_engine) -> None:
    # categories.parent_id -> categories would loop without a visited set.
    graph = _graph(demo_engine)
    assert "categories" in graph.expand({"categories"}, hops=3)


def test_isolated_tables_are_reported(demo_engine) -> None:
    graph = _graph(demo_engine)
    assert "cust_ref_log_v2" in graph.isolated_tables
    assert "orders" not in graph.isolated_tables


def test_join_path_between_distant_tables(demo_engine) -> None:
    graph = _graph(demo_engine)
    path = graph.join_path("order_items", "customers")

    assert path == ["order_items", "orders", "customers"]


def test_join_path_to_self_is_the_table_alone(demo_engine) -> None:
    assert _graph(demo_engine).join_path("orders", "orders") == ["orders"]


def test_join_path_is_none_when_unreachable(demo_engine) -> None:
    assert _graph(demo_engine).join_path("orders", "cust_ref_log_v2") is None


def test_join_path_is_none_for_an_unknown_table(demo_engine) -> None:
    assert _graph(demo_engine).join_path("orders", "no_such_table") is None


def test_graph_ignores_edges_pointing_outside_the_snapshot() -> None:
    from app.services.introspect.introspector import ForeignKeyInfo, TableInfo

    tables = [
        TableInfo(
            name="orders",
            foreign_keys=[
                ForeignKeyInfo("orders", ["archive_id"], "archived_orders", ["id"])
            ],
        )
    ]
    graph = ForeignKeyGraph.from_tables(tables)

    assert graph.neighbors("orders") == set()
    assert "archived_orders" not in graph.adjacency
