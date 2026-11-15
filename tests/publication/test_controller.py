"""Native orchestration preserves capabilities while separating source admission."""

import copy
from pathlib import Path
import unittest

from scripts.inventory.repositories import ROOT

SOURCE = "a" * 40
HUB = "b" * 40
CONTROL = "c" * 40
ENV = {
    "BIJUX_PUBLICATION_APP_ID": "5265926",
    "BIJUX_PUBLICATION_INSTALLATION_ID": "912",
    "BIJUX_PUBLICATION_ACTOR_ID": "340710222",
    "BIJUX_PUBLICATION_APP_PRIVATE_KEY": "/fixture/key",
}


class Client:
    def __init__(self, repository, commit):
        self.repository, self.commit, self.writes = repository, commit, []

    def read(self, path):
        if path == "users/bijux-publication[bot]":
            return {"id": 340710222, "type": "Bot", "login": "bijux-publication[bot]"}
        if path.endswith("/actions/variables/BIJUX_PUBLICATION_ACTOR_ID"):
            return {"value": "340710222"}
        if path.endswith("/commits/main"):
            return {"sha": self.commit}
        if path == "repos/bijux/" + self.repository:
            return {"full_name": "bijux/" + self.repository, "default_branch": "main"}
        if "check-runs" in path:
            return {"check_runs": []}
        if "/actions/workflows?" in path:
            return {"workflows": []}
        if "/actions/variables?" in path:
            return {"variables": []}
        raise AssertionError(path)

    def dispatch(self, workflow, inputs):
        self.writes.append({"workflow": workflow, "inputs": inputs})
        return {"workflow_run_id": 84}


class Dependencies:
    def __init__(self):
        self.native_calls, self.legacy, self.clients, self.receipts = [], [], [], []
        self.source_calls = []
        self.controller_changed, self.source_changed = False, False

    def controller(self, root, environment):
        self.native_calls.append(None)
        return {
            "status": "admitted",
            "commit": CONTROL,
            "pipeline_id": 11,
            "job_id": (
                12 if not self.controller_changed or len(self.native_calls) == 1 else 13
            ),
        }

    def source(self, root, name, commit, pipeline_id):
        self.source_calls.append((name, commit, pipeline_id))
        return {
            "status": "admitted",
            "commit": commit,
            "report_job_id": (
                90 if not self.source_changed or len(self.source_calls) == 1 else 91
            ),
        }

    def public(self, path):
        if path == "repos/bijux/bijux.github.io/commits/main":
            return {"sha": HUB}
        raise AssertionError(path)

    def credential(self, destination, key, **kwargs):
        client = Client(
            destination, HUB if destination == "bijux.github.io" else SOURCE
        )
        self.clients.append(client)
        return client

    def admit(self, root, client, name, workflow, commit, tag, trusted):
        self.legacy.append((name, workflow, commit, tag, trusted))
        return {"repository": "bijux/" + name, "commit": commit, "workflow": workflow}

    def retain(self, receipt):
        self.receipts.append(copy.deepcopy(receipt))


