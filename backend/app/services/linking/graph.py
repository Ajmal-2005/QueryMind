"""The foreign-key graph.

Retrieval finds tables that *look* relevant to a question. It routinely
misses the join table sitting between two of them, which makes the generated
SQL unjoinable. Expanding the retrieved set one hop along foreign keys is the
fix, and this is the structure that makes that cheap.
"""

from collections import deque
from dataclasses import dataclass, field

from app.services.introspect.introspector import ForeignKeyInfo, TableInfo


@dataclass
class ForeignKeyGraph:
    """Undirected adjacency over tables, plus the edges that justify it.

    Undirected because a join is usable in both directions: reaching
    ``customers`` from ``orders`` matters as much as the reverse.
    """

    adjacency: dict[str, set[str]] = field(default_factory=dict)
    edges: list[ForeignKeyInfo] = field(default_factory=list)

    @classmethod
    def from_tables(cls, tables: list[TableInfo]) -> "ForeignKeyGraph":
        graph = cls()
        for table in tables:
            graph.adjacency.setdefault(table.name, set())

        for table in tables:
            for fk in table.foreign_keys:
                # Skip edges pointing outside the introspected set.
                if fk.to_table not in graph.adjacency:
                    continue
                graph.adjacency[fk.from_table].add(fk.to_table)
                graph.adjacency[fk.to_table].add(fk.from_table)
                graph.edges.append(fk)

        return graph

    def neighbors(self, table: str) -> set[str]:
        return set(self.adjacency.get(table, set()))

    def expand(self, tables: set[str], hops: int = 1) -> set[str]:
        """Grow a table set outward along foreign keys.

        One hop is the proposal's default: it reliably picks up junction
        tables without dragging in the whole schema.
        """
        if hops <= 0:
            return set(tables)

        seen = set(tables)
        frontier = deque((t, 0) for t in tables)

        while frontier:
            current, depth = frontier.popleft()
            if depth >= hops:
                continue
            for neighbor in self.neighbors(current):
                if neighbor not in seen:
                    seen.add(neighbor)
                    frontier.append((neighbor, depth + 1))

        return seen

    def join_path(self, start: str, end: str) -> list[str] | None:
        """Shortest sequence of tables joining ``start`` to ``end``."""
        if start not in self.adjacency or end not in self.adjacency:
            return None
        if start == end:
            return [start]

        previous: dict[str, str | None] = {start: None}
        queue = deque([start])

        while queue:
            current = queue.popleft()
            for neighbor in sorted(self.neighbors(current)):
                if neighbor in previous:
                    continue
                previous[neighbor] = current
                if neighbor == end:
                    path = [end]
                    while (parent := previous[path[-1]]) is not None:
                        path.append(parent)
                    return list(reversed(path))
                queue.append(neighbor)

        return None

    @property
    def isolated_tables(self) -> set[str]:
        """Tables with no foreign keys in either direction.

        Often lookup or audit tables — useful to surface, because they are
        also where undocumented join conventions hide.
        """
        return {t for t, neighbors in self.adjacency.items() if not neighbors}
