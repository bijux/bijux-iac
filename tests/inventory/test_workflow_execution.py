"""Reject policy drift before workflow settings can be applied."""
import copy
import unittest

from scripts.inventory.repositories import load_inventory
from scripts.inventory.workflows import validate_workflow_execution, merged_workflow_execution


class WorkflowExecutionTests(unittest.TestCase):
    def test_all_twelve_use_review_only_proposals_with_the_explicit_masterclass_exception(self):
        inventory = load_inventory()
        validate_workflow_execution(inventory, require_standard=False)
        for repository in inventory['repositories']:
            policy = merged_workflow_execution(inventory, repository)
            self.assertEqual(policy['dependency_pull_requests'], 'notification-only')
            self.assertEqual(policy['dependency_merge'], 'owner-consolidation')
            self.assertEqual(policy['main_verification'], 'existing-events' if repository['name'] == 'bijux-masterclass' else 'accepted-pull-request')

    def test_missing_unknown_redundant_and_permissive_policy_fail_closed(self):
        original = load_inventory()
        for key in original['workflow_execution_defaults']:
            for value in (None, True, 'full-verification', 'automatic-merge'):
                inventory = copy.deepcopy(original)
                inventory['workflow_execution_defaults'][key] = value
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    validate_workflow_execution(inventory, require_standard=False)
        for repository in original['repositories']:
            inventory = copy.deepcopy(original)
            row = next(row for row in inventory['repositories'] if row['name'] == repository['name'])
            row['governance']['workflow_execution'] = {'dependency_merge': 'owner-consolidation'}
            with self.subTest(repository=row['name']), self.assertRaises(ValueError):
                validate_workflow_execution(inventory, require_standard=False)
