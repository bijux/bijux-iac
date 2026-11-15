"""Keep GitLab-owned mirrors outside legacy GitHub development operations."""

import copy
import unittest
from unittest.mock import patch

from scripts.inventory.repositories import load_inventory, merged_repository_settings

MIRRORS = {"bijux-std", "bijux-iac"}


class AuthorityRoleTests(unittest.TestCase):
    def test_terraform_projection_excludes_both_mirrors_without_dropping_other_profiles(
        self,
    ):
        from scripts.terraform.render import render_payload

        inventory = load_inventory()
        with patch(
            "scripts.terraform.render.validated_inventory", return_value=inventory
        ):
            payload = render_payload()
        expected = {r["name"] for r in inventory["repositories"]} - MIRRORS
        self.assertEqual(set(payload["ruleset_repositories"]), expected)
        self.assertEqual(set(payload["ruleset_required_status_checks"]), expected)

    def test_import_discovery_does_not_import_mirror_admission_rulesets(self):
        from scripts.terraform.imports import discover_all

        inventory = load_inventory()
        with patch(
            "scripts.terraform.imports.discover_ruleset", return_value=123
        ) as discover:
            result = discover_all(inventory)
        self.assertEqual(
            set(result), {r["name"] for r in inventory["repositories"]} - MIRRORS
        )
        self.assertEqual(
            {call.args[0] for call in discover.call_args_list}, set(result)
        )

    def test_readonly_settings_plan_never_plans_legacy_mirror_settings(self):
        from scripts.execution.application import settings_plan

        inventory = load_inventory()

        def read(endpoint):
            name = endpoint.rsplit("/", 1)[1]
            return {
                "full_name": "bijux/" + name,
                "default_branch": "main",
                **merged_repository_settings(inventory, {"settings": {}}),
            }

        with patch("scripts.execution.application.gh_api_json", side_effect=read):
            result = settings_plan(inventory)
        self.assertEqual(
            set(result), {r["name"] for r in inventory["repositories"]} - MIRRORS
        )

    def test_legacy_settings_writer_refuses_mirror_before_transport(self):
        from scripts.github.settings import apply_settings

        inventory = load_inventory()
        for name in MIRRORS:
            with self.subTest(name=name), patch(
                "scripts.github.settings.validated_inventory", return_value=inventory
            ), patch("scripts.github.settings.subprocess.run") as write:
                row = next(r for r in inventory["repositories"] if r["name"] == name)
                with self.assertRaisesRegex(ValueError, "GitLab|mirror"):
                    apply_settings(
                        "bijux", name, merged_repository_settings(inventory, row)
                    )
                write.assert_not_called()

    def test_legacy_api_writer_refuses_mirror_even_when_saved_operation_is_noop(self):
        from scripts.github.ruleset_transport import apply_api_operation

        for name in MIRRORS:
            operation = {
                "repository": name,
                "id": 123,
                "before": {},
                "actions": ["no-op"],
            }
            with self.subTest(name=name), patch(
                "scripts.github.ruleset_transport.gh_api_json", return_value={}
            ) as read, patch(
                "scripts.github.ruleset_transport.subprocess.run"
            ) as write:
                with self.assertRaisesRegex(ValueError, "GitLab|mirror"):
                    apply_api_operation(operation)
                read.assert_not_called()
                write.assert_not_called()

    def test_saved_terraform_plan_cannot_reintroduce_a_mirror_even_if_allowlisted(self):
        from scripts.terraform.plans import validate_ruleset_changes

        for name in MIRRORS:
            address = 'github_repository_ruleset.main["' + name + '"]'
            change = {
                "mode": "managed",
                "address": address,
                "change": {
                    "actions": ["update"],
                    "before": {"rules": []},
                    "after": {"rules": []},
                },
            }
            with self.subTest(name=name), self.assertRaisesRegex(
                ValueError, "GitLab|mirror"
            ):
                validate_ruleset_changes([change], {address})

    def test_github_privileged_path_stays_blocked_after_future_status_activation(self):
        from scripts.execution.application import require_governance_main
        from scripts.inventory.authority import load_authority

        authority = copy.deepcopy(load_authority())
        for row in authority["repositories"]:
            if row["name"] in MIRRORS:
                row["authority"]["status"] = "active"
                row["authority"]["current"] = copy.deepcopy(row["authority"]["target"])
        with patch(
            "scripts.execution.application.validated_inventory",
            return_value=load_inventory(),
        ), patch(
            "scripts.execution.application.validated_authority", return_value=authority
        ), patch(
            "scripts.execution.application.require_accepted_main"
        ), patch.dict(
            "os.environ", {}, clear=True
        ):
            with self.assertRaisesRegex(ValueError, "GitLab|mirror"):
                require_governance_main()

    def test_terraform_repository_value_cannot_hide_a_mirror_under_another_address(
        self,
    ):
        from scripts.terraform.plans import validate_ruleset_changes

        address = 'github_repository_ruleset.main["bijux-canon"]'
        for name in MIRRORS:
            change = {
                "mode": "managed",
                "address": address,
                "change": {
                    "actions": ["update"],
                    "before": {"repository": name, "rules": []},
                    "after": {"repository": name, "rules": []},
                },
            }
            with self.subTest(name=name), self.assertRaisesRegex(
                ValueError, "GitLab|mirror"
            ):
                validate_ruleset_changes([change], {address})
