from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.execution import publication
from scripts.github import publication as live_publication
from scripts.inventory.publication import publisher_declarations, validate_request, validate_publisher, workflow_policy
from scripts.inventory.repositories import ROOT, load_inventory


class PublicationBoundaryTests(unittest.TestCase):
    def test_capabilities_come_from_the_accepted_standard_and_delivery_inventory(self):
        inventory = load_inventory()
        declarations = publisher_declarations(inventory)
        self.assertEqual(len(declarations), 12)
        self.assertEqual(declarations["bijux-iac"], {})
        self.assertEqual(declarations["bijux-std"], {})
        validate_request(inventory, "bijux-core", "release-pypi", "a" * 40, "v1.2.3")
        validate_request(inventory, "bijux.github.io", "deploy-docs", "a" * 40, "")
        for repository, workflow, commit, tag in [
            ("outside-family", "deploy-docs", "a" * 40, ""),
            ("bijux-iac", "release-github", "a" * 40, "v1.2.3"),
            ("bijux-genomics", "deploy-docs", "a" * 40, ""),
            ("bijux.github.io", "release-pypi", "a" * 40, "v1.2.3"),
            ("bijux-canon", "release-crates", "a" * 40, "v1.2.3"),
            ("bijux-canon", "release-pypi", "main", "v1.2.3"),
            ("bijux-canon", "release-pypi", "a" * 40, ""),
            ("bijux.github.io", "deploy-docs", "a" * 40, "v1.2.3"),
        ]:
            with self.subTest(repository=repository, workflow=workflow), self.assertRaises(ValueError):
                validate_request(inventory, repository, workflow, commit, tag)

    def test_unaccepted_controller_code_stops_before_target_or_app_reads(self):
        with patch.object(publication, "require_accepted_main", side_effect=ValueError("unaccepted controller")), \
                patch.object(publication, "gh_api_json") as api:
            with self.assertRaisesRegex(ValueError, "unaccepted controller"):
                publication.request("bijux.github.io", "deploy-docs", "a" * 40, "")
        api.assert_not_called()

    def test_inventory_rejects_a_publisher_without_the_controller_policy(self):
        from scripts.inventory.validate import validate_inventory
        from scripts.inventory import publication as declarations
        manifest = json.loads((ROOT / ".github/standards/repo-config.manifest.json").read_text())
        entry = next(value for value in manifest["repositories"] if value["name"] == "bijux-core")
        entry["workflow_execution_policy"]["publication_entrypoints"]["release-pypi"] = {"mode": "manual-only"}
        with patch.object(declarations, "ROOT") as root:
            root.__truediv__.return_value.read_text.return_value = json.dumps(manifest)
            with self.assertRaisesRegex(SystemExit, "manual IaC control"):
                validate_inventory(load_inventory())

    def test_app_with_additional_permissions_is_rejected_before_consumer_reads(self):
        app = {"id": 12, "owner": {"login": "bijux"}, "permissions": {**publication.APP_PERMISSIONS, "administration": "write"}}
        with patch.object(publication, "require_accepted_main"), \
                patch.dict(os.environ, {"PUBLICATION_CONTROLLER_ACTOR": "bijux-publication[bot]", "PUBLICATION_APP_ID": "12"}), \
                patch.object(publication, "gh_api_json", return_value=app) as api:
            with self.assertRaisesRegex(ValueError, "exactly"):
                publication.request("bijux.github.io", "deploy-docs", "a" * 40, "")
        api.assert_called_once_with("apps/bijux-publication")

    def test_valid_personal_account_app_request_uses_consumer_trust_and_shared_admission(self):
        policy = workflow_policy()
        document = {"on": {"workflow_dispatch": {"inputs": {"accepted_commit": {"required": True}}}},
                    "jobs": {"publication_admission": policy.publication.controller_admission_job("deploy-docs")}}
        app = {"id": 12, "owner": {"login": "bijux", "type": "User"}, "permissions": publication.APP_PERMISSIONS}
        encoded = base64.b64encode(json.dumps(document).encode()).decode()
        from unittest.mock import Mock
        admit = Mock(return_value={"commit": "a" * 40})
        with patch.object(publication, "require_accepted_main"), \
                patch.object(publication, "workflow_policy", return_value=policy), \
                patch.object(policy, "parse_workflow", return_value=document), \
                patch.object(publication.runpy, "run_path", return_value={"admit": admit}), \
                patch.dict(os.environ, {"PUBLICATION_CONTROLLER_ACTOR": "bijux-publication[bot]",
                                       "PUBLICATION_APP_ID": "12", "PUBLICATION_CONTROLLER_ACTOR_ID": "123"}), \
                patch.object(publication, "gh_api_json", side_effect=[app, {"content": encoded}, {"value": "123"}]):
            self.assertEqual(publication.request("bijux.github.io", "deploy-docs", "a" * 40, ""), {"commit": "a" * 40})
        environment = admit.call_args.args[0]
        self.assertEqual(environment["PUBLICATION_CONTROLLER_ACTOR_ID"], "123")
        self.assertEqual(environment["PUBLICATION_ACTOR_ID"], "123")
        self.assertEqual(environment["PUBLICATION_TRIGGERING_ACTOR"], "bijux-publication[bot]")
        self.assertEqual(environment["PUBLICATION_RUN_SHA"], "a" * 40)

    def test_dispatch_sends_only_immutable_inputs_and_retains_failed_dispatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as directory, \
                patch.object(publication, "ROOT", Path(directory)), \
                patch.object(publication, "request", return_value={"commit": "a" * 40}), \
                patch.dict(os.environ, {"GITHUB_SHA": "b" * 40, "GITHUB_RUN_ID": "12"}), \
                patch.object(publication.subprocess, "run") as run:
            receipt = publication.dispatch("bijux-canon", "release-pypi", "a" * 40, "v1.2.3")
            self.assertEqual(receipt["status"], "dispatched")
            self.assertEqual(json.loads(run.call_args.kwargs["input"]),
                             {"ref": "main", "inputs": {"accepted_commit": "a" * 40, "release_tag": "v1.2.3"}})
            self.assertEqual(receipt["controller_commit"], "b" * 40)
            run.side_effect = subprocess.CalledProcessError(1, ["gh", "api"])
            with self.assertRaises(subprocess.CalledProcessError):
                publication.dispatch("bijux-canon", "release-pypi", "a" * 40, "v1.2.3")
            stored = json.loads((Path(directory) / "artifacts/publication/request.json").read_text())
            self.assertEqual(stored["status"], "dispatch-failed")

    def test_denied_admission_cannot_dispatch(self):
        with patch.object(publication, "request", side_effect=ValueError("unhealthy checks")), \
                patch.object(publication.subprocess, "run") as write:
            with self.assertRaisesRegex(ValueError, "unhealthy checks"):
                publication.dispatch("bijux-canon", "release-pypi", "a" * 40, "v1.2.3")
        write.assert_not_called()

    def test_canonical_admission_controls_every_publisher_job(self):
        policy = workflow_policy()
        document = {"on": {"workflow_dispatch": {"inputs": {"accepted_commit": {"required": True}}}},
                    "jobs": {"publication_admission": policy.publication.controller_admission_job("deploy-docs"),
                             "publish": {"needs": ["publication_admission"], "if": "${{ needs.publication_admission.result == 'success' && (success()) }}"}}}
        validate_publisher(policy, "deploy-docs", document)
        for change in [lambda value: value["on"].update(push={}),
                       lambda value: value["jobs"]["publication_admission"].update(permissions={"contents": "write"}),
                       lambda value: value["jobs"]["publish"].update(needs=[]),
                       lambda value: value["jobs"]["publish"].update(**{"if": "always()"}),
                       lambda value: value["jobs"]["publish"].update(**{"if": "${{ always() || needs.publication_admission.result == 'success' }}"}),
                       lambda value: value.update(jobs=None),
                       lambda value: value["on"]["workflow_dispatch"]["inputs"].update(accepted_commit=True)]:
            changed = copy.deepcopy(document)
            change(changed)
            with self.assertRaises(ValueError):
                validate_publisher(policy, "deploy-docs", changed)

    def test_audit_rejects_renamed_publishers_and_automatic_reusable_callers(self):
        policy = workflow_policy()
        for document in [
            {"on": {"push": {}}, "jobs": {"ship": {"steps": [{"run": "cargo publish"}]}}},
            {"on": {"push": {}}, "jobs": {"ship": {"uses": "bijux/bijux-canon/.github/workflows/release-pypi.yml@main"}}},
        ]:
            self.assertTrue(live_publication.publication_mismatches(policy, {}, {"renamed.yml": document}))
        ordinary_ci = {"on": {"push": {}}, "jobs": {"test": {"steps": [{"uses": "actions/upload-artifact@" + "a" * 40}]}}}
        self.assertEqual(live_publication.publication_mismatches(policy, {}, {"ci.yml": ordinary_ci}), [])

    def test_audit_records_all_twelve_when_live_reads_are_denied(self):
        with patch.object(live_publication, "gh_api_json", side_effect=ValueError("read denied")):
            receipt = live_publication.audit(load_inventory(), "123")
        self.assertEqual(len(receipt["repositories"]), 12)
        self.assertEqual(receipt["status"], "drift")
        self.assertIs(receipt["remote_writes"], False)
        self.assertTrue(all(entry["mismatches"] for entry in receipt["repositories"]))

    def test_publication_workflow_is_manual_and_secrets_follow_admission(self):
        workflow = (ROOT / ".github/workflows/publication-control.yml").read_text()
        self.assertNotIn("pull_request", workflow)
        self.assertNotIn("push:", workflow)
        self.assertLess(workflow.index('[[ "$APPLY_REF" == "refs/heads/main" ]]'), workflow.index("environment: publication-control"))
        self.assertLess(workflow.index("publication validate"), workflow.index("secrets.BIJUX_PUBLICATION_APP_PRIVATE_KEY"))
        self.assertIn("repositories: ${{ inputs.repository }}", workflow)


if __name__ == "__main__":
    unittest.main()
