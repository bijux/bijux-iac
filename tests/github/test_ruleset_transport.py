from __future__ import annotations

import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from scripts.github import ruleset_transport as transport
from tests.github.test_audit import RulesetAuditTests


def before_image(name="bijux-iac"):
    return {**RulesetAuditTests.healthy_ruleset(), "id": 123, "source": f"bijux/{name}",
            "source_type": "Repository", "updated_at": "original", "node_id": "retained-node",
            "_links": {"self": {"href": "retained-link"}}}


def inventory(name="bijux-iac", checks=None):
    return {"repositories": [{"name": name, "governance": {"branch_protection": {
        "required_status_checks": checks or ["example", "iac / governance"]}}}]}


class ApiRulesetTransportTests(unittest.TestCase):
    def test_actual_api_only_parameters_and_unrelated_rule_survive_round_trip(self):
        before = before_image()
        before["rules"][2]["parameters"].update(
            require_extra_approval_for_unattributed_changes=True,
            required_reviewers=[{"minimum_approvals": 1, "reviewer": {"id": 7, "type": "Team"},
                                 "file_patterns": ["**/*.py"]}])
        before["rules"].append({"type": "required_signatures"})
        original = copy.deepcopy(before)
        operation = transport.api_plan(inventory(), {"bijux-iac": before})[0]
        self.assertEqual(before, original)
        self.assertEqual(operation["body"]["rules"][:3], original["rules"][:3])
        self.assertEqual(operation["body"]["rules"][-1], original["rules"][-1])
        self.assertEqual(json.loads(json.dumps(operation["body"])), operation["body"])
        response = {**operation["after"], "updated_at": "server-modified"}
        with patch.object(transport, "gh_api_json", side_effect=[before, response]), \
                patch.object(transport.subprocess, "run") as write:
            self.assertEqual(transport.apply_api_operation(operation), response)
        self.assertEqual(json.loads(write.call_args.kwargs["input"]), operation["body"])
        self.assertIn("PUT", write.call_args.args[0])
        self.assertNotIn("bypass_actors", json.loads(write.call_args.kwargs["input"]))

    def test_unchanged_plan_is_a_no_op_and_never_writes(self):
        before = before_image()
        op = transport.api_plan(inventory(checks=["example"]), {"bijux-iac": before})[0]
        self.assertEqual(op["actions"], ["no-op"])
        self.assertEqual(op["after"], before)
        with patch.object(transport, "gh_api_json", return_value=before), \
                patch.object(transport.subprocess, "run") as write:
            transport.apply_api_operation(op)
        write.assert_not_called()

    def test_drift_or_removed_api_only_field_refuses(self):
        before = before_image()
        before["rules"][2]["parameters"]["require_extra_approval_for_unattributed_changes"] = True
        op = transport.api_plan(inventory(), {"bijux-iac": before})[0]
        for stage in ("before", "after"):
            changed = copy.deepcopy(op[stage])
            del changed["rules"][2]["parameters"]["require_extra_approval_for_unattributed_changes"]
            reads = [changed] if stage == "before" else [before, changed]
            with self.subTest(stage=stage), patch.object(transport, "gh_api_json", side_effect=reads), \
                    patch.object(transport.subprocess, "run") as write, self.assertRaises(ValueError):
                transport.apply_api_operation(op)
            self.assertEqual(write.call_count, 0 if stage == "before" else 1)

    def test_unrelated_baseline_changes_absence_and_binding_removal_refuse(self):
        for change in (lambda b: b.update(bypass_actors=[{"actor_id": 1}]),
                       lambda b: b.update(enforcement="disabled"),
                       lambda b: b["rules"][-1]["parameters"]["required_status_checks"][0].update(integration_id=999),
                       lambda b: b["conditions"]["ref_name"].update(exclude=["refs/heads/main"]),
                       lambda b: b["rules"].append(copy.deepcopy(b["rules"][-1]))):
            before = before_image()
            change(before)
            with self.assertRaises(ValueError):
                transport.api_plan(inventory(), {"bijux-iac": before})
        for snapshots in ({}, {"bijux-iac": None}):
            with self.assertRaises(ValueError):
                transport.api_plan(inventory(), snapshots)
        with self.assertRaisesRegex(ValueError, "remove or replace"):
            transport.api_plan(inventory(checks=["other"]), {"bijux-iac": before_image()})

    def test_only_pollenomics_main_selector_is_narrowly_replaced(self):
        before = before_image("bijux-pollenomics")
        before["conditions"]["ref_name"]["include"] = ["refs/heads/main"]
        op = transport.api_plan(inventory("bijux-pollenomics"), {"bijux-pollenomics": before})[0]
        self.assertEqual(op["after"]["conditions"]["ref_name"]["include"], ["~DEFAULT_BRANCH"])
        before = before_image()
        before["conditions"]["ref_name"]["include"] = ["refs/heads/main"]
        with self.assertRaises(ValueError):
            transport.api_plan(inventory(), {"bijux-iac": before})

    def test_failed_write_is_not_relabelled_as_success(self):
        before = before_image()
        op = transport.api_plan(inventory(), {"bijux-iac": before})[0]
        with patch.object(transport, "gh_api_json", return_value=before) as read, \
                patch.object(transport.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["gh"])), \
                self.assertRaises(subprocess.CalledProcessError):
            transport.apply_api_operation(op)
        read.assert_called_once()
