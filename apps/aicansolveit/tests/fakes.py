"""A stand-in for the Supabase client's query builder: each table answers selects with the
rows a test gives it and records what the code writes."""

from types import SimpleNamespace
from typing import Any


class FakeQuery:
    def __init__(self, db: FakeDB, table: str) -> None:
        self.db, self.table = db, table
        self.write: tuple[str, Any] | None = None
        self.one = False

    def select(self, *_: Any, **__: Any) -> FakeQuery:
        return self

    def eq(self, *_: Any) -> FakeQuery:
        return self

    def order(self, *_: Any, **__: Any) -> FakeQuery:
        return self

    def limit(self, *_: Any) -> FakeQuery:
        return self

    def single(self) -> FakeQuery:
        self.one = True
        return self

    def insert(self, row: dict[str, Any]) -> FakeQuery:
        self.write = ("insert", row)
        return self

    def upsert(self, row: dict[str, Any], **_: Any) -> FakeQuery:
        self.write = ("upsert", row)
        return self

    def execute(self) -> SimpleNamespace:
        if self.write:
            self.db.writes.append((self.table, *self.write))
            return SimpleNamespace(data=[self.write[1]])
        rows = self.db.rows.get(self.table, [])
        return SimpleNamespace(data=(rows[0] if rows else None) if self.one else rows)


class FakeDB:
    def __init__(self, **rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.writes: list[tuple[str, str, dict[str, Any]]] = []

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def written(self, table: str) -> list[dict[str, Any]]:
        return [row for name, _, row in self.writes if name == table]
