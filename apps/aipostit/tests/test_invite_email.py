"""An operator sends a staff invite from the hotel's dashboard page: it's recorded in
staff_invites for one address, and emailed (in Turkish, through the SMTP account in the
settings) where SMTP is set up. Either way the page shows its link."""

from email.message import EmailMessage
from html import unescape
from types import SimpleNamespace
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import mail
from app.auth import signup
from app.auth.dependencies import get_current_user, require_operator
from app.auth.upload_tokens import read_recorded_invite, read_staff_invite
from app.database import get_supabase
from app.main import create_app
from tests.fakes import FakeDB
from tests.test_staff_signup import (
    TOKENS,
    FakeAdmin,
    store,  # noqa: F401 (the fixture)
)

HOTEL = {"id": "hotel-1", "name": "Ege Konak", "slug": "ege-konak"}


class FakeSMTP:
    sent: list[EmailMessage] = []
    calls: list[Any] = []
    fail = False

    def __init__(self, host: str, port: int, timeout: float) -> None:
        if FakeSMTP.fail:
            raise OSError("connection refused")
        FakeSMTP.calls.append(("connect", host, port))

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def starttls(self, context: object) -> None:
        FakeSMTP.calls.append("starttls")

    def login(self, username: str, password: str) -> None:
        FakeSMTP.calls.append(("login", username, password))

    def send_message(self, message: EmailMessage) -> None:
        FakeSMTP.sent.append(message)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.sent, FakeSMTP.calls, FakeSMTP.fail = [], [], False
    monkeypatch.setattr(mail.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setenv("SMTP_USERNAME", "aipostit@gmail.test")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    return FakeSMTP


def operator(db: FakeDB) -> TestClient:
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: SimpleNamespace(email="op@example.com")
    app.dependency_overrides[get_supabase] = lambda: db
    return TestClient(app, follow_redirects=False)


def send(db: FakeDB | None = None, **form: str) -> Any:
    return operator(db or FakeDB(hotels=[HOTEL])).post(
        "/dashboard/hotels/hotel-1/staff-invite",
        data={"email": "New.Staff@Example.com", "role": "content_creator", **form},
    )


def page_link(page: Any) -> str:
    return unescape(page.text.split('id="staff-invite-link" data-copy="', 1)[1].split('"')[0])


def test_an_invite_is_recorded_and_emailed(smtp: type[FakeSMTP]) -> None:
    db = FakeDB(hotels=[HOTEL])
    response = send(db, valid_days="10")

    assert response.status_code == 200
    assert "Invite sent to new.staff@example.com." in response.text
    row = db.written("staff_invites")[0]
    assert {k: row[k] for k in ("hotel_id", "role", "email", "valid_days", "invited_by_email")} == {
        "hotel_id": "hotel-1",
        "role": "content_creator",
        "email": "new.staff@example.com",
        "valid_days": 10,
        "invited_by_email": "op@example.com",
    }
    sent = db.written("staff_invites")[1]
    assert sent["send_count"] == 1 and sent["last_sent_at"] is not None

    assert smtp.calls == [("connect", "smtp.gmail.com", 587), "starttls",
                          ("login", "aipostit@gmail.test", "app-password")]  # fmt: skip
    [message] = smtp.sent
    assert (message["From"], message["To"]) == ("aipostit@gmail.test", "new.staff@example.com")
    assert message["Subject"] == "Ege Konak ekibine davetlisiniz"
    body = message.get_content()
    assert "içerik üreticisi olarak davet edildiniz" in body and "(10 gün geçerli)" in body
    invite = unquote(body.split("/signup#invite=", 1)[1].split()[0])
    assert read_recorded_invite(invite) == ("hotel-1", row["id"])
    assert read_staff_invite(invite) is None  # no older-purpose token
    assert page_link(response).endswith(f"/signup#invite={body.split('#invite=')[1].split()[0]}")


@pytest.mark.usefixtures("store")
def test_the_emailed_link_signs_up(smtp: type[FakeSMTP], monkeypatch: pytest.MonkeyPatch) -> None:
    db = FakeDB(hotels=[HOTEL])
    invite = unquote(page_link(send(db)).split("#invite=")[1])
    db.rows["staff_invites"] = [
        {**db.written("staff_invites")[0], "accepted_at": None, "revoked_at": None}
    ]
    db.auth = SimpleNamespace(admin=FakeAdmin())  # type: ignore[attr-defined]
    monkeypatch.setattr(signup, "get_supabase", lambda: db)
    sign_in = SimpleNamespace(
        sign_in_with_password=lambda credentials: SimpleNamespace(session=SimpleNamespace(**TOKENS))
    )
    monkeypatch.setattr(signup, "get_supabase_anon", lambda: SimpleNamespace(auth=sign_in))
    form = {"invite": invite, "email": "new.staff@example.com", "password": "ege-konak-2026",
            "password_confirmation": "ege-konak-2026"}  # fmt: skip

    response = TestClient(create_app(), follow_redirects=False).post("/signup", data=form)
    assert (response.status_code, response.headers["location"]) == (303, "/hotel")
    assert db.written("hotel_members")[0]["role"] == "content_creator"


def test_a_failed_send_records_the_invite_as_not_sent(smtp: type[FakeSMTP]) -> None:
    smtp.fail = True
    db = FakeDB(hotels=[HOTEL])
    response = send(db)

    assert response.status_code == 200
    assert "Email not sent" in response.text
    assert read_recorded_invite(unquote(page_link(response).split("#invite=")[1]))
    assert [w[1] for w in db.writes] == ["insert"]  # no last_sent_at


def test_a_sent_email_whose_record_fails_still_reads_sent(smtp: type[FakeSMTP]) -> None:
    class SendNotRecorded(FakeDB):
        def table(self, name: str) -> Any:
            query = super().table(name)
            if self.writes:  # the insert went in; the update after the send fails
                query.update = self.fail  # type: ignore[method-assign]
            return query

        def fail(self, row: dict[str, Any]) -> Any:
            raise RuntimeError("timeout")

    db = SendNotRecorded(hotels=[HOTEL])
    response = send(db)

    assert response.status_code == 200
    assert "Invite sent to new.staff@example.com." in response.text
    assert len(smtp.sent) == 1
    assert [w[1] for w in db.writes] == ["insert"]


def test_without_smtp_the_invite_is_recorded_and_its_link_shown() -> None:
    db = FakeDB(hotels=[HOTEL])
    response = send(db)

    assert response.status_code == 200
    assert (
        "Email not sent: copy the link to send it to new.staff@example.com yourself."
        in response.text
    )
    assert len(db.written("staff_invites")) == 1
    # The link is on its copy button, not shown as text
    assert page_link(response).startswith("http://testserver/signup#invite=")
    assert ">Copy invite link</button>" in response.text and "readonly" not in response.text


@pytest.mark.parametrize(
    "form",
    [{"email": "not-an-email"}, {"role": "owner"}, {"valid_days": "0"}, {"valid_days": "31"}],
)
def test_a_bad_form_records_and_sends_nothing(smtp: type[FakeSMTP], form: dict[str, str]) -> None:
    db = FakeDB(hotels=[HOTEL])
    assert send(db, **form).status_code == 422
    assert (db.writes, smtp.sent) == ([], [])


def test_the_page_has_one_invite_form() -> None:
    page = operator(FakeDB(hotels=[HOTEL])).get("/dashboard/hotels/hotel-1").text

    assert page.count('action="/dashboard/hotels/hotel-1/staff-invite') == 1
    assert "Create staff invite link" not in page and "Send invite email" not in page


def test_only_an_operator_sends_invites_from_the_dashboard() -> None:
    db = FakeDB(hotels=[HOTEL])
    app = create_app()
    staff = SimpleNamespace(id="u1", email="admin@example.com", app_metadata={})
    app.dependency_overrides[get_current_user] = lambda: staff
    app.dependency_overrides[get_supabase] = lambda: db
    form = {"email": "new@example.com", "role": "content_creator"}

    response = TestClient(app).post("/dashboard/hotels/hotel-1/staff-invite", data=form)
    assert (response.status_code, db.writes) == (403, [])