class NativeRequestTests(unittest.TestCase):
    def module(self):
        import importlib

        self.assertTrue(
            (ROOT / "scripts/publication/controller.py").is_file(),
            "A native controller must replace the disabled GitHub wrapper",
        )
        return importlib.import_module("scripts.publication.controller")

    def run_request(self, request, deps):
        return self.module().execute(
            request,
            root=ROOT,
            environment=ENV,
            controller_admitter=deps.controller,
            source_admitter=deps.source,
            public_reader=deps.public,
            client_factory=deps.credential,
            legacy_admitter=deps.admit,
            retain=deps.retain,
        )

    def test_default_preflight_routes_native_source_to_hub_without_dispatch(self):
        module = self.module()
        deps = Dependencies()
        request = module.Request.from_environment(
            {
                "PUBLICATION_TARGET_REPOSITORY": "bijux-std",
                "PUBLICATION_TARGET_WORKFLOW": "deploy-docs",
                "PUBLICATION_TARGET_COMMIT": SOURCE,
                "PUBLICATION_TARGET_PIPELINE_ID": "88",
            }
        )
        receipt = self.run_request(request, deps)
        self.assertEqual(receipt["operation"], "preflight")
        self.assertEqual(
            receipt["destination"],
            {"repository": "bijux.github.io", "commit": HUB, "path": "/standards/"},
        )
        self.assertEqual(
            deps.legacy, [("bijux.github.io", "deploy-docs", HUB, "", "340710222")]
        )
        self.assertEqual(deps.source_calls[0], ("bijux-std", SOURCE, 88))
        self.assertEqual(deps.clients[0].writes, [])
        self.assertIs(receipt["remote_writes"], False)
        self.assertNotIn("/fixture/key", str(deps.receipts))

    def test_saved_controller_or_source_retry_changes_cannot_reach_dispatch(self):
        module = self.module()
        for field in ("controller_changed", "source_changed"):
            deps = Dependencies()
            setattr(deps, field, True)
            request = module.Request(
                "dispatch", "bijux-iac", "deploy-docs", SOURCE, source_pipeline_id=88
            )
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_request(request, deps)
            self.assertFalse(any(client.writes for client in deps.clients))
            self.assertEqual(deps.receipts[-1]["status"], "blocked")

    def test_existing_legacy_release_keeps_admitted_tag_and_single_destination(self):
        module = self.module()
        deps = Dependencies()
        receipt = self.run_request(
            module.Request(
                "dispatch", "bijux-core", "release-crates", SOURCE, "v1.2.3"
            ),
            deps,
        )
        self.assertEqual(deps.source_calls, [])
        self.assertEqual(
            deps.legacy[0][:4], ("bijux-core", "release-crates", SOURCE, "v1.2.3")
        )
        self.assertEqual(
            deps.clients[0].writes,
            [
                {
                    "workflow": "release-crates",
                    "inputs": {"accepted_commit": SOURCE, "release_tag": "v1.2.3"},
                }
            ],
        )
        self.assertEqual(receipt["dispatch"], {"workflow_run_id": 84})
        self.assertIs(receipt["remote_writes"], True)

    def test_capability_and_native_source_requirements_stop_before_credentials(self):
        module = self.module()
        cases = [
            module.Request("dispatch", "bijux-std", "release-pypi", SOURCE, "v1.2.3"),
            module.Request("preflight", "bijux-iac", "deploy-docs", SOURCE),
            module.Request("preflight", "outside-family", "deploy-docs", SOURCE),
        ]
        for request in cases:
            deps = Dependencies()
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.run_request(request, deps)
            self.assertEqual(deps.clients, [])

    def test_legacy_source_rejects_a_native_pipeline_input_before_credentials(self):
        module = self.module()
        deps = Dependencies()
        request = module.Request.from_environment(
            {
                "PUBLICATION_TARGET_REPOSITORY": "bijux-core",
                "PUBLICATION_TARGET_WORKFLOW": "release-crates",
                "PUBLICATION_TARGET_COMMIT": SOURCE,
                "PUBLICATION_TARGET_TAG": "v1.2.3",
                "PUBLICATION_TARGET_PIPELINE_ID": "88",
            }
        )
        with self.assertRaises(ValueError):
            self.run_request(request, deps)
        self.assertEqual(deps.clients, [])

    def test_unqualified_native_source_and_any_debug_tracing_refuse_credentials(self):
        module = self.module()
        deps = Dependencies()
        deps.source = lambda *_: None
        with self.assertRaises(ValueError):
            self.run_request(
                module.Request(
                    "preflight",
                    "bijux-std",
                    "deploy-docs",
                    SOURCE,
                    source_pipeline_id=88,
                ),
                deps,
            )
        self.assertEqual(deps.clients, [])
        for value in ("true", "TRUE", "1"):
            deps = Dependencies()
            with self.subTest(trace=value), self.assertRaises(ValueError):
                module.execute(
                    module.Request("preflight", "bijux.github.io", "deploy-docs", HUB),
                    root=ROOT,
                    environment={**ENV, "CI_DEBUG_TRACE": value},
                    controller_admitter=deps.controller,
                    source_admitter=deps.source,
                    client_factory=deps.credential,
                    public_reader=deps.public,
                    retain=deps.retain,
                )
            self.assertEqual(deps.clients, [])

    def test_credential_verification_uses_native_controller_and_read_only_access(self):
        module = self.module()
        deps = Dependencies()
        receipt = self.run_request(
            module.Request("verify-credential", "bijux.github.io", "deploy-docs", HUB),
            deps,
        )
        self.assertEqual(receipt["status"], "credential-verified")
        self.assertFalse(receipt["dispatch_write_permission_tested"])
        self.assertEqual(deps.legacy, [])
        self.assertEqual(deps.clients[0].writes, [])

    def test_dispatch_error_is_retained_as_attempted_without_retry_or_secret_text(self):
        module = self.module()
        deps = Dependencies()
        original = deps.credential

        def credential(*args, **kwargs):
            client = original(*args, **kwargs)

            def dispatch(*args):
                client.writes.append("attempted")
                raise ValueError("synthetic-sensitive-error-text")

            client.dispatch = dispatch
            return client

        deps.credential = credential
        with self.assertRaises(ValueError):
            self.run_request(
                module.Request(
                    "dispatch", "bijux-core", "release-crates", SOURCE, "v1.2.3"
                ),
                deps,
            )
        self.assertEqual(deps.clients[0].writes, ["attempted"])
        self.assertEqual(deps.receipts[-1]["status"], "dispatch-failed")
        self.assertIsNone(deps.receipts[-1]["remote_writes"])
        self.assertNotIn("synthetic-sensitive-error-text", str(deps.receipts))

    def test_acknowledged_dispatch_survives_primary_and_failure_receipt_io_errors(self):
        module = self.module()
        deps = Dependencies()

        def retain(receipt):
            if receipt["status"] in {
                "dispatched",
                "dispatch-receipt-failed",
                "dispatch-failed",
            }:
                raise OSError("synthetic-private-storage-detail")
            deps.receipts.append(copy.deepcopy(receipt))

        deps.retain = retain
        with self.assertRaises(module.PublicationFailure) as failed:
            self.run_request(
                module.Request(
                    "dispatch", "bijux-core", "release-crates", SOURCE, "v1.2.3"
                ),
                deps,
            )
        receipt = failed.exception.receipt
        self.assertEqual(len(deps.clients[0].writes), 1)
        self.assertEqual(receipt["status"], "dispatch-receipt-failed")
        self.assertIs(receipt["remote_writes"], True)
        self.assertEqual(receipt["dispatch"], {"workflow_run_id": 84})
        self.assertTrue(receipt["receipt_retention_failed"])
        self.assertEqual(receipt["failed_stage"], "receipt")
        self.assertNotIn("synthetic-private-storage-detail", str(failed.exception))

    def test_unacknowledged_dispatch_keeps_unknown_outcome_when_failure_retention_fails(
        self,
    ):
        module = self.module()
        deps = Dependencies()
        original = deps.credential

        def credential(*args, **kwargs):
            client = original(*args, **kwargs)

            def dispatch(*args):
                client.writes.append("attempted")
                raise ValueError("synthetic-sensitive-dispatch-detail")

            client.dispatch = dispatch
            return client

        def retain(receipt):
            if receipt["status"] == "dispatch-failed":
                raise OSError("synthetic-private-storage-detail")

        deps.credential, deps.retain = credential, retain
        with self.assertRaises(module.PublicationFailure) as failed:
            self.run_request(
                module.Request(
                    "dispatch", "bijux-core", "release-crates", SOURCE, "v1.2.3"
                ),
                deps,
            )
        receipt = failed.exception.receipt
        self.assertEqual(deps.clients[0].writes, ["attempted"])
        self.assertEqual(receipt["status"], "dispatch-failed")
        self.assertIsNone(receipt["remote_writes"])
        self.assertTrue(receipt["receipt_retention_failed"])
        self.assertEqual(receipt["failed_stage"], "dispatch")
        self.assertNotIn("synthetic-sensitive-dispatch-detail", str(failed.exception))

    def test_cli_prints_known_acknowledgement_even_when_fallback_storage_fails(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        from scripts.publication import __main__ as entry

        module = self.module()
        failure = module.PublicationFailure(
            {
                "version": 1,
                "authority": "manual-publication-request",
                "status": "dispatch-receipt-failed",
                "remote_writes": True,
                "dispatch": {"workflow_run_id": 84},
                "receipt_retention_failed": True,
                "failed_stage": "receipt",
                "error_type": "OSError",
            }
        )
        output = io.StringIO()
        with patch("sys.argv", ["publication"]), patch.object(
            entry, "execute", side_effect=failure
        ), patch.object(
            entry.Path, "open", side_effect=OSError("synthetic-storage-detail")
        ), contextlib.redirect_stdout(
            output
        ):
            self.assertEqual(entry.main(), 1)
        receipt = json.loads(output.getvalue())
        self.assertIs(receipt["remote_writes"], True)
        self.assertEqual(receipt["dispatch"], {"workflow_run_id": 84})
        self.assertTrue(receipt["receipt_retention_failed"])
        self.assertEqual(receipt["failed_stage"], "receipt")
        self.assertNotIn("synthetic-storage-detail", output.getvalue())

    def test_legacy_admission_uses_real_shared_policy_and_explicit_reader(self):
        import base64
        import json
        from scripts.inventory.publication import workflow_policy

        module = self.module()
        policy = workflow_policy()
        workflow = {
            "on": {
                "workflow_dispatch": {"inputs": {"accepted_commit": {"required": True}}}
            },
            "jobs": {
                "publication_admission": policy.publication.controller_admission_job(
                    "deploy-docs"
                )
            },
        }
        pull = {
            "number": 5,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-11-15T00:00:00Z",
            "merge_commit_sha": HUB,
            "user": {"type": "User", "login": "bijux"},
            "base": {
                "ref": "main",
                "sha": SOURCE,
                "repo": {"full_name": "bijux/bijux.github.io"},
            },
            "head": {"sha": CONTROL, "repo": {"full_name": "bijux/bijux.github.io"}},
        }
        contexts = [
            "policy / github",
            "policy / pr approval",
            "std / standard",
            "std / report",
        ]

        class ExplicitClient(Client):
            failed = False

            def read(self, path):
                if "/contents/.github/workflows/" in path:
                    return {
                        "content": base64.b64encode(
                            json.dumps(workflow).encode()
                        ).decode()
                    }
                if path.endswith("/commits/main"):
                    return {"sha": HUB, "parents": [{"sha": SOURCE}, {"sha": CONTROL}]}
                if path.endswith("/rules/branches/main"):
                    return [
                        {
                            "type": "required_status_checks",
                            "parameters": {
                                "required_status_checks": [
                                    {"context": name, "integration_id": 15368}
                                    for name in contexts
                                ]
                            },
                        }
                    ]
                if path.endswith("/pulls/5"):
                    return pull
                return super().read(path)

            def pages(self, path):
                if "/pulls?" in path:
                    return [[pull]]
                if "/check-runs?" in path:
                    return [
                        {
                            "check_runs": [
                                {
                                    "id": n + 1,
                                    "name": name,
                                    "head_sha": CONTROL,
                                    "app": {"id": 15368},
                                    "status": "completed",
                                    "conclusion": (
                                        "failure" if self.failed else "success"
                                    ),
                                }
                                for n, name in enumerate(contexts)
                            ]
                        }
                    ]
                raise AssertionError(path)

        client = ExplicitClient("bijux.github.io", HUB)
        receipt = module.admit_legacy(
            ROOT, client, "bijux.github.io", "deploy-docs", HUB, "", "340710222"
        )
        self.assertEqual(receipt["verification_commit"], CONTROL)
        client.failed = True
        with self.assertRaisesRegex(ValueError, "checks"):
            module.admit_legacy(
                ROOT, client, "bijux.github.io", "deploy-docs", HUB, "", "340710222"
            )

    def test_npm_candidate_uses_explicit_selected_reader_and_candidate_identity(self):
        from scripts.execution.publication import npm_candidate

        def read(path):
            if path.endswith("/workflows/package-candidate.yml"):
                return {"id": 17, "path": ".github/workflows/package-candidate.yml"}
            self.assertEqual(path, "repos/bijux/bijux-ro-crate-node/actions/runs/123")
            return {
                "id": 123,
                "workflow_id": 17,
                "repository": {"full_name": "bijux/bijux-ro-crate-node"},
                "head_repository": {"full_name": "bijux/bijux-ro-crate-node"},
                "head_sha": SOURCE,
                "head_branch": "main",
                "event": "workflow_dispatch",
                "status": "completed",
                "conclusion": "success",
            }

        self.assertEqual(
            npm_candidate(
                "bijux-ro-crate-node", SOURCE, candidate_run="123", reader=read
            ),
            {"run_id": 123, "commit": SOURCE, "workflow_id": 17},
        )

    def test_cli_refuses_a_local_session_without_exporting_ambient_authentication(self):
        import json
        import os
        import subprocess
        import sys

        self.module()
        environment = {
            "PATH": os.environ["PATH"],
            "GH_TOKEN": "synthetic-ambient-credential",
        }
        result = subprocess.run(
            [sys.executable, "-B", "-m", "scripts.publication"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "blocked")
        self.assertNotIn("synthetic-ambient-credential", result.stdout + result.stderr)

    def test_cli_does_not_relabel_an_ambiguous_dispatch_as_a_blocked_no_write(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        from scripts.publication import __main__ as entry

        module = self.module()
        deps = Dependencies()
        original = deps.credential

        def credential(*args, **kwargs):
            client = original(*args, **kwargs)

            def dispatch(*args):
                raise ValueError("synthetic-private-detail")

            client.dispatch = dispatch
            return client

        deps.credential = credential
        with self.assertRaises(ValueError) as failed:
            self.run_request(
                module.Request(
                    "dispatch", "bijux-core", "release-crates", SOURCE, "v1.2.3"
                ),
                deps,
            )
        output = io.StringIO()
        with patch("sys.argv", ["publication"]), patch.object(
            entry, "execute", side_effect=failed.exception
        ), contextlib.redirect_stdout(output):
            self.assertEqual(entry.main(), 1)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["status"], "dispatch-failed")
        self.assertIsNone(receipt["remote_writes"])
        self.assertNotIn("synthetic-private-detail", output.getvalue())

    def test_real_default_hub_reader_uses_the_execute_root_and_anonymous_http(self):
        import io
        import json
        import shutil
        import subprocess
        import tempfile
        from unittest.mock import patch
        from scripts.publication import native
        from tests.publication.fixtures import ACCEPTED_PROVIDER, provider

        module = self.module()
        deps = Dependencies()
        accepted, _ = provider()

        class Response(io.BytesIO):
            status = 200

            def geturl(self):
                return "https://api.github.com/repos/bijux/bijux.github.io/commits/main"

        class HTTP:
            urls = []

            def open(self, request, timeout):
                self.urls.append(request.full_url)
                self_test.assertIsNone(request.get_header("Authorization"))
                return Response(json.dumps({"sha": HUB}).encode())

        self_test = self
        http = HTTP()
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as directory:
            checkout = Path(directory)
            shutil.copytree(
                Path(accepted.__file__).parent.parent,
                checkout / ".bijux/shared/bijux-gitlab",
            )
            pin = checkout / ".github/standards/bijux-std.sha"
            pin.parent.mkdir(parents=True)
            pin.write_text(ACCEPTED_PROVIDER + "\n")
            subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
            subprocess.run(
                ["git", "-C", str(checkout), "add", "--", ".bijux", ".github"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "-c",
                    "user.name=Bijux fixture",
                    "-c",
                    "user.email=verification@example.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "test(publication): bind provider fixture",
                ],
                check=True,
            )
            with patch.object(native, "build_opener", return_value=http):
                receipt = module.execute(
                    module.Request(
                        "preflight",
                        "bijux-std",
                        "deploy-docs",
                        SOURCE,
                        source_pipeline_id=88,
                    ),
                    root=checkout,
                    environment=ENV,
                    controller_admitter=deps.controller,
                    source_admitter=deps.source,
                    client_factory=deps.credential,
                    legacy_admitter=deps.admit,
                    retain=deps.retain,
                )
            self.assertEqual(receipt["destination"]["commit"], HUB)
            self.assertEqual(
                http.urls,
                ["https://api.github.com/repos/bijux/bijux.github.io/commits/main"],
            )
