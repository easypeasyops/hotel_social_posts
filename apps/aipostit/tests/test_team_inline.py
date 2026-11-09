"""/hotel/staff updates in place like the dashboard's staff section (app/static/inline.js): its
forms are marked data-inline="team", and every answer they get holds that element with the
outcome in it. Pending invites come first, each link only on a copy button; ended ones are
folded away."""

from tests.fakes import FakeDB
from tests.test_invite_revoke import staff
from tests.test_invite_table import HOTEL, invites, team_page

OTHER = {
    "user_id": "u2",
    "hotel_id": "hotel-1",
    "email": "u2@example.com",
    "role": "content_creator",
}


def team(page: str) -> str:
    return page.split('<div id="team"', 1)[1].split("<script", 1)[0]


def test_pending_invites_come_first_with_their_links_on_copy_buttons_only() -> None:
    page = team(team_page("hotel_admin", FakeDB(hotels=[HOTEL], staff_invites=invites())).text)
    pending, ended = page.split('<details id="ended-invites"', 1)

    assert "sent@example.com" in pending and "unsent@example.com" in pending
    assert "Sona eren davetler (3)" in ended
    assert all(e in ended for e in ("joined@", "lapsed@", "taken-back@"))
    assert (
        page.index("Birini davet edin")
        < page.index("Bekleyen davetler")
        < page.index("Ekip üyeleri")
    )
    assert page.count("/signup#invite=") == page.count(' data-copy="') == 2
    assert "readonly" not in page and ">Bağlantıyı kopyala</button>" in page


def test_every_team_form_updates_in_place() -> None:
    db = FakeDB(hotels=[HOTEL], staff_invites=invites())
    client = staff(db)
    db.rows["hotel_members"].append(OTHER)
    page = client.get("/hotel/staff").text

    # invite, two revokes, and the other member's role and remove
    assert team(page).count("<form ") == team(page).count('data-inline="team"') == 5
    assert '<script src="/static/inline.js" defer></script>' in page


def test_a_revoke_lands_on_the_page_with_its_outcome() -> None:
    client = staff(FakeDB(hotels=[HOTEL], staff_invites=invites()))
    client.follow_redirects = True

    page = client.post("/hotel/staff/invites/id-sent/revoke").text
    assert 'data-focus tabindex="-1"' in team(page) and "Davet iptal edildi." in team(page)


def test_a_bad_invite_answers_with_the_page_and_its_error() -> None:
    response = staff(FakeDB(hotels=[HOTEL])).post(
        "/hotel/staff/invite", data={"email": "yeni", "role": "content_creator"}
    )
    assert response.status_code == 422
    assert 'role="alert" data-focus' in team(response.text)
    assert "Bir e-posta adresi girin." in team(response.text)
