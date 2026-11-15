"""Real accepted provider helpers over small immutable native execution fixtures."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
ACCEPTED_PROVIDER = '718205998095d71b8339e54fd7d0eb70e2cbd2dd'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def provider():
    managed = ROOT / '.bijux/shared/bijux-gitlab/publication/admission.py'
    if managed.is_file():
        return load(managed, 'bijux_test_managed_native_provider'), managed.parents[3]
    checkout = ROOT / 'artifacts/native-publication/provider'
    sha = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if sha != ACCEPTED_PROVIDER:
        raise AssertionError('Integration fixtures require the exact accepted GitHub provider checkout')
    return load(checkout / 'shared/bijux-gitlab/publication/admission.py', 'bijux_test_accepted_native_provider'), checkout


def zip_files(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, body in files.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0)),
                             body if isinstance(body, bytes) else json.dumps(body).encode())
    return stream.getvalue()


class NativeFixture:
    def __init__(self, root, name='bijux-iac', source='web'):
        self.root, self.name = root, name
        self.provider, self.provider_root = provider()
        self.project = 88949971 if name == 'bijux-iac' else 88948041
        self.route = copy.deepcopy(self.provider.ROUTES[self.project])
        self.prefix = '/projects/' + str(self.project)
        self.source = source
        self.parent, self.child, self.caller, self.bridge = 200, 300, 900, 800
        root.mkdir(parents=True, exist_ok=True)
        self.git('init', '--quiet', '--initial-branch=main')
        self.git('config', 'user.name', 'Bijux native publication fixture')
        self.git('config', 'user.email', 'verification@example.invalid')
        (root / '.gitignore').write_text('artifacts/\n')
        (root / '.gitlab-ci.yml').write_text('fixture: immutable native validation\n')
        if name == 'bijux-iac':
            self.names = sorted(self.provider.IAC_JOBS)
            self.report = 'governance-plan'
            self.contracts = {name: {'frontend': False, 'paths': []} for name in self.names}
        else:
            self.report = 'std / report'
            self.names = ['std / contracts'] + ['std / contracts / partition ' + str(index) for index in range(2, 7)]
            self.names += ['std / prerequisite ' + str(index) for index in range(76)] + [self.report]
            self.contracts = {name: {'operation': 'standard', 'frontend': False, 'paths': []} for name in self.names}
            for index, name in enumerate(self.names[:6]):
                self.contracts[name].update(operation='contracts', args=[index])
            self.contracts[self.report].update(operation='report', paths=['artifacts/gitlab/acceptance'])
            package = root / 'shared/bijux-gitlab'
            package.mkdir(parents=True)
            (package / 'contracts.py').write_bytes((self.provider_root / 'shared/bijux-gitlab/contracts.py').read_bytes())
            (package / 'pipeline.py').write_text('CONTRACT_PARTITION_COUNT=6\ndef job_contracts(root):\n    return ' + repr(self.contracts) + '\n')
        self.git('add', '--', '.gitignore', '.gitlab-ci.yml', *(['shared'] if self.name == 'bijux-std' else []))
        self.git('commit', '--quiet', '-m', 'test(publication): bind native evidence fixtures')
        self.sha = self.git('rev-parse', 'HEAD')
        self.jobs = [self.job(1000 + index, name) for index, name in enumerate(self.names)]
        self.report_job = next(row['id'] for row in self.jobs if row['name'] == self.report)
        self.mr = {'iid': 7, 'target_project_id': self.project, 'state': 'merged', 'target_branch': 'main',
            'merge_commit_sha': self.sha, 'sha': 'a' * 40, 'diff_refs': {'head_sha': 'a' * 40},
            'author': {'username': 'bijux'}, 'labels': ['owner-self-signoff'], 'draft': False}
        self.rows = {
            self.prefix: {'id': self.project, 'path_with_namespace': 'bijux-oss/' + self.name, 'default_branch': 'main'},
            self.prefix + '/repository/branches/main': {'name': 'main', 'protected': True, 'commit': {'id': self.sha}},
            self.prefix + '/pipelines/200': {'id': 200, 'project_id': self.project, 'sha': self.sha, 'ref': 'main',
                'source': source, 'status': 'running', 'user': {'id': 55, 'username': 'bijux'}},
            self.prefix + '/pipelines/300': {'id': 300, 'project_id': self.project, 'sha': self.sha, 'ref': 'main',
                'source': 'parent_pipeline', 'status': 'running', 'user': {'id': 55, 'username': 'bijux'}},
            self.prefix + '/pipelines/200/jobs?include_retried=true&per_page=100&page=1': self.jobs,
            self.prefix + '/pipelines/300/jobs?include_retried=true&per_page=100&page=1': [self.job(900, 'publication / control', pipeline=300, status='running')],
            self.prefix + '/pipelines/200/bridges?include_retried=true&per_page=100&page=1': [self.job(800, 'publish / request', status='running',
                downstream_pipeline={'id': 300, 'project_id': self.project, 'sha': self.sha, 'ref': 'main'})],
            self.prefix + '/repository/commits/' + self.sha + '/merge_requests?per_page=100': [self.mr],
            self.prefix + '/merge_requests/7': self.mr,
            self.prefix + '/merge_requests/7/approvals': {'sha': 'a' * 40, 'approved_by': [{'user': {'username': 'bijux'}}]},
            'repos/bijux/' + self.name + '/commits/main': {'sha': self.sha},
        }
        self.archives, self.requested_archives = {}, []
        self.files = self.iac_files() if self.name == 'bijux-iac' else self.std_files()
        self.archives[self.report_job] = self.files
        self.environment = {'GITLAB_CI': 'true', 'CI_SERVER_URL': 'https://gitlab.com', 'CI_PROJECT_ID': str(self.project),
            'CI_PROJECT_PATH': 'bijux-oss/' + self.name, 'CI_PROJECT_DIR': str(root), 'CI_DEFAULT_BRANCH': 'main',
            'CI_COMMIT_BRANCH': 'main', 'CI_COMMIT_REF_NAME': 'main', 'CI_COMMIT_REF_PROTECTED': 'true',
            'CI_COMMIT_SHA': self.sha, 'CI_PIPELINE_ID': '300', 'CI_JOB_ID': '900',
            'CI_PIPELINE_SOURCE': 'parent_pipeline', 'CI_JOB_NAME': 'publication / control', 'BIJUX_PARENT_PIPELINE_ID': '200'}

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True, stderr=subprocess.PIPE).strip()

    def job(self, identifier, name, *, pipeline=200, status='success', **extra):
        return {'id': identifier, 'name': name, 'pipeline': {'id': pipeline, 'project_id': self.project, 'sha': self.sha},
            'commit': {'id': self.sha}, 'ref': 'main', 'status': status, 'allow_failure': False, 'runner': {'id': 55},
            'user': {'id': 55, 'username': 'bijux'}, 'created_at': '2026-11-15T10:00:00Z',
            'started_at': '2026-11-15T10:00:01Z', 'finished_at': '2026-11-15T10:01:00Z' if status == 'success' else None, **extra}

    def read(self, path):
        return copy.deepcopy(self.rows[path])

    def artifact(self, job, *, pipeline_id, commit_sha):
        if pipeline_id != 200 or commit_sha != self.sha:
            raise AssertionError('Artifact requests must bind the exact native source and parent')
        self.requested_archives.append(job)
        return zip_files(self.archives[job])

    def iac_files(self):
        identity = {'version': 1, 'project_id': str(self.project), 'project_path': 'bijux-oss/' + self.name,
            'commit': self.sha, 'pipeline_id': '200', 'job_id': str(self.report_job), 'source': self.source,
            'ref': 'main', 'protected_ref': True}
        digest = hashlib.sha256((self.root / '.gitlab-ci.yml').read_bytes()).hexdigest()
        return {'artifacts/gitlab/context.json': {**identity, 'authority': 'validation-only'},
            'artifacts/gitlab/governance-plan.json': {**identity, 'authority': 'read-only-plan', 'status': 'planned',
                'github_authentication': 'anonymous', 'remote_writes': False, 'application_ready': False,
                'native_input_digests': {'.gitlab-ci.yml': digest}, 'plan': {'commit': self.sha, 'status': 'planned',
                    'privileged': False, 'remote_writes': False, 'plan_digest': 'b' * 64, 'ruleset_plan': [],
                    'input_digests': {'.gitlab-ci.yml': digest}}},
            'artifacts/gitlab/github-public-reads.json': {'version': 1, 'authentication': 'anonymous',
                'remote_writes': False, 'failures': 0, 'upstream_requests': 5}}

    def std_files(self):
        runner = load(self.root / 'shared/bijux-gitlab/contracts.py', 'bijux_native_fixture_contracts')
        universe = ['test_fixture.Contracts.test_case_' + str(index) for index in range(30)]
        receipts, owners = [], []
        for index, name in enumerate(self.names[:6]):
            owner = self.jobs[index]['id']
            expected = [case for case in universe if runner.assigned_partition(case, 6) == index]
            receipt = {'schema_version': 1, 'status': 'passed', 'source_head': self.sha,
                'partition_count': 6, 'partition_index': index, 'universe_ids': universe,
                'universe_sha256': runner.universe_digest(universe), 'expected_ids': expected, 'executed_ids': expected,
                'case_results': [{'id': case, 'status': 'passed'} for case in expected], 'failures': [], 'errors': [],
                'skips': [], 'expected_failures': [], 'unexpected_successes': [], 'discovery_errors': []}
            relative = f'artifacts/gitlab/jobs/{owner}/contracts/unit-results.json'
            body = json.dumps(receipt).encode()
            self.archives[owner] = {relative: body}
            receipts.append(receipt)
            owners.append({'partition_index': index, 'job_name': name, 'job_id': owner,
                'receipt_path': relative, 'receipt_sha256': hashlib.sha256(body).hexdigest()})
        coverage = runner.verify_coverage(receipts, self.sha)
        coverage.update(provider='gitlab', server_url='https://gitlab.com', project_id=self.project,
            project_path='bijux-oss/' + self.name, pipeline_id=200, native_owners=owners)
        acceptance = {'schema_version': 1, 'server_url': 'https://gitlab.com', 'project_id': self.project,
            'project_path': 'bijux-oss/' + self.name, 'commit_sha': self.sha, 'pipeline_id': 200,
            'pipeline_source': self.source, 'ref': 'main', 'ref_protected': True, 'publication': {'status': 'pending'},
            'validation': {'status': 'passed', 'contract_coverage': coverage, 'jobs': {row['name']:
                {'job_id': row['id'], 'raw_job': copy.deepcopy(row)} for row in self.jobs if row['name'] != self.report}}}
        return {'artifacts/gitlab/acceptance/acceptance.json': acceptance}
