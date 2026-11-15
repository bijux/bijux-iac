"""Use only the existing dispatch App and a single publisher repository token."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

from scripts.execution.publication import APP_PERMISSIONS
from scripts.inventory.authority import GITHUB_IDENTITIES
from scripts.inventory.publication import WORKFLOWS
from scripts.inventory.repositories import ROOT

APP_ID = 5265926
ACTOR = "bijux-publication[bot]"
ACTOR_ID = 340710222


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive(value):
    return type(value) is int and value > 0


class LegacyReadVersion:
    """Keep accepted publisher admission on its existing GitHub API version."""

    def __init__(self, opener):
        self.opener = opener

    def open(self, request, timeout):
        if request.get_method() == "GET" and urlsplit(request.full_url).path.startswith(
            ("/repos/", "/repositories/", "/users/")
        ):
            request.add_header("X-GitHub-Api-Version", "2022-11-28")
        return self.opener.open(request, timeout=timeout)


def shared_api_factory():
    from scripts.publication.native import load_provider

    provider = load_provider(ROOT)
    http = provider.load(
        Path(provider.__file__).with_name("github.py"), "controller_http"
    )
    opener = LegacyReadVersion(build_opener(ProxyHandler({}), http.NoRedirect()))
    return lambda token: http.APIClient(token, opener)


def installation_client(
    destination, key_path, *, installation_id=None, api_factory=None
):
    require(
        destination in GITHUB_IDENTITIES,
        "Publisher destination must be a governed repository",
    )
    require(
        isinstance(key_path, str) and bool(key_path),
        "Explicit dispatch App key file is required",
    )
    key = Path(key_path)
    require(
        key.is_file() and not key.is_symlink(),
        "Explicit dispatch App key file is required",
    )
    require(
        installation_id is None or positive(installation_id),
        "Declared dispatch installation ID is malformed",
    )
    factory = api_factory if api_factory is not None else shared_api_factory()
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=")
    now = int(time.time())
    header = encode(b'{"alg":"RS256","typ":"JWT"}')
    claims = encode(
        json.dumps(
            {"iat": now - 30, "exp": now + 480, "iss": str(APP_ID)},
            separators=(",", ":"),
        ).encode()
    )
    message = header + b"." + claims
    try:
        signature = subprocess.run(
            [
                "openssl",
                "dgst",
                "-sha256",
                "-sign",
                str(key),
                "-sigopt",
                "rsa_padding_mode:pkcs1",
            ],
            input=message,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError("Dispatch App signing failed") from None
    require(bool(signature), "Dispatch App signature is unavailable")
    jwt_api = factory((message + b"." + encode(signature)).decode("ascii"))
    app, _ = jwt_api.request("GET", "/app")
    require(
        isinstance(app, dict)
        and type(app.get("id")) is int
        and app["id"] == APP_ID
        and app.get("slug") == "bijux-publication"
        and app.get("owner", {}).get("login") == "bijux"
        and app.get("permissions") == APP_PERMISSIONS,
        "Existing dispatch App identity or exact permissions differ",
    )
    installation, _ = jwt_api.request(
        "GET", "/repos/bijux/" + destination + "/installation"
    )
    require(
        isinstance(installation, dict)
        and positive(installation.get("id"))
        and (installation_id is None or installation["id"] == installation_id)
        and type(installation.get("app_id")) is int
        and installation["app_id"] == APP_ID
        and installation.get("account", {}).get("login") == "bijux"
        and installation.get("repository_selection") == "selected"
        and installation.get("suspended_at") is None
        and installation.get("permissions") == APP_PERMISSIONS,
        "Dispatch installation identity or exact permissions differ",
    )
    minted, _ = jwt_api.request(
        "POST",
        "/app/installations/" + str(installation["id"]) + "/access_tokens",
        {
            "repository_ids": [GITHUB_IDENTITIES[destination]],
            "permissions": APP_PERMISSIONS,
        },
    )
    require(
        isinstance(minted, dict)
        and minted.get("permissions") == APP_PERMISSIONS
        and minted.get("repository_selection") == "selected",
        "Dispatch token permissions are unverified",
    )
    token = minted.get("token")
    require(
        isinstance(token, str)
        and 0 < len(token) <= 16384
        and all(32 < ord(c) < 127 for c in token),
        "Explicit dispatch token is unavailable",
    )
    try:
        expires = datetime.fromisoformat(minted["expires_at"].replace("Z", "+00:00"))
        seconds = (expires - datetime.now(timezone.utc)).total_seconds()
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ValueError("Dispatch token expiry is unavailable") from None
    require(
        0 < seconds <= 3600, "Dispatch token lifetime is outside its permitted bound"
    )
    scoped = factory(token)
    repositories, headers = scoped.request(
        "GET", "/installation/repositories?per_page=100"
    )
    require(
        isinstance(repositories, dict)
        and type(repositories.get("total_count")) is int
        and repositories["total_count"] == 1
        and isinstance(repositories.get("repositories"), list)
        and len(repositories["repositories"]) == 1
        and not headers.get("link"),
        "Dispatch token must expose exactly one destination repository",
    )
    row = repositories["repositories"][0]
    require(
        isinstance(row, dict)
        and type(row.get("id")) is int
        and row["id"] == GITHUB_IDENTITIES[destination]
        and row.get("full_name") == "bijux/" + destination
        and row.get("owner", {}).get("login") == "bijux",
        "Dispatch token destination readback differs",
    )
    return Client(destination, scoped)


class Client:
    def __init__(self, repository, api):
        require(
            repository in GITHUB_IDENTITIES,
            "Publisher destination is outside the governed family",
        )
        self.repository, self._api = repository, api
        self._prefix = "repos/bijux/" + repository
        self._alias = "repositories/" + str(GITHUB_IDENTITIES[repository])

    def _path(self, path):
        require(
            isinstance(path, str)
            and "://" not in path
            and ".." not in path
            and "#" not in path
            and (
                path in {self._prefix, self._alias, "users/" + ACTOR}
                or path.startswith((self._prefix + "/", self._alias + "/"))
            ),
            "Read endpoint is outside the selected publisher destination",
        )
        return "/" + path.replace("[", "%5B").replace("]", "%5D")

    def read(self, path):
        return self._api.request("GET", self._path(path))[0]

    def pages(self, path):
        current, pages, seen = path, [], set()
        initial = urlsplit("/" + path)
        tail = initial.path.removeprefix("/" + self._prefix).removeprefix(
            "/" + self._alias
        )
        for _ in range(10):
            require(current not in seen, "Publisher pagination repeated an endpoint")
            seen.add(current)
            body, headers = self._api.request("GET", self._path(current))
            pages.append(body)
            links = re.findall(r'<([^>]+)>;\s*rel="next"', headers.get("link", ""))
            require(len(links) <= 1, "Publisher pagination is ambiguous")
            if not links:
                return pages
            parsed = urlsplit(links[0])
            require(
                parsed.scheme == "https"
                and parsed.netloc == "api.github.com"
                and not parsed.fragment
                and parsed.path in {"/" + self._prefix + tail, "/" + self._alias + tail}
                and re.fullmatch(
                    r"(?:per_page=100&page=[1-9][0-9]*|page=[1-9][0-9]*&per_page=100)",
                    parsed.query,
                ),
                "Publisher pagination changed its destination or endpoint",
            )
            current = parsed.path.lstrip("/") + "?" + parsed.query
        raise ValueError("Publisher pagination exceeds its bound")

    def dispatch(self, workflow, inputs):
        require(
            workflow in WORKFLOWS and isinstance(inputs, dict),
            "Canonical publisher workflow is required",
        )
        expected = (
            {"accepted_commit"}
            | ({"release_tag"} if workflow != "deploy-docs" else set())
            | ({"candidate_run_id"} if workflow == "release-npm" else set())
        )
        require(
            set(inputs) == expected
            and isinstance(inputs.get("accepted_commit"), str)
            and re.fullmatch(r"[a-f0-9]{40}", inputs["accepted_commit"]),
            "Immutable publisher inputs are required",
        )
        result, _ = self._api.request(
            "POST",
            "/" + self._prefix + "/actions/workflows/" + workflow + ".yml/dispatches",
            {"ref": "main", "inputs": inputs},
            expected=200,
        )
        require(
            isinstance(result, dict) and positive(result.get("workflow_run_id")),
            "Publisher dispatch acknowledgement is unavailable",
        )
        return {"workflow_run_id": result["workflow_run_id"]}
