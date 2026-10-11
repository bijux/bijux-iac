from __future__ import annotations

import unittest

from scripts.inventory.repositories import ROOT, load_inventory, merged_repository_settings


class ApplicationBoundaryTests(unittest.TestCase):
    def test_stopped_preflight_retains_attempted_commit_and_digests_without_writes(self):
        import copy
        import json
        from unittest.mock import patch
        from scripts.execution import application
        receipts = []
        def retain(receipt):
            receipts.append(copy.deepcopy(receipt))
        with patch("sys.argv", ["application", "preflight"]), \
                patch.object(application, "git_head", return_value="a" * 40), \
                patch.object(application, "input_digests", return_value={"inventory": "input-digest"}), \
                patch.object(application, "write_receipt", side_effect=retain), \
                patch.object(application, "PLAN") as plan, \
                patch.object(application, "RECEIPT") as receipt, \
                patch.object(application, "preflight", side_effect=ValueError("missing accepted producer")), \
                patch.object(application, "apply_settings") as settings_write, \
                patch.object(application, "terraform") as terraform:
            plan.exists.return_value = False
            receipt.read_text.side_effect = lambda: json.dumps(receipts[-1])
            with self.assertRaisesRegex(ValueError, "missing accepted producer"):
                application.main()
        self.assertEqual(receipts[-1]["status"], "preflight-failed")
        self.assertEqual(receipts[-1]["commit"], "a" * 40)
        self.assertEqual(receipts[-1]["input_digests"], {"inventory": "input-digest"})
        self.assertIs(receipts[-1]["remote_writes"], False)
        settings_write.assert_not_called()
        terraform.assert_not_called()

    def test_credential_verification_reads_the_family_and_never_writes(self):
        from unittest.mock import patch
        from scripts.execution import application
        def api(path):
            if "/rulesets/" in path:
                return {"bypass_actors": []}
            return [] if "/pulls?" in path else {"check_runs": []}
        with patch.object(application, "require_accepted_main"), \
                patch.object(application, "settings_plan"), \
                patch.object(application, "list_rulesets", return_value=[{"name": "main-branch-protection", "id": 1}]), \
                patch.object(application, "gh_api_json", side_effect=api), \
                patch.object(application, "git_head", return_value="a" * 40), \
                patch.object(application, "input_digests", return_value={}), \
                patch.object(application, "write_receipt"), \
                patch.object(application, "apply_settings") as settings_write, \
                patch.object(application, "terraform") as terraform:
            receipt = application.verify_credential()
        self.assertEqual(len(receipt["credential_access"]), 12)
        self.assertEqual(receipt["status"], "credential-verified")
        self.assertIs(receipt["remote_writes"], False)
        settings_write.assert_not_called()
        terraform.assert_not_called()
        with self.assertRaisesRegex(ValueError, "privileged preflight"):
            application.verify_receipt(receipt)

    def test_missing_administrator_visibility_reports_every_repository(self):
        from unittest.mock import patch
        from scripts.execution import application
        with patch.object(application, "require_accepted_main"), \
                patch.object(application, "settings_plan"), \
                patch.object(application, "list_rulesets", return_value=[{"name": "main-branch-protection", "id": 1}]), \
                patch.object(application, "gh_api_json", return_value={}) as api, \
                patch.object(application, "git_head", return_value="a" * 40), \
                patch.object(application, "input_digests", return_value={}), \
                patch.object(application, "write_receipt"):
            with self.assertRaisesRegex(ValueError, "administration visibility"):
                application.verify_credential()
        self.assertEqual(api.call_count, 12)

    def test_workflow_defaults_to_preflight_and_requires_explicit_application(self):
        workflow = (ROOT / ".github/workflows/github-governance-apply.yml").read_text()
        self.assertIn("default: preflight", workflow)
        self.assertIn("if: ${{ inputs.operation == 'apply' }}", workflow)
        self.assertIn('case "$APPLY_OPERATION" in', workflow)
        self.assertIn("verify-credential|preflight|apply)", workflow)
        self.assertLess(workflow.index('case "$APPLY_OPERATION" in'), workflow.index("environment: governance-apply"))

    def test_unaccepted_dispatches_fail_before_api_reads(self):
        from unittest.mock import patch
        from scripts.execution.application import require_main
        for repository, event, ref in [("other/repository", "workflow_dispatch", "refs/heads/main"),
                                       ("bijux/bijux-iac", "pull_request", "refs/heads/main"),
                                       ("bijux/bijux-iac", "workflow_dispatch", "refs/heads/feature")]:
            with self.subTest(ref=ref), patch("scripts.execution.application.gh_api_json") as api:
                with self.assertRaises(ValueError):
                    require_main(repository, event, ref, "commit")
                api.assert_not_called()

    def test_accepted_dispatch_must_match_remote_main_and_checked_out_commit(self):
        from unittest.mock import patch
        from scripts.execution.application import require_main
        with patch("scripts.execution.application.gh_api_json", return_value={"sha": "accepted"}), \
                patch("scripts.execution.application.git_head", return_value="accepted"):
            require_main("bijux/bijux-iac", "workflow_dispatch", "refs/heads/main", "accepted")
            with self.assertRaises(ValueError):
                require_main("bijux/bijux-iac", "workflow_dispatch", "refs/heads/main", "outdated")

    def test_pr_planning_does_not_reference_administration_secrets(self):
        from scripts.inventory.publication import workflow_policy
        workflow = (ROOT / ".github/workflows/github-governance-plan.yml").read_text()
        self.assertNotIn("secrets.", workflow)
        document = workflow_policy().parse_workflow(workflow.encode(), "github-governance-plan.yml")
        self.assertEqual(document["on"], {"pull_request": {"branches": ["main"]}})
        self.assertNotIn("contents: write", workflow)
        self.assertIn("TF_VAR_github_token: ${{ github.token }}", workflow)

    def test_owned_aggregate_rejects_failure_cancellation_and_skips(self):
        import subprocess
        workflow = (ROOT / ".github/workflows/github-governance-plan.yml").read_text()
        command = workflow.rsplit("        run: |\n", 1)[1]
        command = "\n".join(line[10:] for line in command.splitlines())
        for dependency in ["CONTRACTS_RESULT", "PLAN_RESULT"]:
            for result in ["success", "failure", "cancelled", "skipped"]:
                with self.subTest(dependency=dependency, result=result):
                    environment = {"CONTRACTS_RESULT": "success", "PLAN_RESULT": "success", dependency: result}
                    status = subprocess.run(["bash", "-c", command], env=environment, capture_output=True).returncode
                    self.assertEqual(status == 0, result == "success")

    def test_changed_inputs_and_nonprivileged_plans_are_rejected_before_writes(self):
        from unittest.mock import patch
        from scripts.execution.application import verify_receipt
        with patch("scripts.execution.application.input_digests", return_value={"inventory": "current"}), \
                patch("scripts.execution.application.git_head", return_value="accepted"):
            for receipt in [{"status": "planned", "privileged": False},
                            {"status": "planned", "privileged": True, "commit": "accepted", "input_digests": {"inventory": "old"}}]:
                with self.assertRaises(ValueError):
                    verify_receipt(receipt)

    def test_provider_preservation_refusal_precedes_import_and_plan(self):
        import json
        from unittest.mock import patch
        from scripts.execution import application
        inventory = {"repositories": [{"name": "bijux-iac"}]}
        with patch.object(application, "validated_inventory", return_value=inventory), \
                patch.object(application, "require_accepted_main"), \
                patch.object(application, "require_producers", return_value=[]), \
                patch.object(application.subprocess, "check_output", return_value=json.dumps({"terraform_version": application.TERRAFORM_VERSION})), \
                patch.object(application.subprocess, "run"), \
                patch.object(application, "git_head", return_value="accepted"), \
                patch.object(application, "input_digests", return_value={}), \
                patch.object(application, "settings_plan", return_value={}), \
                patch.object(application, "ruleset_snapshot", return_value={"bijux-iac": None}), \
                patch.object(application, "write_receipt"), \
                patch.object(application, "terraform", return_value="{}") as terraform, \
                patch.object(application, "require_representable_rulesets", side_effect=ValueError("cannot preserve API protections")), \
                patch.object(application, "import_rulesets") as imports, \
                patch.object(application, "apply_settings") as writes:
            with self.assertRaisesRegex(ValueError, "cannot preserve API protections"):
                application.preflight(True)
        terraform.assert_called_once_with("providers", "schema", "-json", capture=True)
        imports.assert_not_called()
        writes.assert_not_called()

    def test_public_plan_does_not_claim_privileged_preservation(self):
        import json
        from unittest.mock import patch
        from scripts.execution import application
        def terraform(*arguments, **kwargs):
            return json.dumps({"resource_changes": []}) if arguments[0] == "show" else ""
        with patch.object(application, "validated_inventory", return_value={"repositories": []}), \
                patch.object(application.subprocess, "check_output", return_value=json.dumps({"terraform_version": application.TERRAFORM_VERSION})), \
                patch.object(application.subprocess, "run"), \
                patch.object(application, "git_head", return_value="accepted"), \
                patch.object(application, "input_digests", return_value={}), \
                patch.object(application, "settings_plan", return_value={}), \
                patch.object(application, "write_receipt"), \
                patch.object(application, "WORK_DIR") as work, \
                patch.object(application, "PLAN") as plan, \
                patch.object(application, "terraform", side_effect=terraform) as calls, \
                patch.object(application, "require_accepted_main") as accepted, \
                patch.object(application, "ruleset_snapshot") as snapshots, \
                patch.object(application, "require_representable_rulesets") as preservation, \
                patch.object(application, "import_rulesets"), \
                patch.object(application, "apply_settings") as writes:
            work.glob.return_value = []
            plan.read_bytes.return_value = b"read-only plan"
            receipt = application.preflight(False)
        self.assertEqual(receipt["status"], "planned")
        self.assertIs(receipt["privileged"], False)
        self.assertIs(receipt["remote_writes"], False)
        self.assertNotIn("ruleset_before_images", receipt)
        self.assertNotIn("provider_schema_digest", receipt)
        self.assertEqual([call.args[0] for call in calls.call_args_list], ["plan", "show"])
        accepted.assert_not_called()
        snapshots.assert_not_called()
        preservation.assert_not_called()
        writes.assert_not_called()

    def test_bound_saved_plan_bytes_cannot_be_replaced_on_replay(self):
        import hashlib
        from unittest.mock import patch
        from scripts.execution import application
        receipt = {"status": "planned", "privileged": True, "commit": "accepted", "input_digests": {},
                   "plan_digest": hashlib.sha256(b"reviewed plan").hexdigest()}
        with patch.object(application, "git_head", return_value="accepted"), \
                patch.object(application, "input_digests", return_value={}), patch.object(application, "PLAN") as plan:
            plan.read_bytes.return_value = b"reviewed plan"
            application.verify_receipt(receipt)
            plan.read_bytes.return_value = b"replacement plan"
            with self.assertRaisesRegex(ValueError, "saved plan changed"):
                application.verify_receipt(receipt)

    def test_settings_discovery_failure_never_patches_an_earlier_repository(self):
        from unittest.mock import patch
        from scripts.execution.application import settings_plan
        inventory = load_inventory()
        responses = []
        for repository in inventory["repositories"]:
            responses.append({**merged_repository_settings(inventory, repository),
                              "full_name": "bijux/" + repository["name"], "default_branch": "main"})
        responses[-1] = {"message": "denied"}
        with patch("scripts.execution.application.gh_api_json", side_effect=responses), \
                patch("scripts.execution.application.apply_settings") as patch_settings:
            with self.assertRaises(ValueError):
                settings_plan(inventory)
            patch_settings.assert_not_called()

    def test_reader_hidden_settings_are_explicit_and_never_apply_ready(self):
        from unittest.mock import patch
        from scripts.execution.application import settings_plan
        inventory = load_inventory()
        def response(path):
            name = path.rsplit("/", 1)[1]
            return {"full_name": "bijux/" + name, "default_branch": "main", "visibility": "public"}
        with patch("scripts.execution.application.gh_api_json", side_effect=response):
            plan = settings_plan(inventory, require_complete=False)
            self.assertIn("allow_merge_commit", plan["bijux-iac"]["unavailable_to_reader"])
            self.assertNotIn("allow_merge_commit", plan["bijux-iac"]["before"])
            with self.assertRaises(ValueError):
                settings_plan(inventory)

    def test_partial_apply_failure_preserves_operations_and_still_audits(self):
        import subprocess
        from unittest.mock import patch
        from scripts.execution.application import apply
        settings = {repository["name"]: {"before": {"has_wiki": False}, "after": {"has_wiki": True}}
                    for repository in load_inventory()["repositories"]}
        receipt = {"settings": settings, "ruleset_before_images": {}, "completed": []}
        with patch("scripts.execution.application.require_accepted_main"), patch("scripts.execution.application.verify_receipt"), \
                patch("scripts.execution.application.settings_plan", return_value=settings), \
                patch("scripts.execution.application.require_ruleset_snapshot"), \
                patch("scripts.execution.application.write_receipt"), patch("scripts.execution.application.apply_settings"), \
                patch("scripts.execution.application.terraform", side_effect=subprocess.CalledProcessError(1, ["terraform"])), \
                patch("scripts.execution.application.audit", return_value=["bijux-pollenomics: incomplete ruleset"]) as live_audit:
            with self.assertRaises(subprocess.CalledProcessError):
                apply(receipt)
        live_audit.assert_called_once()
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("settings:bijux-iac", receipt["completed"])
        self.assertIn("ruleset:bijux-pollenomics", receipt["outstanding"])
        self.assertIn("audit:family", receipt["outstanding"])
        self.assertIn("ruleset:bijux-iac", receipt["completed"])

    def test_ruleset_drift_refuses_before_any_settings_or_terraform_write(self):
        from unittest.mock import patch
        from scripts.execution import application
        receipt = {"settings": {}, "ruleset_before_images": {}, "completed": []}
        with patch.object(application, "require_accepted_main"), patch.object(application, "verify_receipt"), \
                patch.object(application, "settings_plan", return_value={}), \
                patch.object(application, "require_ruleset_snapshot", side_effect=ValueError("live rulesets changed")), \
                patch.object(application, "apply_settings") as settings_write, \
                patch.object(application, "terraform") as terraform:
            with self.assertRaisesRegex(ValueError, "live rulesets changed"):
                application.apply(receipt)
        settings_write.assert_not_called()
        terraform.assert_not_called()

    def test_ruleset_drift_during_settings_writes_retains_partial_ledger(self):
        from unittest.mock import patch
        from scripts.execution import application
        inventory = load_inventory()
        settings = {r["name"]: {"before": {"has_wiki": False}, "after": {"has_wiki": True}}
                    for r in inventory["repositories"]}
        receipt = {"settings": settings, "ruleset_before_images": {}, "completed": []}
        with patch.object(application, "require_accepted_main"), patch.object(application, "verify_receipt"), \
                patch.object(application, "settings_plan", return_value=settings), \
                patch.object(application, "require_ruleset_snapshot", side_effect=[None, ValueError("live rulesets changed")]) as read, \
                patch.object(application, "write_receipt"), patch.object(application, "apply_settings"), \
                patch.object(application, "terraform") as terraform, \
                patch.object(application, "audit", return_value=["bijux-iac: concurrent ruleset edit"]):
            with self.assertRaisesRegex(ValueError, "live rulesets changed"):
                application.apply(receipt)
        self.assertEqual(read.call_count, 2)
        terraform.assert_not_called()
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("settings:bijux-iac", receipt["completed"])
        self.assertIn("ruleset:bijux-iac", receipt["outstanding"])
        self.assertIn("audit:family", receipt["outstanding"])

    def test_standalone_settings_reject_arbitrary_scope_before_patch(self):
        from unittest.mock import patch
        from scripts.github.settings import apply_settings
        with patch("scripts.github.settings.subprocess.run") as run:
            with self.assertRaises(SystemExit):
                apply_settings("other", "bijux-iac", {})
            with self.assertRaises(ValueError):
                apply_settings("bijux", "outside-family", {})
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
