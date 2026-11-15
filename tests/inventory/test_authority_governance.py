"""Desired authority policy never confers applied or publication authority."""

import copy
import unittest

from scripts.inventory import authority_governance


class AuthorityGovernanceTests(unittest.TestCase):
    def test_exact_desired_profiles_do_not_claim_applied_state(self):
        module = authority_governance
        policy = module.load_governance()
        module.validate_governance(policy, require_standard=False)
        self.assertEqual(policy["claim"], "desired")
        self.assertEqual(
            {r["name"] for r in policy["repositories"]}, {"bijux-std", "bijux-iac"}
        )
        for row in policy["repositories"]:
            self.assertFalse(row["publication_enabled"])
            self.assertEqual(row["github_mirror"]["app_id"], 5768636)
            self.assertEqual(
                row["github_mirror"]["required_check"],
                {"context": "gitlab / validation", "integration_id": 5768636},
            )
            self.assertEqual(
                row["canonical"]["main"],
                {
                    "push_access_level": 0,
                    "merge_access_level": 40,
                    "allow_force_push": False,
                },
            )
        ontology = policy["product_publication"]["bijux-ontology"]
        self.assertEqual(ontology["standard_capabilities"], ["common", "python"])
        self.assertEqual(ontology["entrypoints"], {})
        self.assertEqual(ontology["controller"], "iac")
        self.assertEqual(ontology["owner"], "bijux-ontology")

    def test_permission_identity_execution_and_claim_mutations_are_rejected(self):
        module = authority_governance
        policy = module.load_governance()
        paths = [("claim", "applied"), ("version", True)]
        for key, value in paths:
            altered = copy.deepcopy(policy)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                module.validate_governance(altered, require_standard=False)
        for modify in [
            lambda r: r["github_mirror"].update(app_id=True),
            lambda r: r["github_mirror"].update(actions_enabled=True),
            lambda r: r["github_mirror"].update(
                required_check={"context": "std / report", "integration_id": 15368}
            ),
            lambda r: r["github_mirror"].update(history_guard_bypass=[5768636]),
            lambda r: r["personal_mirror"].update(ci_enabled=True),
            lambda r: r["canonical"]["main"].update(push_access_level=40),
            lambda r: r["canonical"]["publication_environment"].update(
                deploy_access_level=30
            ),
            lambda r: r.update(publication_enabled=True),
        ]:
            altered = copy.deepcopy(policy)
            modify(altered["repositories"][0])
            with self.subTest(policy=altered), self.assertRaises(ValueError):
                module.validate_governance(altered, require_standard=False)

    def test_missing_accepted_ontology_capability_fails_closed(self):
        module = authority_governance
        with self.assertRaisesRegex(ValueError, "accepted.*fourteen|Ontology"):
            module.validate_governance(
                module.load_governance(), standard={"repositories": []}
            )

    def test_accepted_ontology_contract_requires_python_and_authored_events_without_a_publisher(
        self,
    ):
        from scripts.inventory.repositories import FAMILY_REPOSITORIES

        standard = {"repositories": [{"name": name} for name in FAMILY_REPOSITORIES]}
        ontology = next(
            row for row in standard["repositories"] if row["name"] == "bijux-ontology"
        )
        ontology.update(
            standard_capabilities=["common", "python"],
            workflow_execution_policy={
                "main_verification": "existing-events",
                "publication_entrypoints": {},
            },
        )
        policy = authority_governance.load_governance()
        authority_governance.validate_governance(policy, standard=standard)
        for change in (
            lambda row: row.update(standard_capabilities=["common"]),
            lambda row: row["workflow_execution_policy"].update(
                main_verification="accepted-pull-request"
            ),
            lambda row: row["workflow_execution_policy"].update(
                publication_entrypoints={"release-pypi": {}}
            ),
        ):
            changed = copy.deepcopy(standard)
            row = next(
                row
                for row in changed["repositories"]
                if row["name"] == "bijux-ontology"
            )
            change(row)
            with self.subTest(ontology=row), self.assertRaisesRegex(
                ValueError, "Ontology"
            ):
                authority_governance.validate_governance(policy, standard=changed)
