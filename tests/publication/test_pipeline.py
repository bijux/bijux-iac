"""Keep manual publication inputs isolated from validation and automatic mirrors."""
from __future__ import annotations

import json
import shlex
import subprocess
import unittest
from unittest.mock import patch

from scripts.execution import gitlab_validation
from scripts.inventory.repositories import ROOT

REQUEST_FIELDS = (
    'PUBLICATION_OPERATION', 'PUBLICATION_TARGET_REPOSITORY', 'PUBLICATION_TARGET_WORKFLOW',
    'PUBLICATION_TARGET_COMMIT', 'PUBLICATION_TARGET_TAG', 'PUBLICATION_TARGET_CANDIDATE_RUN',
    'PUBLICATION_TARGET_PIPELINE_ID',
)
SAFE_DOCUMENTS = '''documents = YAML.parse_stream(STDIN.read).children.map { |doc|
  stream = Psych::Nodes::Stream.new; stream.children << doc
  YAML.safe_load(stream.to_yaml, aliases: false)
}; puts JSON.generate(documents)'''


def documents(path):
    result = subprocess.run(['ruby', '-ryaml', '-rjson', '-e', SAFE_DOCUMENTS],
                            input=path.read_text(), text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


class PublicationPipelineTests(unittest.TestCase):
    def parent(self):
        return documents(ROOT / '.gitlab-ci.yml')

    def test_parent_inputs_default_to_no_request_and_preflight_with_empty_targets(self):
        docs = self.parent()
        self.assertEqual(len(docs), 2, 'Native requests require a typed inputs header')
        inputs = docs[0]['spec']['inputs']
        self.assertEqual(set(inputs), {'BIJUX_PUBLICATION_REQUEST', *REQUEST_FIELDS})
        self.assertEqual(inputs['BIJUX_PUBLICATION_REQUEST'],
                         {'type': 'string', 'default': '0', 'options': ['0', '1']})
        self.assertEqual(inputs['PUBLICATION_OPERATION'], {'type': 'string', 'default': 'preflight',
                         'options': ['verify-credential', 'preflight', 'dispatch']})
        for name in REQUEST_FIELDS[1:]:
            self.assertEqual(inputs[name], {'type': 'string', 'default': ''})

    def test_request_bridge_passes_typed_inputs_and_only_the_actual_parent_id_as_a_variable(self):
        pipeline = self.parent()[-1]
        self.assertIn('publish / request', pipeline, 'The manual request needs a separate native bridge')
        bridge = pipeline['publish / request']
        self.assertEqual(bridge['stage'], 'publication')
        self.assertEqual(bridge['needs'], ['governance-plan'])
        self.assertEqual(bridge['inherit'], {'variables': False})
        self.assertEqual(bridge['variables'], {'BIJUX_PARENT_PIPELINE_ID': '$CI_PIPELINE_ID'})
        self.assertEqual(bridge['trigger'], {'include': [{'local': '.gitlab/publication-control.yml',
            'inputs': {name: '$[[ inputs.' + name + ' ]]' for name in REQUEST_FIELDS}}],
            'strategy': 'depend', 'forward': {'yaml_variables': True, 'pipeline_variables': False}})
        self.assertIs(bridge['interruptible'], False)
        self.assertNotIn('environment', bridge)
        self.assertNotIn('script', bridge)
        rule = bridge['rules'][0]['if']
        for predicate in ('"$[[ inputs.BIJUX_PUBLICATION_REQUEST ]]" == "1"',
                          '$CI_PIPELINE_SOURCE == "web"', '$CI_PIPELINE_SOURCE == "api"',
                          '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH', '$CI_COMMIT_REF_PROTECTED == "true"'):
            self.assertIn(predicate, rule)
        self.assertEqual(bridge['rules'][-1], {'when': 'never'})

    def test_api_workflow_requires_typed_request_and_validation_receives_compiled_selector(self):
        pipeline = self.parent()[-1]
        api_rules = [row for row in pipeline['workflow']['rules'] if '"api"' in row.get('if', '')]
        self.assertEqual(len(api_rules), 1)
        for predicate in ('"$[[ inputs.BIJUX_PUBLICATION_REQUEST ]]" == "1"',
                          '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH', '$CI_COMMIT_REF_PROTECTED == "true"'):
            self.assertIn(predicate, api_rules[0]['if'])
        self.assertEqual(pipeline['variables']['BIJUX_PUBLICATION_REQUEST'],
                         '$[[ inputs.BIJUX_PUBLICATION_REQUEST ]]')
        self.assertEqual(pipeline['variables']['PUBLICATION_OPERATION'], '$[[ inputs.PUBLICATION_OPERATION ]]')

    def test_manual_requests_cannot_select_the_automatic_mirror_bridge(self):
        rule = self.parent()[-1]['publish / mirrors']['rules'][0]['if']
        self.assertIn('"$[[ inputs.BIJUX_PUBLICATION_REQUEST ]]" != "1"', rule)
        for source in ('push', 'web', 'schedule'):
            self.assertIn('$CI_PIPELINE_SOURCE == "' + source + '"', rule)
        self.assertNotIn('"api"', rule)

    def test_child_has_one_protected_serialized_job_and_only_receipt_artifacts(self):
        path = ROOT / '.gitlab/publication-control.yml'
        self.assertTrue(path.is_file(), 'The request bridge needs its owned child configuration')
        header, pipeline = documents(path)
        self.assertEqual(set(header['spec']['inputs']), set(REQUEST_FIELDS))
        for name in REQUEST_FIELDS:
            self.assertEqual(header['spec']['inputs'][name], self.parent()[0]['spec']['inputs'][name])
        physical = {name: value for name, value in pipeline.items() if isinstance(value, dict) and 'script' in value}
        self.assertEqual(set(physical), {'publication / control'})
        job = physical['publication / control']
        self.assertEqual(job['image'], 'python:3.13.18-slim-bookworm')
        self.assertEqual(job['environment'], {'name': 'publication-control', 'action': 'prepare'})
        self.assertEqual(job['resource_group'], 'publication-control')
        self.assertIs(job['interruptible'], False)
        self.assertEqual(job['script'], [
            "python3 -B -m scripts.publication --operation '$[[ inputs.PUBLICATION_OPERATION ]]'",
        ])
        operation = header['spec']['inputs']['PUBLICATION_OPERATION']
        for value in (operation['default'], *operation['options']):
            compiled = job['script'][0].replace('$[[ inputs.PUBLICATION_OPERATION ]]', value)
            self.assertEqual(shlex.split(compiled),
                             ['python3', '-B', '-m', 'scripts.publication', '--operation', value])
        self.assertNotIn('$PUBLICATION_OPERATION', job['script'][0])
        self.assertEqual(job['artifacts'], {'when': 'always', 'expire_in': '1 year',
                                          'paths': ['artifacts/publication/control/']})
        bootstrap = '\n'.join(job['before_script'])
        for package in ('ca-certificates', 'git', 'openssl', 'ruby'):
            self.assertIn(package, bootstrap)
        self.assertEqual(pipeline['variables'], {name: '$[[ inputs.' + name + ' ]]' for name in REQUEST_FIELDS})
        rule = pipeline['workflow']['rules'][0]['if']
        for predicate in ('$CI_PIPELINE_SOURCE == "parent_pipeline"', '$CI_PROJECT_ID == "88949971"',
                          '$CI_PROJECT_PATH == "bijux-oss/bijux-iac"', '$CI_COMMIT_REF_PROTECTED == "true"'):
            self.assertIn(predicate, rule)
        self.assertEqual(pipeline['workflow']['rules'][-1], {'when': 'never'})

    def test_request_inputs_do_not_add_physical_parent_jobs_or_ambient_github_context(self):
        pipeline = self.parent()[-1]
        jobs = {name for name, job in pipeline.items() if isinstance(job, dict) and 'script' in job}
        self.assertEqual(jobs, {'contracts', 'terraform-format', 'terraform-validate', 'standards', 'governance-plan'})
        self.assertNotIn('GITHUB_', (ROOT / '.gitlab-ci.yml').read_text())


class ApiValidationContextTests(unittest.TestCase):
    def setUp(self):
        self.commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        self.environment = {'GITLAB_CI': 'true', 'CI_SERVER_URL': 'https://gitlab.com',
            'CI_PROJECT_ID': '88949971', 'CI_PROJECT_PATH': 'bijux-oss/bijux-iac',
            'CI_COMMIT_SHA': self.commit, 'CI_PIPELINE_ID': '123', 'CI_JOB_ID': '456',
            'CI_PIPELINE_SOURCE': 'api', 'CI_COMMIT_REF_NAME': 'main', 'CI_COMMIT_BRANCH': 'main',
            'CI_DEFAULT_BRANCH': 'main', 'CI_COMMIT_REF_PROTECTED': 'true',
            'BIJUX_PUBLICATION_REQUEST': '1', 'PUBLICATION_OPERATION': 'preflight'}
        self.branch = {'name': 'main', 'default': True, 'protected': True, 'commit': {'id': self.commit}}

    def test_explicit_api_request_is_validation_only_on_actual_protected_current_main(self):
        for operation in ('verify-credential', 'preflight', 'dispatch'):
            with self.subTest(operation=operation), patch(
                    'scripts.execution.gitlab_plan.public_gitlab_json', return_value=self.branch) as read:
                try:
                    receipt = gitlab_validation.context({**self.environment, 'PUBLICATION_OPERATION': operation})
                except ValueError as error:
                    self.fail('Explicit protected current-main API requests must be admitted: ' + str(error))
                self.assertEqual(receipt['authority'], 'validation-only')
                self.assertEqual(receipt['source'], 'api')
                self.assertIs(receipt['protected_ref'], True)
                read.assert_called_once_with('/repository/branches/main')

    def test_api_request_rejects_absent_selector_unknown_operation_and_unprotected_or_nonmain_refs(self):
        for key, value in [('GITLAB_CI', ''), ('BIJUX_PUBLICATION_REQUEST', ''),
                ('BIJUX_PUBLICATION_REQUEST', '0'), ('PUBLICATION_OPERATION', ''),
                ('PUBLICATION_OPERATION', 'release'), ('CI_COMMIT_REF_PROTECTED', 'false'),
                ('CI_DEFAULT_BRANCH', 'other'), ('CI_COMMIT_BRANCH', 'other'),
                ('CI_COMMIT_REF_NAME', 'other'), ('CI_COMMIT_TAG', 'v1.0.0')]:
            with self.subTest(key=key, value=value), patch(
                    'scripts.execution.gitlab_plan.public_gitlab_json', return_value=self.branch), self.assertRaises(ValueError):
                gitlab_validation.context({**self.environment, key: value})

    def test_api_request_rejects_stale_or_unprotected_native_main(self):
        for branch in ({}, {**self.branch, 'protected': False}, {**self.branch, 'default': False},
                       {**self.branch, 'name': 'other'}, {**self.branch, 'commit': {'id': 'a' * 40}}):
            with self.subTest(branch=branch), patch(
                    'scripts.execution.gitlab_plan.public_gitlab_json', return_value=branch), self.assertRaises(ValueError):
                gitlab_validation.context(self.environment)

    def test_api_request_does_not_fall_back_when_native_main_read_fails(self):
        with patch('scripts.execution.gitlab_plan.public_gitlab_json', side_effect=OSError('unavailable')):
            try:
                gitlab_validation.context(self.environment)
            except OSError:
                pass
            except ValueError as error:
                self.fail('The native main verification must actually run: ' + str(error))
            else:
                self.fail('Unavailable native current-main proof must refuse admission')
