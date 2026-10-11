"""Keep PR-only producer evidence tied to current accepted source and real checks."""
import base64
import copy
import json
import unittest
from unittest.mock import patch

from scripts.github import checks
from scripts.inventory.repositories import load_inventory
from scripts.inventory.workflows import merged_workflow_execution

MAIN = 'a' * 40
HEAD = 'b' * 40


class AcceptedVerificationTests(unittest.TestCase):
    def setUp(self):
        self.inventory = load_inventory()
        self.inventory['repositories'] = self.inventory['repositories'][:1]
        self.repository = self.inventory['repositories'][0]
        self.contexts = self.repository['governance']['branch_protection']['required_status_checks']
        self.main = {'sha': MAIN, 'parents': [{'sha': 'c' * 40}, {'sha': HEAD}]}
        self.pr = {'number': 31, 'state': 'closed', 'merged_at': '2026-10-11T12:00:00Z',
                   'merge_commit_sha': MAIN, 'head': {'sha': HEAD}, 'base': {'ref': 'main', 'sha': 'c' * 40, 'repo': {'full_name': 'bijux/bijux-iac'}},
                   'user': {'login': 'bijux'}}
        self.policy = merged_workflow_execution(self.inventory, self.repository)
        self.runs = [{'id': number, 'head_sha': HEAD, 'name': context,
                      'app': {'id': 15368}, 'status': 'completed', 'conclusion': 'success'}
                     for number, context in enumerate(self.contexts, 1)]

    def evidence(self, *, main=None, prs=None, policy=None, runs=None, current=None):
        manifest = {'repositories': [{'name': 'bijux-iac', 'workflow_execution_policy':
                                      self.policy if policy is None else policy}]}
        encoded = base64.b64encode(json.dumps(manifest).encode()).decode()
        with patch.object(checks, 'gh_api_json', side_effect=[self.main if main is None else main,
                           [self.pr] if prs is None else prs, {'encoding': 'base64', 'content': encoded}, {'sha': MAIN} if current is None else current]), \
                patch.object(checks, 'check_runs', return_value=self.runs if runs is None else runs) as observed:
            receipt = checks.producer_evidence(self.inventory)
        return receipt, observed

    def test_current_normal_merge_uses_only_its_verified_pr_head(self):
        receipt, observed = self.evidence()
        self.assertEqual(receipt['status'], 'producers-verified')
        observed.assert_called_once_with('bijux-iac', HEAD)
        row = receipt['repositories'][0]
        self.assertEqual(row['verification_source'], 'accepted-pull-request')
        self.assertEqual(row['accepted_pr']['merge_commit'], MAIN)
        self.assertTrue(all(check['commit'] == HEAD for check in row['checks']))
        self.assertFalse(receipt['remote_writes'])

    def test_direct_squash_rebase_and_unrelated_merge_cannot_borrow_pr_success(self):
        for parents in ([], [{'sha': HEAD}], [{'sha': 'c' * 40}, {'sha': 'd' * 40}], [None, None]):
            with self.subTest(parents=parents):
                main = dict(self.main, parents=parents)
                receipt, observed = self.evidence(main=main)
                self.assertEqual(receipt['status'], 'producers-unverified')
                observed.assert_not_called()
        older = dict(self.pr, merge_commit_sha='e' * 40)
        for prs in ([], [older], [self.pr, self.pr]):
            with self.subTest(prs=prs):
                receipt, observed = self.evidence(prs=prs)
                self.assertEqual(receipt['status'], 'producers-unverified')
                observed.assert_not_called()

    def test_unadopted_consumer_policy_cannot_establish_pr_only_verification(self):
        for key in self.policy:
            policy = dict(self.policy)
            del policy[key]
            with self.subTest(key=key):
                receipt, observed = self.evidence(policy=policy)
                self.assertEqual(receipt['status'], 'producers-unverified')
                self.assertIn('has not adopted', receipt['errors'][0])
                observed.assert_not_called()

    def test_dependency_notice_and_skipped_checks_never_establish_verification(self):
        bot = copy.deepcopy(self.pr)
        bot['user']['login'] = 'dependabot[bot]'
        receipt, observed = self.evidence(prs=[bot])
        self.assertEqual(receipt['status'], 'producers-unverified')
        self.assertIn('notification', receipt['errors'][0])
        observed.assert_not_called()
        lock_proposal = copy.deepcopy(self.pr)
        lock_proposal['user']['login'] = 'github-actions[bot]'
        lock_proposal['head']['ref'] = 'automation/dependency-lock-refresh'
        receipt, observed = self.evidence(prs=[lock_proposal])
        self.assertEqual(receipt['status'], 'producers-unverified')
        observed.assert_not_called()
        lock_proposal['head']['ref'] = 'automation/documentation-preview'
        receipt, _ = self.evidence(prs=[lock_proposal])
        self.assertEqual(receipt['status'], 'producers-verified')
        for conclusion in ('skipped', 'failure', 'cancelled', None):
            runs = copy.deepcopy(self.runs)
            runs[0]['conclusion'] = conclusion
            if conclusion is None:
                runs[0]['status'] = 'in_progress'
            with self.subTest(conclusion=conclusion):
                receipt, _ = self.evidence(runs=runs)
                self.assertEqual(len(receipt['errors']), 1)
        notices = [dict(run, name='unverified dependency / ' + run['name']) for run in self.runs]
        receipt, _ = self.evidence(runs=notices)
        self.assertEqual(len(receipt['errors']), len(self.contexts))

    def test_latest_failed_or_foreign_check_cannot_borrow_older_success(self):
        for change in ({'id': 999, 'conclusion': 'failure'}, {'head_sha': 'd' * 40}, {'app': {'id': 999}}):
            runs = copy.deepcopy(self.runs)
            if 'id' in change:
                runs.append(dict(runs[0], **change))
            else:
                runs[0].update(change)
            with self.subTest(change=change):
                receipt, _ = self.evidence(runs=runs)
                self.assertEqual(len(receipt['errors']), 1)

    def test_wrong_repository_and_changed_base_cannot_establish_accepted_source(self):
        for change in ({'sha': 'd' * 40}, {'repo': {'full_name': 'foreign/repository'}},
                       {'repo': None}, {'ref': 'other'}):
            pr = copy.deepcopy(self.pr)
            pr['base'].update(change)
            with self.subTest(change=change):
                receipt, observed = self.evidence(prs=[pr])
                self.assertEqual(receipt['status'], 'producers-unverified')
                observed.assert_not_called()

    def test_moving_main_cannot_reuse_a_completed_observation(self):
        for current in ({'sha': 'd' * 40}, {}, None):
            if current is None:
                continue
            with self.subTest(current=current):
                receipt, _ = self.evidence(current=current)
                self.assertEqual(receipt['status'], 'producers-unverified')
                self.assertIn('main changed', receipt['errors'][0])
