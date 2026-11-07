"""Exercise the controller against the consumed exact-commit admission helper."""
from __future__ import annotations

import base64
import json
import os
import runpy
import unittest
from unittest.mock import patch

from scripts.execution import publication
from scripts.inventory.publication import workflow_policy
from scripts.inventory.repositories import ROOT


class ControllerProductCheckTests(unittest.TestCase):
    def test_effective_rules_cannot_drop_declared_product_checks(self):
        repository = 'bijux/bijux-ro-crate-node'
        commit, base, head = 'a' * 40, 'b' * 40, 'c' * 40
        common = {'policy / github', 'policy / pr approval', 'std / standard', 'std / report'}
        product = {'packages / node-22.23.4', 'packages / node-24.3.0',
                   'Python reference', 'Browser validation and draft lifecycle'}
        policy = workflow_policy()
        publisher = {
            'on': {'workflow_dispatch': {'inputs': {
                'accepted_commit': {'required': True}, 'release_tag': {'required': True},
                'candidate_run_id': {'required': True, 'type': 'string'},
            }}},
            'jobs': {'publication_admission': policy.publication.controller_admission_job('release-npm')},
        }
        content = {'content': base64.b64encode(json.dumps(publisher).encode()).decode()}
        load = runpy.run_path
        admission_path = str(ROOT / '.bijux/shared/bijux-gh/scripts/publication_admission.py')
        scope = load(admission_path)
        pull = {
            'number': 1, 'state': 'closed', 'merged': True, 'merged_at': '2026-11-07T00:00:00Z',
            'merge_commit_sha': commit, 'user': {'type': 'User', 'login': 'bijux'},
            'base': {'ref': 'main', 'sha': base, 'repo': {'full_name': repository}},
            'head': {'sha': head, 'repo': {'full_name': repository}},
        }

        def exercise(bound):
            def api(path):
                if path == 'users/bijux-publication[bot]':
                    return {'type': 'Bot', 'id': 123}
                if path in {f'repos/{repository}/commits/main', f'repos/{repository}/commits/v0.1.0'}:
                    return {'sha': commit, 'parents': [{'sha': base}, {'sha': head}]}
                if path == f'repos/{repository}/rules/branches/main':
                    return [{'type': 'required_status_checks', 'parameters': {'required_status_checks': [
                        {'context': name, 'integration_id': 15368} for name in sorted(bound)]}}]
                if path == f'repos/{repository}/pulls/1':
                    return pull
                raise AssertionError(path)

            runs = [{'id': index + 1, 'name': name, 'head_sha': head, 'app': {'id': 15368},
                     'status': 'completed', 'conclusion': 'success'}
                    for index, name in enumerate(sorted(bound))]
            with patch.dict(scope['admit'].__globals__, {'api': api,
                            'associated_pulls': lambda *_: [pull], 'check_runs': lambda *_: runs}), \
                    patch.object(publication.runpy, 'run_path',
                                 side_effect=lambda path: scope if path == admission_path else load(path)), \
                    patch.object(publication, 'gh_api_json', return_value=content) as fetch, \
                    patch.dict(os.environ, {'PUBLICATION_CONTROLLER_ACTOR_ID': '123'}):
                result = publication.admit_repository('bijux-ro-crate-node', 'release-npm', commit,
                                                      'v0.1.0', 'bijux-publication[bot]', '123')
                fetch.assert_called_once_with(
                    f'repos/{repository}/contents/.github/workflows/release-npm.yml?ref={commit}')
                return result

        for removed in [product, *[{name} for name in sorted(product)]]:
            with self.subTest(removed=removed), self.assertRaisesRegex(ValueError, 'canonical product check bindings'):
                exercise((common | product) - removed)
        admitted = exercise(common | product)
        self.assertEqual(set(admitted['required_commit_checks']), common | product)
        self.assertEqual(admitted['verification_commit'], head)
