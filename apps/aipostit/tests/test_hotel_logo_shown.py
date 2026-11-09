"""The hotel's logo, or its initials without one, beside its name: in the dashboard's hotel
list and on the hotel's page, in the /hotel pages' header and in a staff account's menu."""

from tests.test_hotel_logo import OPERATOR, _client, _staff

IMG = 'src="/logos/hotel-1?v=5"'


def test_the_dashboard_shows_it_in_the_list_and_on_the_hotels_page() -> None:
    client, _ = _client(OPERATOR, logo_version=5)

    assert IMG in client.get("/dashboard/hotels").text
    page = client.get("/dashboard/hotels/hotel-1").text
    assert page.split("<h1", 1)[0].count(IMG) == 1  # in the header, beside the name


def test_staff_see_it_in_the_header_and_in_their_menu() -> None:
    client, _ = _client(_staff(), logo_version=5)
    page = client.get("/hotel").text
    header, menu = page.split("<details data-menu", 1)

    assert IMG in header and IMG in menu.split("</details>", 1)[0]


def test_without_a_logo_the_hotels_initials_stand_in() -> None:
    client, _ = _client(_staff())
    page = client.get("/hotel").text

    assert "/logos/" not in page and page.count(">EK</span>") == 2
