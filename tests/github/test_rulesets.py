from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from scripts.github import rulesets

INVENTORY = {"repositories": [{"name": "bijux-iac"}]}
DETAIL = {"id": 123, "name": "main-branch-protection", "target": "branch", "enforcement": "active",
          "source_type": "Repository", "source": "bijux/bijux-iac",
          "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
          "rules": [{"type": "required_signatures"}], "bypass_actors": [], "unrelated_metadata": "retained"}


class RulesetBeforeImageTests(unittest.TestCase):
    def capture(self, detail=DETAIL, discovery=None):
        if discovery is None:
            discovery = [{"id": 123, "name": "main-branch-protection", "target": "branch"}]
        with patch.object(rulesets, "list_rulesets", return_value=discovery), \
                patch.object(rulesets, "gh_api_json", return_value=detail):
            return rulesets.ruleset_snapshot(INVENTORY)

    def test_complete_before_image_retains_unrelated_fields(self):
        self.assertEqual(self.capture(), {"bijux-iac": DETAIL})

    def test_verified_absence_is_bound_and_later_creation_refuses(self):
        self.assertEqual(self.capture(discovery=[]), {"bijux-iac": None})
        with patch.object(rulesets, "ruleset_snapshot", return_value=self.capture()):
            with self.assertRaisesRegex(ValueError, "changed after planning"):
                rulesets.require_ruleset_snapshot(INVENTORY, {"bijux-iac": None})

    def test_failed_discovery_never_becomes_verified_absence(self):
        with patch.object(rulesets, "list_rulesets", side_effect=ValueError("denied")), \
                patch.object(rulesets, "gh_api_json") as detail:
            with self.assertRaisesRegex(ValueError, "denied"):
                rulesets.ruleset_snapshot(INVENTORY)
            detail.assert_not_called()

    def test_ambiguous_identity_and_reader_hidden_fields_refuse(self):
        for detail, discovery in [(DETAIL, [{"id": 123, "name": "main-branch-protection", "target": "branch"}] * 2),
                                  ({key: value for key, value in DETAIL.items() if key != "bypass_actors"}, None),
                                  ({**DETAIL, "source_type": "Organization"}, None),
                                  ({**DETAIL, "id": 999}, None)]:
            with self.subTest(detail=detail, discovery=discovery), self.assertRaises(ValueError):
                self.capture(detail, discovery)

    def test_old_or_incomplete_receipt_cannot_authorize_application(self):
        for expected in [None, {}, {"outside-family": DETAIL}]:
            with self.subTest(expected=expected), patch.object(rulesets, "ruleset_snapshot") as read:
                with self.assertRaisesRegex(ValueError, "complete managed"):
                    rulesets.require_ruleset_snapshot(INVENTORY, expected)
                read.assert_not_called()

    def test_every_retry_rereads_and_refuses_unrelated_live_drift(self):
        changed = copy.deepcopy(DETAIL)
        changed["unrelated_metadata"] = "concurrent change"
        with patch.object(rulesets, "ruleset_snapshot", side_effect=[{"bijux-iac": DETAIL}, {"bijux-iac": changed}]) as read:
            rulesets.require_ruleset_snapshot(INVENTORY, {"bijux-iac": DETAIL})
            with self.assertRaisesRegex(ValueError, "changed after planning"):
                rulesets.require_ruleset_snapshot(INVENTORY, {"bijux-iac": DETAIL})
            self.assertEqual(read.call_count, 2)
