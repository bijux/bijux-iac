from __future__ import annotations

import unittest

from scripts.inventory.repositories import load_inventory
from tests.github.ruleset_fixtures import healthy_ruleset


class RulesetAuditTests(unittest.TestCase):

    def test_feature_audit_reports_every_disabled_missing_and_mistyped_surface(self):
        from scripts.github.audit import compare_settings

        expected = {
            "has_issues": True, "has_discussions": True,
            "has_projects": True, "has_wiki": True,
        }
        live = {"has_issues": False, "has_projects": "true", "has_wiki": 1}
        errors = compare_settings("bijux-core", expected, live)
        self.assertEqual(len(errors), 4)
        for feature in expected:
            self.assertTrue(any(feature in error for error in errors), feature)
        self.assertEqual(compare_settings("bijux-core", expected, expected), [])


    def test_bypass_exclusion_and_unenforced_creation_are_rejected_together(self):
        from scripts.github.audit import ruleset_mismatches
        ruleset = healthy_ruleset()
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
        from scripts.github.audit import ruleset_mismatches
        ruleset = healthy_ruleset()
        del ruleset["bypass_actors"]
        del ruleset["rules"][-1]["parameters"]["required_status_checks"][0]["integration_id"]
        self.assertEqual(len(ruleset_mismatches("example", ["example"], ruleset)), 2)

    def test_audit_continues_after_api_errors_and_collects_every_repository(self):
        from unittest.mock import patch
        from scripts.github.audit import audit
        with patch("scripts.github.audit.gh_api_json", side_effect=ValueError("denied")), \
                patch("scripts.github.audit.list_rulesets", side_effect=ValueError("denied")):
            errors = audit(load_inventory())
        self.assertEqual(len(errors), 2 * len(load_inventory()["repositories"]))
        self.assertTrue(any("bijux-pollenomics" in error for error in errors))
        self.assertTrue(any("bijux-gnss" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
