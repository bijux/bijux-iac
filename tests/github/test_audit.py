from __future__ import annotations

import unittest

from scripts.inventory.repositories import load_inventory


class RulesetAuditTests(unittest.TestCase):

    @staticmethod
    def healthy_ruleset():
        from scripts.github.audit import STATUS_APP_ID
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
        from scripts.github.audit import ruleset_mismatches
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
        from scripts.github.audit import ruleset_mismatches
        ruleset = self.healthy_ruleset()
        del ruleset["bypass_actors"]
        del ruleset["rules"][-1]["parameters"]["required_status_checks"][0]["integration_id"]
        self.assertEqual(len(ruleset_mismatches("example", ["example"], ruleset)), 2)

    def test_audit_continues_after_api_errors_and_collects_every_repository(self):
        from unittest.mock import patch
        from scripts.github.audit import audit
        with patch("scripts.github.audit.gh_api_json", side_effect=ValueError("denied")), \
                patch("scripts.github.audit.list_rulesets", side_effect=ValueError("denied")):
            errors = audit(load_inventory())
        self.assertEqual(len(errors), 24)
        self.assertTrue(any("bijux-pollenomics" in error for error in errors))
        self.assertTrue(any("bijux-gnss" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
