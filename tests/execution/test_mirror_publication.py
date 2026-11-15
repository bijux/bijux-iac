"""Keep optional mirror delivery outside IaC's five physical validation jobs."""

import json
import subprocess
import unittest

from scripts.inventory.repositories import ROOT


class MirrorPublicationPipelineTests(unittest.TestCase):
    def pipeline(self):
        result = subprocess.run(
            ['ruby', '-ryaml', '-rjson', '-e', 'documents = YAML.parse_stream(STDIN.read).children.map { |doc| '
                                 'stream = Psych::Nodes::Stream.new; stream.children << doc; '
                                 'YAML.safe_load(stream.to_yaml, aliases: false) }; '
                                 'puts JSON.generate(documents.last)'],
            input=(ROOT / '.gitlab-ci.yml').read_text(), text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    def test_accepted_publication_is_a_child_bridge_after_the_real_governance_plan(self):
        pipeline = self.pipeline()
        self.assertIn('publish / mirrors', pipeline, 'Accepted mirror delivery needs its own downstream bridge')
        bridge = pipeline['publish / mirrors']
        self.assertEqual(bridge['stage'], 'publication')
        self.assertEqual(bridge['needs'], ['governance-plan'])
        self.assertEqual(bridge['variables'], {'BIJUX_PARENT_PIPELINE_ID': '$CI_PIPELINE_ID'})
        self.assertEqual(bridge['trigger'], {
            'include': [{'local': '.bijux/shared/bijux-gitlab/ci/publication.yml'}], 'strategy': 'depend',
        })
        self.assertNotIn('script', bridge)
        self.assertNotIn('allow_failure', bridge)
        self.assertIs(bridge['interruptible'], False)
        self.assertEqual(pipeline['stages'], ['validation', 'governance', 'publication'])

    def test_publication_bridge_requires_explicit_readiness_and_protected_default_main(self):
        pipeline = self.pipeline()
        self.assertIn('publish / mirrors', pipeline)
        self.assertEqual(pipeline['publish / mirrors']['rules'], [
            {'if': '"$[[ inputs.BIJUX_PUBLICATION_REQUEST ]]" != "1" && ($CI_PIPELINE_SOURCE == "push" || $CI_PIPELINE_SOURCE == "web" || $CI_PIPELINE_SOURCE == "schedule") && $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_REF_PROTECTED == "true" && $BIJUX_MIRROR_PUBLICATION_READY == "true"'},
            {'when': 'never'},
        ])
        self.assertNotIn('environment', pipeline['governance-plan'])
        self.assertNotIn('environment', pipeline['publish / mirrors'])

    def test_all_five_physical_jobs_stay_credential_free_and_keep_their_existing_commands(self):
        pipeline = self.pipeline()
        physical = {name: job for name, job in pipeline.items() if isinstance(job, dict) and 'script' in job}
        self.assertEqual(set(physical), {'contracts', 'terraform-format', 'terraform-validate', 'standards', 'governance-plan'})
        self.assertEqual(physical['contracts']['script'], ['make contract-tests'])
        self.assertEqual(physical['standards']['script'], ['make bijux-std-checks'])
        self.assertEqual(physical['governance-plan']['script'][-1], 'python3 -B -m scripts.execution.gitlab_plan')
        for name, job in physical.items():
            with self.subTest(job=name):
                self.assertNotIn('environment', job)
                self.assertNotIn('trigger', job)
        self.assertNotIn('BIJUX_MIRROR_GITHUB_APP_KEY', json.dumps(pipeline))
        self.assertNotIn('BIJUX_MIRROR_GITLAB_SSH_KEY', json.dumps(pipeline))

    def test_capability_selection_requests_the_shared_gitlab_owner(self):
        result = subprocess.run([
            'make', '--no-print-directory', '-s', '-f', 'makes/bijux-std.mk', '-f', '-', 'publication-capabilities',
        ], input='publication-capabilities:\n\t@echo $(BIJUX_STD_CAPABILITIES)\n',
            cwd=ROOT, text=True, capture_output=True, check=True)
        self.assertEqual(result.stdout.split(), ['common', 'gitlab'])
