"""A stand-in for the Supabase client: each table answers selects with the rows a test gives
it (filtered by `eq` and `in_` on columns the rows have) and records what the code writes;
an `update` changes the matching rows. Storage keeps files in memory."""

import builtins
from types import SimpleNamespace
from typing import Any


class FakeQuery:
    def __init__(self, db: FakeDB, table: str) -> None:
        self.db, self.table = db, table
        self.write: tuple[str, Any] | None = None
        self.one = False
        self.only: tuple[str, list[Any]] | None = None
        self.equal: list[tuple[str, Any]] = []

    def select(self, *_: Any, **__: Any) -> FakeQuery:
        return self

    def eq(self, column: str, value: Any) -> FakeQuery:
        self.equal.append((column, value))
        return self

    def in_(self, column: str, values: list[Any]) -> FakeQuery:
        self.only = (column, values)
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

    def update(self, row: dict[str, Any]) -> FakeQuery:
        self.write = ("update", row)
        return self

    def delete(self) -> FakeQuery:
        self.write = ("delete", {})
        return self

    def _matching(self) -> list[dict[str, Any]]:
        rows = self.db.rows.get(self.table, [])
        # A filter on a column the test's rows don't have is ignored, as before eq filtered.
        rows = [r for r in rows if all(r.get(c, v) == v for c, v in self.equal)]
        if self.only:
            column, values = self.only
            rows = [row for row in rows if row.get(column) in values]
        return rows

    def execute(self) -> SimpleNamespace:
        if self.write and self.write[0] == "delete":
            matching = self._matching()
            self.db.rows[self.table] = [
                r for r in self.db.rows.get(self.table, []) if r not in matching
            ]
            self.db.writes.append((self.table, "delete", {}))
            return SimpleNamespace(data=matching)
        if self.write and self.write[0] == "update":
            matching = self._matching()
            for row in matching:
                row.update(self.write[1])
            self.db.writes.append((self.table, *self.write))
            return SimpleNamespace(data=[dict(r) for r in matching])
        if self.write:
            self.db.writes.append((self.table, *self.write))
            return SimpleNamespace(data=[self.write[1]])
        rows = self._matching()
        return SimpleNamespace(data=(rows[0] if rows else None) if self.one else rows)


class FakeBucket:
    def __init__(self, storage: FakeStorage, bucket: str) -> None:
        self.storage, self.bucket = storage, bucket

    def download(self, path: str) -> bytes:
        return self.storage.files[(self.bucket, path)]

    def upload(self, path: str, data: bytes, options: dict[str, str] | None = None) -> None:
        self.storage.files[(self.bucket, path)] = data
        self.storage.uploads.append((self.bucket, path, options or {}))

    def list(self, prefix: str) -> builtins.list[dict[str, str]]:
        start = f"{prefix}/"
        return [
            {"name": path[len(start) :]}
            for bucket, path in self.storage.files
            if bucket == self.bucket and path.startswith(start)
        ]

    def remove(self, paths: builtins.list[str]) -> None:
        for path in paths:
            self.storage.files.pop((self.bucket, path), None)

    def get_public_url(self, path: str) -> str:
        return f"https://supabase.invalid/storage/v1/object/public/{self.bucket}/{path}"


class FakeStorage:
    def __init__(self) -> None:
        self.files: dict[tuple[str, str], bytes] = {}
        self.uploads: list[tuple[str, str, dict[str, str]]] = []

    def from_(self, bucket: str) -> FakeBucket:
        return FakeBucket(self, bucket)


class FakeDB:
    def __init__(self, **rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.writes: list[tuple[str, str, dict[str, Any]]] = []
        self.storage = FakeStorage()

    def table(self, name: str) -> FakeQuery:
        return FakeQuery(self, name)

    def written(self, table: str) -> list[dict[str, Any]]:
        return [row for name, _, row in self.writes if name == table]
