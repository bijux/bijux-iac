from __future__ import annotations

import copy
import unittest

from scripts.terraform.plans import OWNED_PARAMETERS, require_representable_rulesets, validate_ruleset_changes

ADDRESS = 'github_repository_ruleset.main["bijux-iac"]'


def resource(before, after, actions=None):
    return {"mode": "managed", "address": ADDRESS,
            "change": {"actions": actions or ["update"], "before": {"rules": [before]},
                       "after": {"rules": [after]}, "after_unknown": {}}}


class RulesetPlanCustodyTests(unittest.TestCase):
    def schema(self):
        rules = {"attributes": {"deletion": {}, "non_fast_forward": {}},
                 "block_types": {name: {"block": {"attributes": {key: {} for key in parameters}}}
                                 for name, parameters in OWNED_PARAMETERS.items()}}
        return {"provider_schemas": {"registry.terraform.io/integrations/github": {"resource_schemas": {
            "github_repository_ruleset": {"block": {"block_types": {"rules": {"block": rules}}}}}}}}

    def test_actual_api_only_parameter_refuses_privileged_application(self):
        snapshots = {"bijux-iac": {"rules": [{"type": "pull_request", "parameters": {
            "required_approving_review_count": 0, "require_extra_approval_for_unattributed_changes": True}}]}}
        with self.assertRaisesRegex(ValueError, "pull_request.require_extra_approval_for_unattributed_changes"):
            require_representable_rulesets(snapshots, self.schema())

    def test_known_api_names_are_bound_to_actual_provider_schema(self):
        snapshots = {"bijux-iac": {"rules": [{"type": "deletion"}, {"type": "required_status_checks",
                     "parameters": {"required_status_checks": [{"context": "iac / governance", "integration_id": 15368}],
                                    "strict_required_status_checks_policy": True}}]}, "bijux-std": None}
        require_representable_rulesets(snapshots, self.schema())

    def test_missing_schema_unknown_rules_and_unknown_false_parameters_refuse(self):
        for snapshots, schema in [({}, {}), ({"bijux-iac": {"rules": [{"type": "unknown"}]}}, self.schema()),
                                  ({"bijux-iac": {"rules": [{"type": "pull_request", "parameters": {"unknown": False}}]}}, self.schema())]:
            with self.subTest(snapshots=snapshots), self.assertRaises(ValueError):
                require_representable_rulesets(snapshots, schema)

    def test_authored_checks_can_change_without_erasing_unrelated_protection(self):
        before = {"required_status_checks": [{"required_check": [{"context": "policy / github"}]}], "required_signatures": True}
        after = {**before, "required_status_checks": [{"required_check": [{"context": "iac / governance"}]}]}
        validate_ruleset_changes([resource(before, after)], {ADDRESS})

    def test_removal_or_change_of_unrelated_protection_refuses(self):
        for before, after in [({"required_signatures": True}, {"required_signatures": False}),
                              ({"required_deployments": [{"environments": ["production"]}]}, {}),
                              ({"creation": False}, {"creation": True})]:
            with self.subTest(before=before), self.assertRaisesRegex(ValueError, "outside the authored"):
                validate_ruleset_changes([resource(before, after)], {ADDRESS})

    def test_inactive_optional_provider_representations_are_equivalent(self):
        validate_ruleset_changes([resource({"creation": False, "required_deployments": None},
                                           {"creation": None, "required_deployments": []})], {ADDRESS})

    def test_unowned_parameters_inside_authored_rule_cannot_be_erased(self):
        before = {"pull_request": [{"required_approving_review_count": 0,
                                    "require_extra_approval_for_unattributed_changes": True}]}
        after = {"pull_request": [{"required_approving_review_count": 0}]}
        with self.assertRaisesRegex(ValueError, "outside the authored"):
            validate_ruleset_changes([resource(before, after)], {ADDRESS})
        after["pull_request"][0]["require_extra_approval_for_unattributed_changes"] = True
        validate_ruleset_changes([resource(before, after)], {ADDRESS})

    def test_unknown_unrelated_rule_cannot_authorize_a_saved_plan(self):
        change = resource({}, {})
        change["change"]["after_unknown"] = {"rules": [{"required_signatures": True}]}
        with self.assertRaisesRegex(ValueError, "cannot prove preservation"):
            validate_ruleset_changes([change], {ADDRESS})

    def test_duplicate_unowned_destructive_and_malformed_operations_refuse(self):
        valid = resource({}, {})
        for changes in [[valid, copy.deepcopy(valid)], [{**valid, "address": "unowned"}],
                        [resource({}, {}, ["delete", "create"])], [resource({}, {}, ["read"])],
                        [{**valid, "mode": "unknown"}], [None], {}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_ruleset_changes(changes, {ADDRESS})
