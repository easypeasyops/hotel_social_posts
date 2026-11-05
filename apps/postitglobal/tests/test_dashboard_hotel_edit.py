"""An operator's edit of a hotel on the dashboard saves every field the form sends."""

from fastapi.testclient import TestClient

from app.auth.dependencies import require_operator
from app.database import get_supabase
from app.main import create_app
from tests.fakes import FakeDB

HOTEL = {
    "id": "hotel-1",
    "name": "Lagoon Bay",
    "slug": "lagoon-bay",
    "location": "Bodrum",
    "contact_email": "info@lagoon.example",
    "tier": "standard",
    "channels": [],
    "description": "",
}


def test_the_edit_saves_a_new_location() -> None:
    db = FakeDB(hotels=[dict(HOTEL)])
    app = create_app()
    app.dependency_overrides[require_operator] = lambda: object()
    app.dependency_overrides[get_supabase] = lambda: db

    response = TestClient(app, follow_redirects=False).post(
        "/dashboard/hotels/hotel-1",
        data={"name": "Lagoon Bay", "location": "Fethiye", "contact_email": "info@lagoon.example"},
    )

    assert (response.status_code, response.headers["location"]) == (
        303,
        "/dashboard/hotels/hotel-1",
    )
    assert db.rows["hotels"][0]["location"] == "Fethiye"
