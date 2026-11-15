"""The existing dispatch App may mint only the selected publisher credential."""

import base64
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.inventory.repositories import ROOT

PERMISSIONS = {
    "actions": "write",
    "contents": "read",
    "checks": "read",
    "actions_variables": "read",
    "metadata": "read",
}


class Wire:
    def __init__(self, responses, token):
        self.responses, self.token, self.requests = responses, token, []

    def request(self, method, path, payload=None, **kwargs):
        self.requests.append((method, path, payload, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result), {}


class Factory:
    def __init__(self, installation_change=None, mint_change=None, repositories=None):
        self.clients = []
        install = {
            "id": 912,
            "app_id": 5265926,
            "account": {"login": "bijux"},
            "repository_selection": "selected",
            "suspended_at": None,
            "permissions": PERMISSIONS,
        }
        mint = {
            "token": "synthetic-selected-token",
            "permissions": PERMISSIONS,
            "repository_selection": "selected",
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=30)
            ).isoformat(),
        }
        self.responses = [
            {
                "id": 5265926,
                "slug": "bijux-publication",
                "owner": {"login": "bijux"},
                "permissions": PERMISSIONS,
            },
            {**install, **(installation_change or {})},
            {**mint, **(mint_change or {})},
            repositories
            or {
                "total_count": 1,
                "repositories": [
                    {
                        "id": 1037487722,
                        "full_name": "bijux/bijux.github.io",
                        "owner": {"login": "bijux"},
                    }
                ],
            },
        ]

    def __call__(self, token):
        wire = Wire(self.responses, token)
        self.clients.append(wire)
        return wire


class DispatchCredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / "artifacts").mkdir(exist_ok=True)
        cls.folder = tempfile.TemporaryDirectory(dir=ROOT / "artifacts")
        cls.key = Path(cls.folder.name) / "fixture.pem"
        subprocess.run(
            [
                "openssl",
                "genpkey",
                "-algorithm",
                "RSA",
                "-pkeyopt",
                "rsa_keygen_bits:2048",
                "-out",
                str(cls.key),
            ],
            check=True,
            capture_output=True,
        )
        cls.key.chmod(0o600)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def module(self):
        import importlib

        self.assertTrue(
            (ROOT / "scripts/publication/credentials.py").is_file(),
            "Native controller requires an explicit existing-App credential factory",
        )
        return importlib.import_module("scripts.publication.credentials")

    def test_mints_exact_existing_permissions_and_one_real_destination(self):
        module = self.module()
        factory = Factory()
        client = module.installation_client(
            "bijux.github.io", str(self.key), api_factory=factory
        )
        self.assertEqual(client.repository, "bijux.github.io")
        writes = [
            request
            for wire in factory.clients
            for request in wire.requests
            if request[0] == "POST"
        ]
        self.assertEqual(
            [(row[1], row[2]) for row in writes],
            [
                (
                    "/app/installations/912/access_tokens",
                    {"repository_ids": [1037487722], "permissions": PERMISSIONS},
                )
            ],
        )
        jwt = factory.clients[0].token.split(".")
        claims = json.loads(base64.urlsafe_b64decode(jwt[1] + "=" * (-len(jwt[1]) % 4)))
        self.assertEqual(claims["iss"], "5265926")
        self.assertLessEqual(claims["exp"] - claims["iat"], 600)
        self.assertNotIn("synthetic-selected-token", repr(client))

    def test_wrong_app_permissions_expiry_and_extra_repository_refuse(self):
        module = self.module()
        for change in (
            {"app_id": 5768636},
            {"permissions": {**PERMISSIONS, "administration": "write"}},
            {"suspended_at": "2026-11-15T00:00:00Z"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.installation_client(
                    "bijux.github.io",
                    str(self.key),
                    api_factory=Factory(installation_change=change),
                )
        for change in (
            {"permissions": {**PERMISSIONS, "contents": "write"}},
            {"expires_at": "2000-01-01T00:00:00Z"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                module.installation_client(
                    "bijux.github.io",
                    str(self.key),
                    api_factory=Factory(mint_change=change),
                )
        with self.assertRaises(ValueError):
            module.installation_client(
                "bijux.github.io",
                str(self.key),
                api_factory=Factory(
                    repositories={
                        "total_count": 2,
                        "repositories": [{"id": 1037487722}, {"id": 1212849789}],
                    }
                ),
            )

    def test_ambient_credentials_cannot_supply_a_missing_key(self):
        import os
        from unittest.mock import patch

        module = self.module()
        with patch.dict(
            os.environ, {"GH_TOKEN": "ambient-secret", "GITHUB_TOKEN": "ambient-secret"}
        ):
            with self.assertRaises(ValueError):
                module.installation_client("bijux.github.io", "", api_factory=Factory())

    def test_declared_installation_identity_cannot_be_substituted(self):
        module = self.module()
        with self.assertRaises(ValueError):
            module.installation_client(
                "bijux.github.io",
                str(self.key),
                installation_id=999,
                api_factory=Factory(),
            )

    def test_client_restricts_reads_and_only_exposes_explicit_publisher_dispatch(self):
        module = self.module()
        wire = Wire([{"sha": "a" * 40}, {"workflow_run_id": 42}], "synthetic")
        client = module.Client("bijux.github.io", wire)
        self.assertEqual(
            client.read("repos/bijux/bijux.github.io/commits/main"), {"sha": "a" * 40}
        )
        for endpoint in (
            "repos/bijux/bijux-std/commits/main",
            "https://evil.invalid/",
            "repos/bijux/bijux.github.io/../outside",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                client.read(endpoint)
        result = client.dispatch("deploy-docs", {"accepted_commit": "a" * 40})
        self.assertEqual(result, {"workflow_run_id": 42})
        self.assertEqual(
            wire.requests[-1][:3],
            (
                "POST",
                "/repos/bijux/bijux.github.io/actions/workflows/deploy-docs.yml/dispatches",
                {"ref": "main", "inputs": {"accepted_commit": "a" * 40}},
            ),
        )
        with self.assertRaises(ValueError):
            client.dispatch("outside", {})
