from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from repository_inventory import (  # noqa: E402
    FAMILY_REPOSITORIES,
    load_inventory,
    merged_repository_settings,
)
from render_main_branch_protection_tfvars import render_payload  # noqa: E402


class GovernanceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inventory = load_inventory()
        self.repositories = {
            repository["name"]: repository
            for repository in self.inventory["repositories"]
        }

    def test_inventory_covers_the_complete_bijux_family(self) -> None:
        self.assertEqual(set(self.repositories), set(FAMILY_REPOSITORIES))
        self.assertEqual(len(self.repositories), 12)
        self.assertEqual(
            Counter(repository["class"] for repository in self.repositories.values()),
            {"foundation": 2, "hubs": 2, "rust": 4, "python": 4},
        )

    def test_inventory_checks_match_accepted_standards_for_every_repository(self) -> None:
        import json
        manifest = json.loads((ROOT / ".github/standards/repo-config.manifest.json").read_text())
        base_ruleset = json.loads((ROOT / ".bijux/shared/bijux-gh/rulesets/main-branch-protection.json").read_text())
        required = next(rule for rule in base_ruleset["rules"] if rule["type"] == "required_status_checks")
        baseline = {check["context"] for check in required["parameters"]["required_status_checks"]}
        standards = {repo["name"]: repo for repo in manifest["repositories"]}
        for name, repository in self.repositories.items():
            with self.subTest(repository=name):
                expected = baseline | {check["context"] for check in standards[name].get("additional_required_status_checks", [])}
                self.assertEqual(set(repository["governance"]["branch_protection"]["required_status_checks"]), expected)
        self.assertTrue({"iac / contracts", "iac / plan", "iac / governance"}.issubset(
            self.repositories["bijux-iac"]["governance"]["branch_protection"]["required_status_checks"]))

    def test_genomics_is_the_only_planned_product_delivery(self) -> None:
        planned = {
            name
            for name, repository in self.repositories.items()
            if "planned" in repository["delivery"].values()
        }
        self.assertEqual(planned, {"bijux-genomics"})

    def test_merged_branches_are_deleted_for_every_repository(self) -> None:
        for name, repository in self.repositories.items():
            settings = merged_repository_settings(self.inventory, repository)
            self.assertIs(settings["delete_branch_on_merge"], True, name)

    def test_ruleset_render_covers_every_family_repository(self) -> None:
        payload = render_payload()
        self.assertEqual(
            set(payload["ruleset_repositories"]),
            set(FAMILY_REPOSITORIES),
        )
        self.assertEqual(
            set(payload["ruleset_required_status_checks"]),
            set(FAMILY_REPOSITORIES),
        )


