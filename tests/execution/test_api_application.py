from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.execution import application
from scripts.github.ruleset_transport import API_VERSION, api_plan
from tests.github.test_ruleset_transport import before_image, inventory


class ApiApplicationTests(unittest.TestCase):
    def test_protected_api_preflight_binds_complete_plan_and_rereads_without_writes(self):
        inv = inventory()
        images = {"bijux-iac": before_image()}
        # Keep all generated test output under the owning repository artifacts.
        with tempfile.TemporaryDirectory(dir=application.ROOT / "artifacts") as directory:
            path = Path(directory)
            with patch.object(application, "ARTIFACTS", path), patch.object(application, "API_PLAN", path / "rulesets.json"), \
                    patch.object(application, "validated_inventory", return_value=inv), \
                    patch.object(application, "require_accepted_main") as accepted, \
                    patch.object(application, "require_producers", return_value={"status": "producers-verified"}), \
                    patch.object(application, "git_head", return_value="a" * 40), \
                    patch.object(application, "input_digests", return_value={"lock": "digest"}), \
                    patch.object(application, "settings_plan", return_value={}), \
                    patch.object(application, "ruleset_snapshot", return_value=images), \
                    patch.object(application, "require_ruleset_snapshot") as reread, \
                    patch.object(application, "write_receipt"), patch.object(application.subprocess, "run"), \
                    patch.object(application, "apply_api_operation") as writes:
                receipt = application.preflight(True, "github-api")
                application.verify_receipt(receipt)
                self.assertEqual(receipt["ruleset_plan"], api_plan(inv, images))
                self.assertIs(receipt["remote_writes"], False)
                self.assertEqual(receipt["transport"], "github-api")
                changed = json.loads(application.API_PLAN.read_text())
                changed[0]["body"]["rules"][2]["parameters"]["require_last_push_approval"] = True
                application.API_PLAN.write_text(json.dumps(changed))
                receipt["plan_digest"] = hashlib.sha256(application.API_PLAN.read_bytes()).hexdigest()
                with self.assertRaisesRegex(ValueError, "inventory-bound"):
                    application.verify_receipt(receipt)
            accepted.assert_called_once()
            reread.assert_called_once_with(inv, images)
            writes.assert_not_called()

    def test_unprivileged_api_transport_and_unknown_choice_refuse(self):
        with patch.object(application, "require_accepted_main") as accepted:
            for privileged, transport in [(False, "github-api"), (True, "unknown")]:
                with self.assertRaises(ValueError):
                    application.preflight(privileged, transport)
            accepted.assert_not_called()

    def test_partial_api_failure_retains_completed_and_outstanding_operations(self):
        inv = inventory()
        inv["repositories"].append({**copy.deepcopy(inv["repositories"][0]), "name": "bijux-std"})
        images = {name: before_image(name) for name in ("bijux-iac", "bijux-std")}
        receipt = {"transport": "github-api", "api_version": API_VERSION, "settings": {},
                   "ruleset_before_images": images, "ruleset_plan": api_plan(inv, images), "completed": []}
        with patch.object(application, "validated_inventory", return_value=inv), \
                patch.object(application, "require_accepted_main"), patch.object(application, "verify_receipt"), \
                patch.object(application, "settings_plan", return_value={}), \
                patch.object(application, "require_ruleset_snapshot"), patch.object(application, "write_receipt"), \
                patch.object(application, "apply_api_operation", side_effect=[images["bijux-iac"], ValueError("live drift")]), \
                patch.object(application, "terraform") as terraform, \
                patch.object(application, "audit", return_value=["bijux-std: missing required check"]):
            with self.assertRaisesRegex(ValueError, "live drift"):
                application.apply(receipt)
        self.assertEqual(receipt["status"], "failed")
        self.assertIn("ruleset:bijux-iac", receipt["completed"])
        self.assertIn("ruleset:bijux-std", receipt["outstanding"])
        self.assertIn("audit:family", receipt["outstanding"])
        terraform.assert_not_called()
