"""Native anonymous plans bind actual source identity without application authority."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.inventory.repositories import ROOT


class NativePlanTests(unittest.TestCase):
    def setUp(self):
        self.sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        self.environment = {'CI_SERVER_URL': 'https://gitlab.com', 'CI_PROJECT_PATH': 'bijux-oss/bijux-iac',
                            'CI_PROJECT_ID': '88949971', 'CI_PIPELINE_ID': '123', 'CI_JOB_ID': '456',
                            'CI_JOB_NAME': 'governance-plan', 'CI_COMMIT_SHA': self.sha,
                            'CI_PIPELINE_SOURCE': 'merge_request_event', 'CI_COMMIT_REF_NAME': 'ci/gitlab-authority',
                            'CI_COMMIT_REF_PROTECTED': 'false', 'CI_MERGE_REQUEST_IID': '1'}
        self.responses = {
            '': {'id': 88949971, 'path_with_namespace': 'bijux-oss/bijux-iac', 'default_branch': 'main'},
            '/pipelines/123': {'id': 123, 'project_id': 88949971, 'sha': self.sha,
                               'source': 'merge_request_event', 'ref': 'refs/merge-requests/1/head'},
            '/pipelines/123/jobs?per_page=100&page=1': [{'id': 456, 'name': 'governance-plan', 'status': 'running',
                                                       'pipeline': {'id': 123}, 'commit': {'id': self.sha}}],
            '/merge_requests/1': {'iid': 1, 'project_id': 88949971, 'state': 'opened', 'sha': self.sha,
                                  'source_project_id': 88949971, 'target_project_id': 88949971,
                                  'source_branch': 'ci/gitlab-authority', 'target_branch': 'main'},
            '/repository/branches/ci%2Fgitlab-authority': {'name': 'ci/gitlab-authority', 'protected': False,
                                                          'commit': {'id': self.sha}},
        }

    def admit(self, environment=None, responses=None):
        from scripts.execution.gitlab_plan import admit
        return admit(self.environment if environment is None else environment,
                     read=lambda suffix: copy.deepcopy((self.responses if responses is None else responses)[suffix]))

    def test_plan_admission_binds_native_running_job_and_exact_same_project_mr_head(self):
        admitted = self.admit()
        self.assertEqual(admitted['authority'], 'read-only-plan')
        self.assertEqual(admitted['merge_request_iid'], 1)
        self.assertEqual(admitted['commit'], self.sha)
        self.assertFalse(admitted['application_ready'])
        self.assertFalse(admitted['remote_writes'])

    def test_mr_fork_stale_head_wrong_target_or_wrong_native_job_is_rejected(self):
        for path, key, value in [
            ('/merge_requests/1', 'source_project_id', 999),
            ('/merge_requests/1', 'sha', 'a' * 40),
            ('/merge_requests/1', 'state', 'closed'),
            ('/merge_requests/1', 'target_branch', 'other'),
            ('/merge_requests/1', 'source_branch', 'other'),
            ('/pipelines/123', 'source', 'push'),
            ('/pipelines/123', 'sha', 'a' * 40),
            ('', 'id', 999),
        ]:
            data = copy.deepcopy(self.responses)
            data[path][key] = value
            with self.subTest(path=path, key=key), self.assertRaises(ValueError):
                self.admit(responses=data)
        for key, value in [('id', 999), ('name', 'contracts'), ('status', 'success'),
                           ('pipeline', {'id': 999}), ('commit', {'id': 'a' * 40})]:
            data = copy.deepcopy(self.responses)
            data['/pipelines/123/jobs?per_page=100&page=1'][0][key] = value
            with self.subTest(job_key=key), self.assertRaises(ValueError):
                self.admit(responses=data)

    def test_branch_plan_binds_current_native_branch_without_claiming_protected_authority(self):
        environment = {**self.environment, 'CI_PIPELINE_SOURCE': 'push'}
        environment.pop('CI_MERGE_REQUEST_IID')
        responses = copy.deepcopy(self.responses)
        responses['/pipelines/123'].update(source='push', ref='ci/gitlab-authority')
        result = self.admit(environment, responses)
        self.assertFalse(result['protected_ref'])
        self.assertFalse(result['application_ready'])
        for key, value in [('protected', True), ('name', 'other'), ('commit', {'id': 'a' * 40})]:
            data = copy.deepcopy(responses)
            data['/repository/branches/ci%2Fgitlab-authority'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.admit(environment, data)

    def test_web_and_schedule_require_actual_protected_default_branch(self):
        for source in ['web', 'schedule']:
            environment = {**self.environment, 'CI_PIPELINE_SOURCE': source, 'CI_COMMIT_REF_NAME': 'main',
                           'CI_COMMIT_REF_PROTECTED': 'true'}
            environment.pop('CI_MERGE_REQUEST_IID')
            data = copy.deepcopy(self.responses)
            data['/pipelines/123'].update(source=source, ref='main')
            data['/repository/branches/main'] = {'name': 'main', 'protected': True, 'commit': {'id': self.sha}}
            self.assertEqual(self.admit(environment, data)['ref'], 'main')
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.admit({**environment, 'CI_COMMIT_REF_PROTECTED': 'false'}, data)

    def test_anonymous_child_cannot_inherit_tokens_provider_overrides_or_local_sessions(self):
        from scripts.execution.gitlab_plan import anonymous_environment
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            environment = {'PATH': '/usr/bin:/bin', 'HOME': '/sensitive', 'GH_TOKEN': 'secret',
                           'GITHUB_TOKEN': 'secret', 'GITHUB_APP_ID': '1', 'GITHUB_BASE_URL': 'https://evil.test',
                           'GH_CONFIG_DIR': '/sensitive', 'GH_PATH': '/usr/local/bin/gh',
                           'TF_VAR_github_token': 'secret', 'TF_VAR_github_owner': 'other',
                           'TF_CLI_ARGS_plan': '-target=wrong', 'TF_CLI_CONFIG_FILE': '/sensitive',
                           'CI_JOB_TOKEN': 'secret', 'HTTPS_PROXY': 'https://evil.test', 'ARBITRARY_SECRET': 'secret'}
            result = anonymous_environment(environment, 'http://127.0.0.1:43210/api/v3', Path(directory))
            self.assertFalse(any(value == 'secret' for value in result.values()))
            self.assertNotIn('TF_CLI_ARGS_plan', result)
            self.assertNotIn('GITHUB_APP_ID', result)
            self.assertNotIn('CI_JOB_TOKEN', result)
            self.assertNotIn('HTTPS_PROXY', result)
            self.assertEqual(result['TF_VAR_github_token'], '')
            self.assertEqual(result['TF_VAR_github_owner'], 'bijux')
            self.assertEqual(result['GITHUB_BASE_URL'], 'http://127.0.0.1:43210/api/v3/')
            self.assertEqual(result['GITHUB_LEGACY_CLIENT'], 'false')
            self.assertTrue(Path(result['HOME']).is_dir())
            self.assertTrue(Path(result['TMPDIR']).is_dir())
            self.assertTrue(Path(result['HOME']).is_relative_to(Path(directory)))

    def test_native_plan_receipt_binds_ci_configuration_and_does_not_accept_privileged_receipt(self):
        from scripts.execution.gitlab_plan import complete_receipt
        from scripts.execution.application import input_digests
        plan = {'status': 'planned', 'privileged': False, 'commit': self.sha, 'remote_writes': False,
                'input_digests': input_digests(),
                'ruleset_plan': [], 'plan_digest': 'a' * 64}
        result = complete_receipt(self.admit(), plan)
        self.assertEqual(result['status'], 'planned')
        self.assertFalse(result['application_ready'])
        self.assertEqual(result['github_authentication'], 'anonymous')
        self.assertEqual(len(result['native_input_digests']['.gitlab-ci.yml']), 64)
        for update in [{'privileged': True}, {'remote_writes': True}, {'status': 'preflight'}, {'commit': 'b' * 40}, {'input_digests': {}}]:
            with self.subTest(update=update), self.assertRaises(ValueError):
                complete_receipt(self.admit(), {**plan, **update})

    def test_tracked_and_untracked_source_mutations_fail_source_integrity(self):
        from scripts.execution.gitlab_plan import require_clean_source
        for status in [' M scripts/execution/application.py\n', '?? scripts/unowned.py\n']:
            with self.subTest(status=status), patch('scripts.execution.gitlab_plan.subprocess.check_output', return_value=status):
                with self.assertRaisesRegex(ValueError, 'clean exact source checkout'):
                    require_clean_source()
        with patch('scripts.execution.gitlab_plan.subprocess.check_output', return_value=''):
            require_clean_source()
