from __future__ import annotations

import unittest
from collections import Counter

from scripts.inventory.repositories import ROOT, FAMILY_REPOSITORIES, load_inventory, merged_repository_settings
from scripts.terraform.render import render_payload


class InventoryContractTests(unittest.TestCase):
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

    def test_missing_unknown_and_redundant_settings_are_rejected(self):
        import copy
        from scripts.inventory.validate import validate_inventory
        for mutate in [lambda repo: repo.pop("settings"),
                       lambda repo: repo.update(unknown_policy=True),
                       lambda repo: repo["settings"].update(has_issues=True),
                       lambda repo: repo["settings"].update(allow_rebase_merge=True)]:
            inventory = copy.deepcopy(self.inventory)
            mutate(inventory["repositories"][0])
            with self.subTest(repository=inventory["repositories"][0]), self.assertRaises(SystemExit):
                validate_inventory(inventory)

    def test_duplicate_json_keys_cannot_hide_inventory_policy(self):
        from unittest.mock import Mock
        path = Mock()
        path.read_text.return_value = '{"settings": {"allow_merge_commit": true, "allow_merge_commit": false}}'
        with self.assertRaisesRegex(ValueError, "duplicate inventory key"):
            load_inventory(path)

    def test_disabled_legacy_and_boolean_review_inventory_are_rejected(self):
        import copy
        from scripts.inventory.validate import validate_inventory
        for changes in ({"enabled": False}, {"engine": "branch_protection", "required_status_checks": []},
                        {"required_approving_review_count": False}):
            with self.subTest(changes=changes):
                inventory = copy.deepcopy(load_inventory())
                inventory["repositories"][0]["governance"]["branch_protection"].update(changes)
                with self.assertRaises(SystemExit):
                    validate_inventory(inventory)


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


if __name__ == "__main__":
    unittest.main()
