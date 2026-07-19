from __future__ import annotations

import sys
import unittest
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
        self.assertIn("bijux-gnss", self.repositories)
        self.assertNotIn("bijux-telecom", self.repositories)

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
