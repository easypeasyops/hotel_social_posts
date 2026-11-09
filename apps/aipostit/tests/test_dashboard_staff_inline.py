"""The dashboard's "Hotel staff" section updates in place (app/static/inline.js): its forms are
marked data-inline="staff", and every answer they get, the redirect's page or the invite form's
200 or 422, holds that section with the outcome in it. Pending invites come first, each link
only on a copy button; ended ones are folded away."""

import pytest

from tests.fakes import FakeDB
from tests.test_invite_revoke import operator
from tests.test_invite_table import HOTEL, dashboard, invites

MEMBER = {"user_id": "u1", "hotel_id": "hotel-1", "email": "u1@example.com", "role": "hotel_admin"}


def section(page: str) -> str:
    return page.split('<section id="staff"', 1)[1].split("</section>", 1)[0]


def test_pending_invites_come_first_with_their_links_on_copy_buttons_only() -> None:
    staff = section(dashboard(FakeDB(hotels=[HOTEL], staff_invites=invites())))
    pending, ended = staff.split('<details id="ended-invites"', 1)

    assert "sent@example.com" in pending and "unsent@example.com" in pending
    assert "Ended invites (3)" in ended
    assert all(e in ended for e in ("joined@", "lapsed@", "taken-back@"))
    assert staff.index("Invite someone") < staff.index("Pending invites") < staff.index("Members")
    assert staff.count("/signup#invite=") == staff.count(' data-copy="') == 2
    assert "readonly" not in staff and ">Copy invite link</button>" in staff


def test_every_staff_form_updates_the_section_in_place() -> None:
    db = FakeDB(hotels=[HOTEL], staff_invites=invites(), hotel_members=[MEMBER])
    page = dashboard(db)

    assert section(page).count("<form ") == section(page).count('data-inline="staff"') == 5
    assert '<script src="/static/inline.js" defer></script>' in page


@pytest.mark.parametrize(
    ("path", "form", "outcome"),
    [
        ("invites/id-sent/revoke", {}, "Invite revoked."),
        ("staff/u1/role", {"role": "content_creator"}, "Role changed."),
        ("staff/u1/remove", {}, "Removed from this hotel."),
    ],
)
def test_each_action_lands_on_the_section_with_its_outcome(
    path: str, form: dict[str, str], outcome: str
) -> None:
    db = FakeDB(hotels=[HOTEL], staff_invites=invites(), hotel_members=[MEMBER])
    client = operator(db)
    client.follow_redirects = True

    page = client.post(f"/dashboard/hotels/hotel-1/{path}", data=form).text
    assert f'data-focus tabindex="-1" class="mt-2 text-sm text-green-800">{outcome}' in (
        section(page)
    )


def test_a_bad_invite_answers_with_the_section_and_its_error() -> None:
    response = operator(FakeDB(hotels=[HOTEL])).post(
        "/dashboard/hotels/hotel-1/staff-invite", data={"email": "nope", "role": "hotel_admin"}
    )
    assert response.status_code == 422
    assert 'role="alert" data-focus' in section(response.text)
    assert "Enter an email address." in section(response.text)
