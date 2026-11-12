"""GitHub as the deploybot GitHub App: a short-lived installation token per call, asked
for with only the permissions that call needs (the app has at most Contents: read and
Actions: write). Nothing here can push, open or merge a PR."""

import time
from typing import Literal

import httpx
import jwt

API = "https://api.github.com"
# The only workflows the bot starts. None of them merges anything into prod: each opens a PR
# with the release app's token, and prod's PRs wait for a person.
WORKFLOWS = frozenset({"bump.yml", "promote.yml", "rollback.yml"})
Permissions = dict[str, Literal["read", "write"]]


class GitHub:
    def __init__(
        self,
        client_id: str,
        installation_id: str,
        private_key: str,
        repository: str,
        http: httpx.Client | None = None,
    ) -> None:
        self._client_id = client_id
        self._installation_id = installation_id
        self._private_key = private_key
        self._repository = repository
        self._http = http or httpx.Client(base_url=API, timeout=10)

    def _app_jwt(self) -> str:
        # GitHub accepts at most 10 minutes; 60 s back allows for clock drift.
        now = int(time.time())
        claims = {"iat": now - 60, "exp": now + 540, "iss": self._client_id}
        return jwt.encode(claims, self._private_key, algorithm="RS256")

    def _token(self, permissions: Permissions) -> str:
        """An installation token (1 hour, never kept) for this repository only."""
        response = self._http.post(
            f"/app/installations/{self._installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {self._app_jwt()}"},
            json={
                "repositories": [self._repository.split("/")[1]],
                "permissions": permissions,
            },
        )
        response.raise_for_status()
        token: str = response.json()["token"]
        return token

    def read_file(self, path: str, ref: str = "main") -> str:
        response = self._http.get(
            f"/repos/{self._repository}/contents/{path}",
            params={"ref": ref},
            headers={
                "Authorization": f"Bearer {self._token({'contents': 'read'})}",
                "Accept": "application/vnd.github.raw+json",
            },
        )
        response.raise_for_status()
        return response.text

    def dispatch(self, workflow: str, inputs: dict[str, str]) -> None:
        """Starts `workflow` on main with `inputs`, with an Actions: write token."""
        if workflow not in WORKFLOWS:
            raise ValueError(f"{workflow} is not a workflow deploybot starts")
        response = self._http.post(
            f"/repos/{self._repository}/actions/workflows/{workflow}/dispatches",
            headers={"Authorization": f"Bearer {self._token({'actions': 'write'})}"},
            json={"ref": "main", "inputs": inputs},
        )
        response.raise_for_status()
