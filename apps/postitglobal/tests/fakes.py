"""A stand-in for the Supabase client: each table answers selects with the rows a test gives
it (filtered by `in_`) and records what the code writes; Storage keeps files in memory."""

from types import SimpleNamespace
from typing import Any


class FakeQuery:
    def __init__(self, db: FakeDB, table: str) -> None:
        self.db, self.table = db, table
        self.write: tuple[str, Any] | None = None
        self.one = False
        self.only: tuple[str, list[Any]] | None = None

    def select(self, *_: Any, **__: Any) -> FakeQuery:
        return self

    def eq(self, *_: Any) -> FakeQuery:
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

    def execute(self) -> SimpleNamespace:
        if self.write:
            self.db.writes.append((self.table, *self.write))
            return SimpleNamespace(data=[self.write[1]])
        rows = self.db.rows.get(self.table, [])
        if self.only:
            column, values = self.only
            rows = [row for row in rows if row.get(column) in values]
        return SimpleNamespace(data=(rows[0] if rows else None) if self.one else rows)


class FakeBucket:
    def __init__(self, storage: FakeStorage, bucket: str) -> None:
        self.storage, self.bucket = storage, bucket

    def download(self, path: str) -> bytes:
        return self.storage.files[(self.bucket, path)]

    def upload(self, path: str, data: bytes, options: dict[str, str] | None = None) -> None:
        self.storage.files[(self.bucket, path)] = data
        self.storage.uploads.append((self.bucket, path, options or {}))

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
