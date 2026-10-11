"""Keep the read-only governance plan verified by humans and inert for proposals."""
from __future__ import annotations

import copy
import json
import re
import unittest

from scripts.inventory.publication import workflow_policy
from scripts.inventory.repositories import ROOT


class GovernanceWorkflowAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.policy = workflow_policy()
        manifest = json.loads((ROOT / ".github/standards/repo-config.manifest.json").read_text())
        self.execution = next(entry["workflow_execution_policy"] for entry in manifest["repositories"]
                              if entry["name"] == "bijux-iac")
        self.path = ".github/workflows/github-governance-plan.yml"
        self.document = self.policy.parse_workflow((ROOT / self.path).read_bytes(), self.path)

    def test_governance_plan_has_no_duplicate_main_event_or_unverified_required_context(self):
        self.assertEqual(set(self.document["on"]), {"pull_request"})
        self.policy.validate_owned_execution({self.path: self.document}, self.execution)
        self.assertEqual(self.document["jobs"]["plan"]["needs"], "contracts")
        self.assertEqual(self.document["jobs"]["governance"]["needs"], ["contracts", "plan"])
        for author, branch, dependency in (("bijux", "governance/dependency-review-policy", False),
                                          ("contributor", "automation/dependency-lock-refresh", False),
                                          ("dependabot[bot]", "dependency/proposal", True),
                                          ("github-actions[bot]", "automation/dependency-lock-refresh", True),
                                          ("github-actions[bot]", "automation/documentation-preview", False)):
            for event in ("pull_request", "pull_request_target", "pull_request_review"):
                for identity, job in self.document["jobs"].items():
                    expression = job["if"][3:-2].strip()
                    expression = expression.replace("github.event_name", repr(event))
                    expression = expression.replace("github.event.pull_request.user.login", repr(author))
                    expression = expression.replace("github.event.pull_request.head.ref", repr(branch))
                    expression = expression.replace("always()", "True").replace("&&", " and ").replace("||", " or ")
                    with self.subTest(author=author, event=event, job=identity):
                        self.assertEqual(bool(eval(expression, {"__builtins__": {}}, {})), not dependency)
                        name = re.sub(r"\$\{\{(.*?)\}\}", lambda match: str(eval(
                            match.group(1).replace("github.event.pull_request.user.login", repr(author))
                            .replace("github.event.pull_request.head.ref", repr(branch))
                            .replace("&&", " and ").replace("||", " or "),
                            {"__builtins__": {}}, {})), job["name"])
                        expected = "iac / " + identity
                        self.assertEqual(name, ("unverified dependency / " if dependency else "") + expected)

    def test_missing_bot_guard_false_required_name_or_main_event_fails_conformance(self):
        for identity in self.document["jobs"]:
            for field in ("if", "name"):
                document = copy.deepcopy(self.document)
                document["jobs"][identity][field] = "${{ always() }}" if field == "if" else "iac / " + identity
                with self.subTest(job=identity, field=field), self.assertRaises(ValueError):
                    self.policy.validate_owned_execution({self.path: document}, self.execution)
        document = copy.deepcopy(self.document)
        document["on"]["push"] = {"branches": ["main"]}
        with self.assertRaisesRegex(ValueError, "duplicate push"):
            self.policy.validate_owned_execution({self.path: document}, self.execution)
