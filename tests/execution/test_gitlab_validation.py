"""Canonical GitLab validation must run real checks without claiming an apply plan."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from scripts.inventory.repositories import ROOT


class GitLabValidationTests(unittest.TestCase):
    def pipeline(self):
        path = ROOT / '.gitlab-ci.yml'
        self.assertTrue(path.is_file(), 'the canonical project needs an executable pipeline')
        result = subprocess.run(['ruby', '-ryaml', '-rjson', '-e',
                                 'puts JSON.generate(YAML.safe_load(STDIN.read, aliases: false))'],
                                input=path.read_text(), text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_pipeline_runs_real_contract_format_terraform_and_standards_gates(self):
        pipeline = self.pipeline()
        for job, command in {'contracts': 'make contract-tests',
                             'terraform-format': 'make terraform-format-check',
                             'terraform-validate': 'make terraform-validate',
                             'standards': 'make bijux-std-checks'}.items():
            with self.subTest(job=job):
                self.assertIn(command, pipeline[job]['script'])
                self.assertNotIn('allow_failure', pipeline[job])
        self.assertIn('scripts.execution.gitlab_validation', '\n'.join(pipeline['default']['before_script']))
        self.assertNotIn('TMPDIR', pipeline['variables'])
        bootstrap = pipeline['default']['before_script']
        self.assertLess(bootstrap.index('mkdir -p artifacts/runtime artifacts/gitlab'),
                        bootstrap.index('export TMPDIR=\"$CI_PROJECT_DIR/artifacts/runtime\"'))

    def test_pipeline_guards_canonical_project_and_avoids_duplicate_mr_pushes(self):
        rules = self.pipeline()['workflow']['rules']
        self.assertIn('bijux-oss/bijux-iac', rules[0]['if'])
        self.assertIn('88949971', rules[0]['if'])
        self.assertEqual(rules[0]['when'], 'never')
        self.assertTrue(any('CI_OPEN_MERGE_REQUESTS' in row.get('if', '')
                            and row.get('when') == 'never' for row in rules))
        self.assertEqual(rules[-1], {'when': 'never'})

    def test_live_plan_is_visible_blocking_manual_gate_without_privileged_execution(self):
        pipeline = self.pipeline()
        job = pipeline['governance-plan']
        self.assertEqual(job['environment'], {'name': 'governance-plan'})
        self.assertEqual(job['resource_group'], 'governance-plan')
        self.assertEqual(job['allow_failure'], False)
        self.assertEqual(job['rules'][0]['when'], 'manual')
        self.assertIn('CI_COMMIT_REF_PROTECTED', job['rules'][0]['if'])
        self.assertIn('CI_DEFAULT_BRANCH', job['rules'][0]['if'])
        self.assertIn('blocked-plan', '\n'.join(job['script']))
        self.assertNotIn('scripts.execution.application', '\n'.join(job['script']))
        self.assertNotIn('GITHUB_', (ROOT / '.gitlab-ci.yml').read_text())
        blocked = pipeline['governance-plan-unavailable']
        self.assertEqual(blocked['rules'][0]['when'], 'never')
        self.assertEqual(blocked['rules'][0]['if'], job['rules'][0]['if'])
        self.assertEqual(blocked['rules'][-1], {'when': 'on_success'})
        self.assertIn('blocked-plan', '\n'.join(blocked['script']))
        self.assertNotIn('environment', blocked)
        self.assertNotIn('allow_failure', blocked)

    def test_validation_context_binds_checkout_and_rejects_mirror_and_spoofed_sha(self):
        from scripts.execution import gitlab_validation
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        environment = {
            'CI_SERVER_URL': 'https://gitlab.com',
            'CI_PROJECT_PATH': 'bijux-oss/bijux-iac',
            'CI_PROJECT_ID': gitlab_validation.PROJECT_ID,
            'CI_COMMIT_SHA': commit,
            'CI_PIPELINE_ID': '123', 'CI_JOB_ID': '456',
            'CI_PIPELINE_SOURCE': 'merge_request_event',
            'CI_COMMIT_REF_NAME': 'ci/gitlab-authority',
            'CI_COMMIT_REF_PROTECTED': 'false',
        }
        receipt = gitlab_validation.context(environment)
        self.assertEqual(receipt['commit'], commit)
        self.assertEqual(receipt['pipeline_id'], '123')
        self.assertEqual(receipt['job_id'], '456')
        self.assertEqual(receipt['authority'], 'validation-only')
        for key, value in [('CI_PROJECT_ID', '999'), ('CI_PROJECT_PATH', 'bijux/bijux-iac'),
                           ('CI_SERVER_URL', 'https://example.com'), ('CI_COMMIT_SHA', 'a' * 40),
                           ('CI_PIPELINE_ID', ''), ('CI_JOB_ID', '0'),
                           ('CI_PIPELINE_SOURCE', 'parent_pipeline'), ('CI_COMMIT_REF_NAME', ''),
                           ('CI_COMMIT_REF_PROTECTED', 'yes')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                gitlab_validation.context({**environment, key: value})

    def test_blocked_plan_exits_unsuccessfully_and_records_no_remote_writes(self):
        result = subprocess.run([sys.executable, '-B', '-m', 'scripts.execution.gitlab_validation', 'blocked-plan'],
                                cwd=ROOT, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dedicated read-only GitHub credential', result.stderr)
        path = ROOT / 'artifacts/gitlab/governance-plan-blocked.json'
        self.assertTrue(path.exists())
        receipt = json.loads(path.read_text())
        self.assertEqual(receipt['status'], 'blocked')
        self.assertIs(receipt['remote_writes'], False)
        self.assertIs(receipt['application_ready'], False)
