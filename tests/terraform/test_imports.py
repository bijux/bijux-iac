from __future__ import annotations

import unittest

from scripts.inventory.repositories import load_inventory


class ImportDiscoveryTests(unittest.TestCase):
    def test_found_and_authoritative_absence_are_distinct(self):
        from unittest.mock import patch
        from scripts.terraform.imports import discover_ruleset
        with patch("scripts.terraform.imports.list_rulesets", return_value=[]):
            self.assertIsNone(discover_ruleset("bijux-iac"))
        with patch("scripts.terraform.imports.list_rulesets", return_value=[{
            "name": "main-branch-protection", "target": "branch", "id": 123,
        }]):
            self.assertEqual(discover_ruleset("bijux-iac"), 123)

    def test_denial_and_ambiguity_are_hard_failures(self):
        from unittest.mock import patch
        from scripts.terraform.imports import discover_all
        import subprocess
        inventory = load_inventory()
        for error in (ValueError("malformed"), subprocess.CalledProcessError(1, ["gh", "api"])):
            with self.subTest(error=error), patch("scripts.terraform.imports.list_rulesets", side_effect=error), \
                    patch("scripts.terraform.imports.subprocess.run") as run:
                with self.assertRaises(type(error)):
                    discover_all(inventory)
                run.assert_not_called()
        matching = {"name": "main-branch-protection", "target": "branch", "id": 123}
        with patch("scripts.terraform.imports.list_rulesets", return_value=[matching, matching]):
            with self.assertRaisesRegex(ValueError, "ambiguous"):
                discover_all(inventory)

    def test_api_pages_require_well_formed_identifiers(self):
        import json
        from unittest.mock import patch
        from scripts.github.api import list_rulesets
        for response in ({"message": "denied"}, [[{"id": True, "name": "main-branch-protection", "target": "branch"}]], [[None]]):
            with self.subTest(response=response), patch("scripts.github.api.subprocess.check_output", return_value=json.dumps(response)):
                with self.assertRaises(ValueError):
                    list_rulesets("bijux-iac")


if __name__ == "__main__":
    unittest.main()
