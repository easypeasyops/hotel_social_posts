import json

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.github import API, GitHub

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
FILE = "apps/aipostit/deploy/envs/prod.yaml"


@pytest.fixture
def github() -> GitHub:
    return GitHub("Iv1.test", "42", PEM, "easypeasyops/hotel_social_posts")


@respx.mock(base_url=API)
def test_a_file_is_read_with_a_contents_read_token_for_this_repo_only(
    respx_mock: respx.MockRouter, github: GitHub
) -> None:
    token = respx_mock.post("/app/installations/42/access_tokens").respond(
        201, json={"token": "ghs_x"}
    )
    contents = respx_mock.get(f"/repos/easypeasyops/hotel_social_posts/contents/{FILE}").respond(
        200, text="image:\n"
    )

    assert github.read_file(FILE) == "image:\n"

    asked = token.calls.last.request
    assert json.loads(asked.content) == {
        "repositories": ["hotel_social_posts"],
        "permissions": {"contents": "read"},
    }
    app_jwt = asked.headers["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(app_jwt, KEY.public_key(), algorithms=["RS256"])
    assert claims["iss"] == "Iv1.test"
    assert claims["exp"] - claims["iat"] <= 600  # GitHub's limit
    read = contents.calls.last.request
    assert read.headers["Authorization"] == "Bearer ghs_x"
    assert read.url.params["ref"] == "main"


@respx.mock(base_url=API, assert_all_called=False)
def test_a_token_github_refuses_reads_nothing(respx_mock: respx.MockRouter, github: GitHub) -> None:
    respx_mock.post("/app/installations/42/access_tokens").respond(401)
    contents = respx_mock.get(f"/repos/easypeasyops/hotel_social_posts/contents/{FILE}")
    with pytest.raises(httpx.HTTPStatusError):
        github.read_file(FILE)
    assert not contents.called
