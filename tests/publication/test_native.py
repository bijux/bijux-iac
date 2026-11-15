"""Prove native controller/source admission without borrowing Actions authority."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tests.publication.fixtures import ROOT, NativeFixture, load


class NativePublicationTests(unittest.TestCase):
    def setUp(self):
        path = ROOT / 'scripts/publication/native.py'
        self.assertTrue(path.is_file(), 'Manual native publication needs source-owned evidence admission')
        self.native = load(path, 'bijux_native_control_test')
        output = ROOT / 'artifacts/native-publication/tests'
        output.mkdir(parents=True, exist_ok=True)
        self.scratch = tempfile.TemporaryDirectory(dir=output)
        self.addCleanup(self.scratch.cleanup)
        self.fixture = NativeFixture(Path(self.scratch.name) / 'iac')

    def controller(self, *, read=None):
        fixture = self.fixture
        return self.native.admit_controller(fixture.root, fixture.environment,
            provider=fixture.provider, read=read or fixture.read, artifact=fixture.artifact)

    def source(self, fixture=None, *, read=None, source_root=None):
        fixture = fixture or self.fixture
        return self.native.admit_source(fixture.root, fixture.name, fixture.sha, 200,
            provider=fixture.provider, read=read or fixture.read, artifact=fixture.artifact,
            source_root=source_root)

    def test_controller_admits_real_five_gate_plan_and_exact_running_manual_child(self):
        proof = self.controller()
        self.assertEqual(proof['status'], 'admitted')
        self.assertEqual(proof['commit_sha'], self.fixture.sha)
        self.assertEqual(proof['pipeline_id'], 300)
        self.assertEqual(proof['parent_pipeline_id'], 200)
        self.assertEqual(proof['job_id'], 900)
        self.assertEqual(proof['bridge_id'], 800)
        self.assertEqual(proof['report_job_id'], self.fixture.report_job)
        self.assertIs(proof['remote_writes'], False)
        self.assertEqual(proof, self.controller())
        self.assertNotIn('created_at', json.dumps(proof))
        self.assertEqual(set(self.fixture.requested_archives), {self.fixture.report_job})

    def test_api_manual_controller_is_supported_but_push_schedule_and_mr_are_refused(self):
        for source in ('web', 'api', 'push', 'schedule', 'merge_request_event'):
            self.fixture.rows[self.fixture.prefix + '/pipelines/200']['source'] = source
            for row in self.fixture.files.values():
                if 'source' in row: row['source'] = source
            if source in ('web', 'api'):
                self.assertEqual(self.controller()['status'], 'admitted')
            else:
                with self.subTest(source=source), self.assertRaises(ValueError): self.controller()

    def test_controller_environment_cannot_substitute_project_branch_child_or_github_identity(self):
        for key, value in (('CI_PROJECT_ID', '88948041'), ('CI_PROJECT_PATH', 'bijux/bijux-iac'),
                           ('CI_COMMIT_REF_PROTECTED', 'false'), ('CI_COMMIT_BRANCH', 'feature'),
                           ('CI_PIPELINE_SOURCE', 'web'), ('CI_JOB_NAME', 'publication / mirrors'),
                           ('CI_JOB_ID', '901'), ('BIJUX_PARENT_PIPELINE_ID', '300'),
                           ('GITHUB_RUN_ID', '123'), ('CI_COMMIT_SHA', 'a' * 40)):
            original = self.fixture.environment
            self.fixture.environment = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError): self.controller()
            self.fixture.environment = original

    def test_controller_actual_owner_and_bridge_identity_must_agree(self):
        changes = [('/pipelines/200', 'user', {'id': 55, 'username': 'someone'}),
                   ('/pipelines/300', 'user', {'id': 56, 'username': 'bijux'})]
        for suffix, key, value in changes:
            row = self.fixture.rows[self.fixture.prefix + suffix]
            original = row[key]; row[key] = value
            with self.subTest(suffix=suffix), self.assertRaises(ValueError): self.controller()
            row[key] = original
        endpoint = self.fixture.prefix + '/pipelines/200/bridges?include_retried=true&per_page=100&page=1'
        self.fixture.rows[endpoint][0]['downstream_pipeline']['id'] = 999
        with self.assertRaises(ValueError): self.controller()

    def test_missing_failed_or_newer_successful_parent_retry_invalidates_old_plan(self):
        endpoint = self.fixture.prefix + '/pipelines/200/jobs?include_retried=true&per_page=100&page=1'
        original = self.fixture.rows[endpoint]
        for rows in (original[1:], original + [self.fixture.job(9999, self.fixture.names[0], status='failed')],
                     original + [self.fixture.job(9999, self.fixture.report)]):
            self.fixture.rows[endpoint] = rows
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError): self.controller()
        self.fixture.rows[endpoint] = original

    def test_controller_rechecks_current_main_caller_review_and_bridge_after_archive(self):
        for suffix, mutation in (
            ('/repository/branches/main', lambda row: row['commit'].update(id='b' * 40)),
            ('/merge_requests/7', lambda row: row.update(labels=[])),
            ('/pipelines/300/jobs?include_retried=true&per_page=100&page=1', lambda rows: rows.append(self.fixture.job(901, 'publication / control', pipeline=300, status='running'))),
            ('/pipelines/200/bridges?include_retried=true&per_page=100&page=1', lambda rows: rows[0].update(id=801))):
            calls = [0]
            def read(path):
                row = self.fixture.read(path)
                if path == self.fixture.prefix + suffix:
                    calls[0] += 1
                    if calls[0] > 1: mutation(row)
                return row
            with self.subTest(suffix=suffix), self.assertRaises(ValueError): self.controller(read=read)

    def test_iac_plan_missing_foreign_writing_or_changed_digest_is_refused(self):
        plan = self.fixture.files['artifacts/gitlab/governance-plan.json']
        for key, value in (('remote_writes', True), ('application_ready', True), ('commit', 'b' * 40)):
            original = plan[key]; plan[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.controller()
            plan[key] = original
        plan['native_input_digests']['.gitlab-ci.yml'] = 'c' * 64
        with self.assertRaises(ValueError): self.controller()

    def test_source_requires_exact_current_canonical_and_github_main_and_stable_proof(self):
        proof = self.source()
        self.assertEqual(proof['status'], 'admitted')
        self.assertEqual(proof['name'], 'bijux-iac')
        self.assertEqual(proof['pipeline_id'], 200)
        self.assertEqual(proof['commit_sha'], self.fixture.sha)
        self.assertEqual(proof, self.source())
        self.fixture.rows['repos/bijux/bijux-iac/commits/main']['sha'] = 'b' * 40
        with self.assertRaises(ValueError): self.source()

    def test_source_rechecks_github_main_and_latest_jobs_after_archive(self):
        for endpoint, mutate in (
            ('repos/bijux/bijux-iac/commits/main', lambda row: row.update(sha='b' * 40)),
            (self.fixture.prefix + '/pipelines/200/jobs?include_retried=true&per_page=100&page=1',
             lambda rows: rows.append(self.fixture.job(9000, self.fixture.report)))):
            calls = [0]
            def read(path):
                row = self.fixture.read(path)
                if path == endpoint:
                    calls[0] += 1
                    if calls[0] > 1: mutate(row)
                return row
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError): self.source(read=read)

    def test_std_source_reads_report_and_all_six_actual_unit_zip_bodies(self):
        std = NativeFixture(Path(self.scratch.name) / 'std', 'bijux-std', 'push')
        proof = self.source(std, source_root=std.root)
        self.assertEqual(proof['status'], 'admitted')
        self.assertEqual(len(proof['archives']), 7)
        self.assertEqual(set(std.requested_archives), {std.report_job, *[row['id'] for row in std.jobs[:6]]})
        self.assertEqual(len(proof['required_jobs']), 83)
        self.assertIs(proof['remote_writes'], False)

    def test_std_source_missing_partition_changed_case_or_false_pending_cannot_qualify(self):
        std = NativeFixture(Path(self.scratch.name) / 'std', 'bijux-std', 'push')
        acceptance = std.files['artifacts/gitlab/acceptance/acceptance.json']
        acceptance['publication']['status'] = 'published'
        with self.assertRaises(ValueError): self.source(std, source_root=std.root)
        acceptance['publication']['status'] = 'pending'
        owner = std.jobs[0]['id']; files = std.archives[owner]
        std.archives[owner] = {'artifacts/gitlab/jobs/' + str(owner) + '/other.json': b'{}'}
        with self.assertRaises(ValueError): self.source(std, source_root=std.root)
        std.archives[owner] = files
        path = next(iter(files)); receipt = json.loads(files[path]); receipt['executed_ids'] = []
        files[path] = json.dumps(receipt).encode()
        with self.assertRaises(ValueError): self.source(std, source_root=std.root)

    def test_explicit_std_checkout_and_ordinary_clean_tracked_inputs_are_required(self):
        std = NativeFixture(Path(self.scratch.name) / 'std', 'bijux-std', 'push')
        (std.root / '.gitlab-ci.yml').write_text('modified\n')
        with self.assertRaises(ValueError): self.source(std, source_root=std.root)

    def test_provider_load_fails_clearly_until_managed_adoption_and_refuses_links(self):
        with self.assertRaisesRegex(ValueError, 'managed|provider'): self.native.load_provider(self.fixture.root)
        managed = self.fixture.root / '.bijux/shared/bijux-gitlab/publication/admission.py'
        managed.parent.mkdir(parents=True)
        managed.symlink_to(ROOT / 'artifacts/native-publication/provider/shared/bijux-gitlab/publication/admission.py')
        with self.assertRaises(ValueError): self.native.load_provider(self.fixture.root)

    def test_manual_request_parent_cannot_also_trigger_automatic_mirror_publication(self):
        endpoint = self.fixture.prefix + '/pipelines/200/bridges?include_retried=true&per_page=100&page=1'
        self.fixture.rows[endpoint].append(self.fixture.job(801, 'publish / mirrors', status='running'))
        for source in ('web', 'api'):
            self.fixture.rows[self.fixture.prefix + '/pipelines/200']['source'] = source
            for row in self.fixture.files.values():
                if 'source' in row: row['source'] = source
            with self.subTest(source=source), self.assertRaises(ValueError): self.controller()

    def test_malformed_native_source_inputs_are_refused_before_provider_reads(self):
        for name, commit, pipeline in (([], self.fixture.sha, 200), ('bijux-iac', 'HEAD', 200),
                                       ('bijux-iac', self.fixture.sha, True), ('unrelated', self.fixture.sha, 200)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.native.admit_source(self.fixture.root, name, commit, pipeline,
                    provider=self.fixture.provider, read=lambda path: self.fail('Malformed input must not read metadata'))

    def test_anonymous_mirror_reader_is_fixed_fresh_bounded_and_has_no_ambient_authentication(self):
        import io
        import os
        from unittest.mock import patch
        class Response(io.BytesIO):
            status = 200
            def geturl(self): return 'https://api.github.com/repos/bijux/bijux-iac/commits/main'
        class Transport:
            def open(self, request, timeout):
                self.request, self.timeout = request, timeout
                return Response(json.dumps({'sha': 'a' * 40}).encode())
        reader = self.native.PublicRead(self.fixture.provider)
        transport = Transport(); reader.opener = transport
        with patch.dict(os.environ, {'GH_TOKEN': 'inert-never-read', 'GITHUB_TOKEN': 'inert-never-read'}, clear=True):
            self.assertEqual(reader('repos/bijux/bijux-iac/commits/main')['sha'], 'a' * 40)
        headers = dict(transport.request.header_items())
        self.assertEqual(transport.request.get_method(), 'GET')
        self.assertEqual(transport.request.get_header('Cache-control'), 'no-cache')
        self.assertFalse({name.lower() for name in headers} & {'authorization', 'cookie', 'private-token'})
        self.assertLessEqual(transport.timeout, 20)
        for path in ([], 'https://evil.example/', 'repos/elsewhere/project/commits/main'):
            with self.subTest(path=path), self.assertRaises(ValueError): reader(path)

    def test_provider_load_uses_only_clean_tracked_managed_adoption(self):
        import shutil
        managed = self.fixture.root / '.bijux/shared/bijux-gitlab'
        shutil.copytree(self.fixture.provider_root / 'shared/bijux-gitlab', managed)
        pin = self.fixture.root / '.github/standards/bijux-std.sha'
        pin.parent.mkdir(parents=True); pin.write_text('718205998095d71b8339e54fd7d0eb70e2cbd2dd\n')
        self.fixture.git('add', '--', '.bijux', '.github')
        self.fixture.git('commit', '--quiet', '-m', 'test(publication): consume accepted native provider fixture')
        admitted = self.native.load_provider(self.fixture.root)
        self.assertEqual(Path(admitted.__file__), managed / 'publication/admission.py')
        linked_root = self.fixture.root.parent / 'linked-provider'
        linked_root.symlink_to(self.fixture.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'link'):
            self.native.load_provider(linked_root)
        (managed / 'evidence/jobs.py').write_text('unreviewed provider code\n')
        with self.assertRaises(ValueError): self.native.load_provider(self.fixture.root)

    def test_default_std_acquisition_is_exact_public_github_and_reuses_clean_checkout(self):
        from unittest.mock import patch
        import subprocess
        std = NativeFixture(Path(self.scratch.name) / 'std', 'bijux-std', 'push')
        original = subprocess.run
        fetched = []
        def transport(argv, *args, **kwargs):
            if 'fetch' in argv and 'https://github.com/bijux/bijux-std.git' in argv:
                fetched.append(list(argv))
                self.assertEqual(argv[-1], std.sha)
                environment = kwargs['env']
                self.assertFalse(set(environment) & {'GH_TOKEN', 'GITHUB_TOKEN', 'CI_JOB_TOKEN', 'SSH_AUTH_SOCK'})
                self.assertEqual(environment['GIT_CONFIG_GLOBAL'], '/dev/null')
                self.assertEqual(environment['GIT_TERMINAL_PROMPT'], '0')
                self.assertIn('credential.helper=', argv)
                self.assertIn('http.followRedirects=false', argv)
                argv = [str(std.root) if value == 'https://github.com/bijux/bijux-std.git' else value for value in argv]
            return original(argv, *args, **kwargs)
        with patch.object(self.native.subprocess, 'run', side_effect=transport):
            first = self.native.admit_source(self.fixture.root, 'bijux-std', std.sha, 200,
                provider=std.provider, read=std.read, artifact=std.artifact)
            second = self.native.admit_source(self.fixture.root, 'bijux-std', std.sha, 200,
                provider=std.provider, read=std.read, artifact=std.artifact)
        self.assertEqual(first, second)
        self.assertEqual(len(fetched), 1)
        checkout = self.fixture.root / 'artifacts/publication-control/sources/bijux-std' / std.sha
        self.assertEqual(subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip(), std.sha)
        (checkout / '.gitlab-ci.yml').write_text('preserve unexpected modification\n')
        with patch.object(self.native.subprocess, 'run', side_effect=transport), self.assertRaises(ValueError):
            self.native.admit_source(self.fixture.root, 'bijux-std', std.sha, 200,
                provider=std.provider, read=std.read, artifact=std.artifact)
        self.assertEqual(len(fetched), 1)
        self.assertEqual((checkout / '.gitlab-ci.yml').read_text(), 'preserve unexpected modification\n')

    def test_std_current_refs_are_checked_before_creating_checkout_artifacts(self):
        std = NativeFixture(Path(self.scratch.name) / 'std', 'bijux-std', 'push')
        std.rows['repos/bijux/bijux-std/commits/main']['sha'] = 'b' * 40
        calls = []
        def read(path): calls.append(path); return std.read(path)
        with self.assertRaises(ValueError):
            self.native.admit_source(self.fixture.root, 'bijux-std', std.sha, 200,
                provider=std.provider, read=read, artifact=std.artifact)
        self.assertIn('repos/bijux/bijux-std/commits/main', calls)
        self.assertFalse((self.fixture.root / 'artifacts/publication-control/sources').exists())

    def test_std_acquisition_preserves_symlinked_and_wrong_head_locations(self):
        std = NativeFixture(Path(self.scratch.name) / 'std', 'bijux-std', 'push')
        parent = self.fixture.root / 'artifacts/publication-control/sources/bijux-std'
        parent.mkdir(parents=True)
        outside = Path(self.scratch.name) / 'outside'; outside.mkdir()
        checkout = parent / std.sha; checkout.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.native.admit_source(self.fixture.root, 'bijux-std', std.sha, 200,
                provider=std.provider, read=std.read, artifact=std.artifact)
        self.assertEqual(list(outside.iterdir()), [])
        checkout.unlink()
        wrong = NativeFixture(checkout)
        with self.assertRaises(ValueError):
            self.native.admit_source(self.fixture.root, 'bijux-std', std.sha, 200,
                provider=std.provider, read=std.read, artifact=std.artifact)
        self.assertEqual(wrong.git('rev-parse', 'HEAD'), wrong.sha)

    def test_iac_current_ref_mismatch_is_refused_before_checkout_inspection(self):
        from unittest.mock import patch
        with patch.object(self.native, 'clean_checkout', side_effect=AssertionError('Source refs must be checked first')):
            with self.assertRaises(ValueError):
                self.native.admit_source(self.fixture.root, 'bijux-iac', 'b' * 40, 200,
                    provider=self.fixture.provider, read=self.fixture.read, artifact=self.fixture.artifact)

    def test_public_reader_supports_only_current_hub_selection_without_migrating_hub(self):
        import io
        class Response(io.BytesIO):
            status = 200
            def geturl(self): return self.url
        class Transport:
            def open(self, request, timeout):
                self.request = request
                response = Response(json.dumps({'sha': 'a' * 40}).encode()); response.url = request.full_url
                return response
        reader = self.native.PublicRead(self.fixture.provider); transport = Transport(); reader.opener = transport
        self.assertEqual(reader('repos/bijux/bijux.github.io/commits/main'), {'sha': 'a' * 40})
        self.assertIsNone(transport.request.get_header('Authorization'))
        with self.assertRaises(ValueError):
            self.native.admit_source(self.fixture.root, 'bijux.github.io', self.fixture.sha, 200,
                provider=self.fixture.provider, read=self.fixture.read, artifact=self.fixture.artifact)
