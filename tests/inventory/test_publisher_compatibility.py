"""Documentation-only equivalence preserves exact publisher admission policy."""

import copy
import json
from pathlib import Path
import unittest

from scripts.inventory.publication import validate_publisher, workflow_policy


class DocumentationAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.policy = workflow_policy()
        # Actual Hub deploy-docs admission at this immutable accepted source:
        # https://github.com/bijux/bijux.github.io/blob/8bc852f739cb3656dd04bf9371b8a52c8a3a6a01/.github/workflows/deploy-docs.yml
        self.document = json.loads(
            Path(__file__).with_name("fixtures").joinpath(
                "hub-documentation-admission.json"
            ).read_text()
        )

    def test_historical_hub_docs_tag_expression_is_equivalent_and_not_mutated(self):
        original = copy.deepcopy(self.document)
        validate_publisher(self.policy, "deploy-docs", self.document)
        self.assertEqual(self.document, original)

    def test_declared_release_tag_input_prevents_documentation_equivalence(self):
        for declaration in ({"type": "string"}, {"type": "string", "required": True}):
            changed = copy.deepcopy(self.document)
            changed["on"]["workflow_dispatch"]["inputs"]["release_tag"] = declaration
            with self.subTest(declaration=declaration), self.assertRaises(ValueError):
                validate_publisher(self.policy, "deploy-docs", changed)

    def test_case_alias_of_release_tag_prevents_documentation_equivalence(self):
        for name in ("RELEASE_TAG", "Release_Tag", "rElEaSe_tAg"):
            changed = copy.deepcopy(self.document)
            changed["on"]["workflow_dispatch"]["inputs"][name] = {
                "type": "string",
                "default": "v1.2.3",
            }
            with self.subTest(input=name), self.assertRaises(ValueError):
                validate_publisher(self.policy, "deploy-docs", changed)

    def test_historical_expression_does_not_hide_other_admission_changes(self):
        changes = {
            "actor": lambda job: job["steps"][1]["env"].update(PUBLICATION_ACTOR="bijux"),
            "checkout": lambda job: job["steps"][0]["with"].update(ref="main"),
            "credential": lambda job: job["steps"][1]["env"].update(GH_TOKEN="other"),
            "permission": lambda job: job["permissions"].update(contents="write"),
            "script": lambda job: job["steps"][1].update(run="echo admitted"),
            "extra-step": lambda job: job["steps"].append({"run": "echo admitted"}),
        }
        for name, change in changes.items():
            changed = copy.deepcopy(self.document)
            change(changed["jobs"]["publication_admission"])
            with self.subTest(change=name), self.assertRaises(ValueError):
                validate_publisher(self.policy, "deploy-docs", changed)

    def test_only_exact_historical_tag_expression_is_compatible(self):
        for expression in ("${{ inputs.release_tag }}", "v1.2.3", "${{ inputs.accepted_commit || '' }}"):
            changed = copy.deepcopy(self.document)
            changed["jobs"]["publication_admission"]["steps"][1]["env"]["PUBLICATION_TAG"] = expression
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                validate_publisher(self.policy, "deploy-docs", changed)

    def test_release_publisher_does_not_accept_documentation_fallback(self):
        document = {
            "on": {"workflow_dispatch": {"inputs": {
                "accepted_commit": {"required": True},
                "release_tag": {"required": True},
            }}},
            "jobs": {"publication_admission": self.policy.publication.controller_admission_job("release-pypi")},
        }
        validate_publisher(self.policy, "release-pypi", document)
        document["jobs"]["publication_admission"]["steps"][1]["env"]["PUBLICATION_TAG"] = "${{ inputs.release_tag || '' }}"
        with self.assertRaises(ValueError):
            validate_publisher(self.policy, "release-pypi", document)

    def test_canonical_documentation_admission_remains_accepted(self):
        self.document["jobs"]["publication_admission"]["steps"][1]["env"]["PUBLICATION_TAG"] = ""
        validate_publisher(self.policy, "deploy-docs", self.document)