class ProtectionFailureTests(unittest.TestCase):
    def test_disabled_legacy_and_boolean_review_inventory_are_rejected(self):
        import copy
        from validate_repo_inventory import validate_inventory
        for changes in ({"enabled": False}, {"engine": "branch_protection", "required_status_checks": []},
                        {"required_approving_review_count": False}):
            with self.subTest(changes=changes):
                inventory = copy.deepcopy(load_inventory())
                inventory["repositories"][0]["governance"]["branch_protection"].update(changes)
                with self.assertRaises(SystemExit):
                    validate_inventory(inventory)

    @staticmethod
    def healthy_ruleset():
        from audit_live_repository_governance import STATUS_APP_ID
        return {
            "name": "main-branch-protection", "target": "branch", "enforcement": "active",
            "bypass_actors": [], "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                      {"type": "pull_request", "parameters": {
                          "allowed_merge_methods": ["merge"], "required_approving_review_count": 0,
                          "dismiss_stale_reviews_on_push": True, "required_review_thread_resolution": True,
                          "require_code_owner_review": False, "require_last_push_approval": False,
                      }}, {"type": "required_status_checks", "parameters": {
                          "strict_required_status_checks_policy": True, "do_not_enforce_on_create": False,
                          "required_status_checks": [{"context": "example", "integration_id": STATUS_APP_ID}],
                      }}],
        }

    def test_bypass_exclusion_and_unenforced_creation_are_rejected_together(self):
        from audit_live_repository_governance import ruleset_mismatches
        ruleset = self.healthy_ruleset()
        self.assertEqual(ruleset_mismatches("example", ["example"], ruleset), [])
        ruleset["bypass_actors"] = [{"actor_type": "OrganizationAdmin", "bypass_mode": "always"}]
        ruleset["conditions"]["ref_name"]["exclude"] = ["refs/heads/main"]
        ruleset["rules"][-1]["parameters"]["do_not_enforce_on_create"] = True
        errors = ruleset_mismatches("example", ["example"], ruleset)
        self.assertEqual(len(errors), 3)
        self.assertTrue(any("bypass" in error for error in errors))
        self.assertTrue(any("excluded" in error for error in errors))
        self.assertTrue(any("creation" in error for error in errors))

    def test_unknown_bypass_and_unbound_status_sources_are_not_proof_of_protection(self):
        from audit_live_repository_governance import ruleset_mismatches
        ruleset = self.healthy_ruleset()
        del ruleset["bypass_actors"]
        del ruleset["rules"][-1]["parameters"]["required_status_checks"][0]["integration_id"]
        self.assertEqual(len(ruleset_mismatches("example", ["example"], ruleset)), 2)

    def test_audit_continues_after_api_errors_and_collects_every_repository(self):
        from unittest.mock import patch
        from audit_live_repository_governance import audit
        with patch("audit_live_repository_governance.gh_api_json", side_effect=ValueError("denied")), \
                patch("audit_live_repository_governance.list_rulesets", side_effect=ValueError("denied")):
            errors = audit(load_inventory())
        self.assertEqual(len(errors), 24)
        self.assertTrue(any("bijux-pollenomics" in error for error in errors))
        self.assertTrue(any("bijux-gnss" in error for error in errors))


class ImportDiscoveryTests(unittest.TestCase):
    def test_found_and_authoritative_absence_are_distinct(self):
        from unittest.mock import patch
        from import_main_branch_protection import discover_ruleset
        with patch("import_main_branch_protection.list_rulesets", return_value=[]):
            self.assertIsNone(discover_ruleset("bijux-iac"))
        with patch("import_main_branch_protection.list_rulesets", return_value=[{
            "name": "main-branch-protection", "target": "branch", "id": 123,
        }]):
            self.assertEqual(discover_ruleset("bijux-iac"), 123)

    def test_denial_and_ambiguity_are_hard_failures(self):
        from unittest.mock import patch
        from import_main_branch_protection import discover_all
        import subprocess
        inventory = load_inventory()
        for error in (ValueError("malformed"), subprocess.CalledProcessError(1, ["gh", "api"])):
            with self.subTest(error=error), patch("import_main_branch_protection.list_rulesets", side_effect=error), \
                    patch("import_main_branch_protection.subprocess.run") as run:
                with self.assertRaises(type(error)):
                    discover_all(inventory)
                run.assert_not_called()
        matching = {"name": "main-branch-protection", "target": "branch", "id": 123}
        with patch("import_main_branch_protection.list_rulesets", return_value=[matching, matching]):
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                discover_all(inventory)

    def test_api_pages_require_well_formed_identifiers(self):
        import json
        from unittest.mock import patch
        from audit_live_repository_governance import list_rulesets
        for response in ({"message": "denied"}, [[{"id": True, "name": "main-branch-protection", "target": "branch"}]], [[None]]):
            with self.subTest(response=response), patch("audit_live_repository_governance.subprocess.check_output", return_value=json.dumps(response)):
                with self.assertRaises(ValueError):
                    list_rulesets("bijux-iac")


