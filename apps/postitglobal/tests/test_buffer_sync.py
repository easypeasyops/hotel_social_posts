"""Syncing Buffer's outcome back: a scheduled post that Buffer sent marks its draft
published, one Buffer couldn't send marks it failed, and one still queued is left alone."""

import json
import logging
from typing import Any

import httpx
import pytest
import respx

from app.publishing.buffer import BUFFER_API_URL, sync_scheduled_posts
from tests.fakes import FakeDB


def _db(*logs: dict[str, Any]) -> FakeDB:
    return FakeDB(
        publish_log=[
            {"id": f"log-{log['draft_id']}", "status": "scheduled", **log} for log in logs
        ],
        content_drafts=[{"id": log["draft_id"], "status": "scheduled"} for log in logs],
    )


def _post(status: str, **fields: Any) -> dict[str, Any]:
    return {"data": {"post": {"status": status, "sentAt": None, "error": None, **fields}}}


def _buffer_answers(posts: dict[str, dict[str, Any]]) -> respx.Route:
    """Buffer answers each post query with the body given for that post's ID."""

    def answer(request: httpx.Request) -> httpx.Response:
        post_id = json.loads(request.content)["variables"]["input"]["id"]
        return httpx.Response(200, json=posts[post_id])

    return respx.post(BUFFER_API_URL).mock(side_effect=answer)


def _status(db: FakeDB, table: str, row_id: str) -> dict[str, Any]:
    return next(row for row in db.rows[table] if row["id"] == row_id)


@respx.mock
def test_a_sent_post_marks_its_draft_published() -> None:
    route = _buffer_answers({"post-1": _post("sent", sentAt="2026-11-04T09:00:00.000Z")})
    db = _db({"draft_id": "d1", "buffer_update_id": "post-1"})

    sync_scheduled_posts(db)  # type: ignore[arg-type]

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-buffer-token"
    assert "post(input: $input)" in json.loads(request.content)["query"]
    assert _status(db, "publish_log", "log-d1") == {
        "id": "log-d1",
        "draft_id": "d1",
        "buffer_update_id": "post-1",
        "status": "published",
        "published_at": "2026-11-04T09:00:00.000Z",
    }
    assert _status(db, "content_drafts", "d1")["status"] == "published"


@respx.mock
def test_a_post_buffer_could_not_send_marks_its_draft_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _buffer_answers({"post-1": _post("error", error={"message": "Channel disconnected"})})
    db = _db({"draft_id": "d1", "buffer_update_id": "post-1"})

    with caplog.at_level(logging.WARNING):
        sync_scheduled_posts(db)  # type: ignore[arg-type]

    assert _status(db, "publish_log", "log-d1")["status"] == "failed"
    assert _status(db, "content_drafts", "d1")["status"] == "failed"
    assert "Channel disconnected" in caplog.text


@pytest.mark.parametrize("status", ["scheduled", "sending", "needs_approval", "draft"])
@respx.mock
def test_a_post_not_yet_sent_is_left_scheduled(status: str) -> None:
    _buffer_answers({"post-1": _post(status)})
    db = _db({"draft_id": "d1", "buffer_update_id": "post-1"})

    sync_scheduled_posts(db)  # type: ignore[arg-type]

    assert db.writes == []


@respx.mock
def test_a_post_buffer_refuses_to_show_does_not_stop_the_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A post deleted in Buffer's own app, say: logged, left scheduled, the rest still synced.
    _buffer_answers(
        {
            "gone": {"data": None, "errors": [{"message": "Post not found",
                                               "extensions": {"code": "NOT_FOUND"}}]},
            "post-2": _post("sent", sentAt="2026-11-04T10:00:00.000Z"),
        }
    )  # fmt: skip
    db = _db(
        {"draft_id": "d1", "buffer_update_id": "gone"},
        {"draft_id": "d2", "buffer_update_id": "post-2"},
    )

    with caplog.at_level(logging.WARNING):
        sync_scheduled_posts(db)  # type: ignore[arg-type]

    assert _status(db, "content_drafts", "d1")["status"] == "scheduled"
    assert _status(db, "content_drafts", "d2")["status"] == "published"
    assert "NOT_FOUND: Post not found" in caplog.text


@respx.mock
def test_the_rate_limit_stops_the_sync_for_the_next_run() -> None:
    respx.post(BUFFER_API_URL).mock(return_value=httpx.Response(429))
    db = _db({"draft_id": "d1", "buffer_update_id": "post-1"})
    with pytest.raises(httpx.HTTPStatusError):
        sync_scheduled_posts(db)  # type: ignore[arg-type]
    assert db.writes == []
