"""An operator emails a staff invite from the hotel's dashboard page: the email (in Turkish,
through the SMTP account in the settings) carries an invite only that address can use. Without
SMTP settings there's no such option."""

from email.message import EmailMessage
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from app import mail
from app.auth.dependencies import require_operator
from app.auth.upload_tokens import read_staff_invite
from app.database import get_supabase
from app.main import create_app
from tests.fakes import FakeDB

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


def operator() -> TestClient:
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: object()
    app.dependency_overrides[get_supabase] = lambda: FakeDB(hotels=[HOTEL])
    return TestClient(app, follow_redirects=False)


def send(**form: str) -> Any:
    return operator().post(
        "/dashboard/hotels/hotel-1/staff-invite-email",
        data={"email": "New.Staff@Example.com", "role": "content_creator", **form},
    )


def test_the_invite_email_carries_an_invite_for_that_address(smtp: type[FakeSMTP]) -> None:
    response = send()

    assert response.status_code == 200
    assert "Invite sent to new.staff@example.com." in response.text
    assert smtp.calls == [("connect", "smtp.gmail.com", 587), "starttls",
                          ("login", "aipostit@gmail.test", "app-password")]  # fmt: skip
    [message] = smtp.sent
    assert (message["From"], message["To"]) == ("aipostit@gmail.test", "new.staff@example.com")
    assert message["Subject"] == "Ege Konak ekibine davetlisiniz"
    body = message.get_content()
    assert "içerik üreticisi olarak davet edildiniz" in body
    invite = body.split("/signup#invite=", 1)[1].split()[0]
    assert read_staff_invite(unquote(invite)) == (
        "hotel-1",
        "content_creator",
        "new.staff@example.com",
    )


def test_a_failed_send_is_told(smtp: type[FakeSMTP]) -> None:
    smtp.fail = True
    response = send()

    assert response.status_code == 502
    assert "The email could not be sent" in response.text


@pytest.mark.parametrize(("form", "status"), [({"email": "not-an-email"}, 422),
                                              ({"role": "owner"}, 422)])  # fmt: skip
def test_a_bad_form_sends_nothing(smtp: type[FakeSMTP], form: dict[str, str], status: int) -> None:
    assert send(**form).status_code == status
    assert smtp.sent == []


def test_without_smtp_settings_there_is_no_invite_email() -> None:
    page = operator().get("/dashboard/hotels/hotel-1")

    assert "Create staff invite link" in page.text
    assert "Send invite email" not in page.text
    assert send().status_code == 404


def test_with_smtp_settings_the_page_offers_it(smtp: type[FakeSMTP]) -> None:
    assert "Send invite email" in operator().get("/dashboard/hotels/hotel-1").text