class ApplicationBoundaryTests(unittest.TestCase):
    def test_unaccepted_dispatches_fail_before_api_reads(self):
        from unittest.mock import patch
        from governance_execution import require_main
        for repository, event, ref in [("other/repository", "workflow_dispatch", "refs/heads/main"),
                                       ("bijux/bijux-iac", "pull_request", "refs/heads/main"),
                                       ("bijux/bijux-iac", "workflow_dispatch", "refs/heads/feature")]:
            with self.subTest(ref=ref), patch("governance_execution.gh_api_json") as api:
                with self.assertRaises(ValueError):
                    require_main(repository, event, ref, "commit")
                api.assert_not_called()

    def test_accepted_dispatch_must_match_remote_main_and_checked_out_commit(self):
        from unittest.mock import patch
        from governance_execution import require_main
        with patch("governance_execution.gh_api_json", return_value={"sha": "accepted"}), \
                patch("governance_execution.git_head", return_value="accepted"):
            require_main("bijux/bijux-iac", "workflow_dispatch", "refs/heads/main", "accepted")
            with self.assertRaises(ValueError):
                require_main("bijux/bijux-iac", "workflow_dispatch", "refs/heads/main", "outdated")

    def test_pr_planning_does_not_reference_administration_secrets(self):
        workflow = (ROOT / ".github/workflows/github-governance-plan.yml").read_text()
        self.assertNotIn("secrets.", workflow)
        self.assertNotIn("pull_request_target", workflow)
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
        from governance_execution import verify_receipt
        with patch("governance_execution.input_digests", return_value={"inventory": "current"}), \
                patch("governance_execution.git_head", return_value="accepted"):
            for receipt in [{"status": "planned", "privileged": False},
                            {"status": "planned", "privileged": True, "commit": "accepted", "input_digests": {"inventory": "old"}}]:
                with self.assertRaises(ValueError):
                    verify_receipt(receipt)

    def test_settings_discovery_failure_never_patches_an_earlier_repository(self):
        from unittest.mock import patch
        from governance_execution import settings_plan
        inventory = load_inventory()
        responses = []
        for repository in inventory["repositories"]:
            responses.append({**merged_repository_settings(inventory, repository),
                              "full_name": "bijux/" + repository["name"], "default_branch": "main"})
        responses[-1] = {"message": "denied"}
        with patch("governance_execution.gh_api_json", side_effect=responses), \
                patch("governance_execution.apply_settings") as patch_settings:
            with self.assertRaises(ValueError):
                settings_plan(inventory)
            patch_settings.assert_not_called()

    def test_reader_hidden_settings_are_explicit_and_never_apply_ready(self):
        from unittest.mock import patch
        from governance_execution import settings_plan
        inventory = load_inventory()
        def response(path):
            name = path.rsplit("/", 1)[1]
            return {"full_name": "bijux/" + name, "default_branch": "main", "visibility": "public"}
        with patch("governance_execution.gh_api_json", side_effect=response):
            plan = settings_plan(inventory, require_complete=False)
            self.assertIn("allow_merge_commit", plan["bijux-iac"]["unavailable_to_reader"])
            self.assertNotIn("allow_merge_commit", plan["bijux-iac"]["before"])
            with self.assertRaises(ValueError):
                settings_plan(inventory)

    def test_partial_apply_failure_preserves_operations_and_still_audits(self):
        import subprocess
        from unittest.mock import patch
        from governance_execution import apply
        settings = {repository["name"]: {"before": {"has_wiki": False}, "after": {"has_wiki": True}}
                    for repository in load_inventory()["repositories"]}
        receipt = {"settings": settings, "completed": []}
        with patch("governance_execution.require_accepted_main"), patch("governance_execution.verify_receipt"), \
                patch("governance_execution.settings_plan", return_value=settings), \
                patch("governance_execution.write_receipt"), patch("governance_execution.apply_settings"), \
                patch("governance_execution.terraform", side_effect=subprocess.CalledProcessError(1, ["terraform"])), \
                patch("governance_execution.audit", return_value=["bijux-pollenomics: incomplete ruleset"]) as live_audit:
            with self.assertRaises(subprocess.CalledProcessError):
                apply(receipt)
        live_audit.assert_called_once()
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("settings:bijux-iac", receipt["completed"])
        self.assertIn("ruleset:bijux-pollenomics", receipt["outstanding"])
        self.assertIn("audit:family", receipt["outstanding"])
        self.assertIn("ruleset:bijux-iac", receipt["completed"])

    def test_standalone_settings_reject_arbitrary_scope_before_patch(self):
        from unittest.mock import patch
        from apply_repository_settings import apply_settings
        with patch("apply_repository_settings.subprocess.run") as run:
            with self.assertRaises(SystemExit):
                apply_settings("other", "bijux-iac", {})
            with self.assertRaises(ValueError):
                apply_settings("bijux", "outside-family", {})
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
