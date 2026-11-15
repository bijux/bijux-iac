"""Admit accepted protected-main evidence before publishing canonical mirrors."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
from types import ModuleType
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


HERE = Path(__file__).resolve().parent


def load(path, name):
    module = ModuleType('bijux_publication_' + name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


API = load(HERE.parent / 'evidence/api.py', 'api')
JOBS = API.JOBS
ARCHIVE = load(HERE.parent / 'evidence/archive.py', 'archive')
require = JOBS.require
ROUTES = {
    88948041: {'name': 'bijux-std', 'project_id': 88948041, 'project_path': 'bijux-oss/bijux-std',
               'github_repository_id': 1212849789, 'personal_gitlab_project_id': 88949531},
    88949971: {'name': 'bijux-iac', 'project_id': 88949971, 'project_path': 'bijux-oss/bijux-iac',
               'github_repository_id': 1223469411, 'personal_gitlab_project_id': 88950131},
}
IAC_JOBS = {'contracts', 'terraform-format', 'terraform-validate', 'standards', 'governance-plan'}


def strict_json(body):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate publication evidence JSON member')
            result[key] = value
        return result
    try:
        return json.loads(body, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite publication JSON')))
    except (UnicodeError, TypeError, ValueError) as error:
        raise ValueError('Invalid publication evidence JSON') from error


class PublicRead:
    """Only finite canonical GitLab metadata paths, with no ambient token or proxy."""
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), API.NoRedirect())
        self.deadline = time.monotonic() + 180

    def __call__(self, path):
        suffix = (r'(?:/pipelines/[1-9][0-9]*(?:/(?:jobs|bridges)\?include_retried=true&per_page=100&page=[1-9][0-9]*)?'
                  r'|/repository/branches/main|/repository/commits/[a-f0-9]{40}/merge_requests\?per_page=100'
                  r'|/merge_requests/[1-9][0-9]*(?:/approvals)?)?')
        require(isinstance(path, str) and re.fullmatch(r'/projects/(?:88948041|88949971)' + suffix, path),
                'Unsupported canonical publication metadata path')
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, 'Publication admission deadline expired')
        request = Request('https://gitlab.com/api/v4' + path, method='GET',
                          headers={'Accept': 'application/json', 'Cache-Control': 'no-cache',
                                   'User-Agent': 'bijux-accepted-publication'})
        try:
            with self.opener.open(request, timeout=min(20, remaining)) as response:
                require(response.status == 200, 'Publication metadata is unavailable')
                body = response.read(API.MAX_JSON_BYTES + 1)
                require(len(body) <= API.MAX_JSON_BYTES and time.monotonic() < self.deadline,
                        'Publication metadata exceeds its byte/time bound')
                result = strict_json(body)
                if '/merge_requests?per_page=100' in path:
                    require(not response.headers.get('X-Next-Page'), 'Merged-request inventory is incomplete')
                if '/jobs?' in path or '/bridges?' in path:
                    page = path.rsplit('=', 1)[1]
                    require(response.headers.get('X-Page') == page
                            and response.headers.get('X-Next-Page') in ('', str(int(page) + 1))
                            and isinstance(result, list) and len(result) <= 100
                            and (not response.headers.get('X-Next-Page') or len(result) == 100),
                            'Publication inventory pagination is incomplete')
        except (HTTPError, URLError, OSError) as error:
            raise ValueError('Anonymous publication metadata is unavailable') from error
        return result


def git(root, *arguments):
    result = subprocess.run(['git', '-C', str(root), *arguments], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(result.returncode == 0, 'Publication requires an actual source-owned Git checkout')
    return result.stdout.strip()


def clean_source(root, sha):
    require(git(root, 'rev-parse', 'HEAD') == sha, 'Publication checkout differs from accepted source')
    require(not git(root, 'status', '--porcelain', '--untracked-files=no'), 'Publication refuses dirty tracked source')


def source_file(root, relative):
    require(isinstance(relative, str) and not PurePosixPath(relative).is_absolute()
            and all(part not in ('', '.', '..') for part in relative.split('/'))
            and '\\' not in relative, 'Publication source path is unsafe')
    path = root / relative
    require(path.is_file() and not any(parent.is_symlink() for parent in (path, *path.parents)
                                      if parent.is_relative_to(root)), 'Publication input must be ordinary source')
    git(root, 'ls-files', '--error-unmatch', '--', relative)
    return path


def inventory(read, prefix, pipeline, kind):
    rows = []
    for page in range(1, 101):
        part = read(f'{prefix}/pipelines/{pipeline}/{kind}?include_retried=true&per_page=100&page={page}')
        require(isinstance(part, list) and len(part) <= 100, 'Malformed publication job/bridge inventory')
        rows.extend(part)
        if len(part) < 100:
            return rows
    raise ValueError('Publication job/bridge inventory exceeds its bound')


def required_contracts(root, route):
    if route['name'] == 'bijux-iac':
        return {name: {'frontend': False, 'paths': []} for name in IAC_JOBS}, 'governance-plan'
    path = source_file(root, 'shared/bijux-gitlab/pipeline.py')
    contracts = load(path, 'source_pipeline').job_contracts(root)
    require(isinstance(contracts, dict) and 'std / report' in contracts and bool(contracts),
            'Source-owned standards execution contracts are missing')
    require(all(isinstance(name, str) and isinstance(contract, dict)
                and type(contract.get('frontend')) is bool for name, contract in contracts.items()),
            'Source-owned standards execution contracts are malformed')
    return contracts, 'std / report'


def snapshot(read, route, sha, child, caller, parent, contracts):
    project, prefix = route['project_id'], '/projects/' + str(route['project_id'])
    metadata = read(prefix)
    require(isinstance(metadata, dict) and type(metadata.get('id')) is int and metadata['id'] == project
            and metadata.get('path_with_namespace') == route['project_path'] and metadata.get('default_branch') == 'main',
            'Canonical publication project/default branch differs')
    branch = read(prefix + '/repository/branches/main')
    require(isinstance(branch, dict) and branch.get('name') == 'main' and branch.get('protected') is True
            and isinstance(branch.get('commit'), dict) and branch['commit'].get('id') == sha,
            'Publication requires the actual current protected main source')
    parent_row = None
    for identifier, sources in ((child, {'parent_pipeline'}), (parent, {'push', 'web', 'schedule'})):
        row = read(f'{prefix}/pipelines/{identifier}')
        require(isinstance(row, dict) and type(row.get('id')) is int and row['id'] == identifier
                and type(row.get('project_id')) is int and row['project_id'] == project
                and row.get('sha') == sha and row.get('ref') == 'main' and row.get('source') in sources,
                'Publication parent/child pipeline source identity differs')
        if identifier == child:
            require(row.get('status') == 'running', 'Publication child pipeline is not running')
        else:
            parent_row = row
    children = inventory(read, prefix, child, 'jobs')
    require(bool(children), 'Actual publication child execution is missing')
    for row in children:
        JOBS.validate_identity(row, project_id=project, pipeline_id=child, commit_sha=sha)
    require(len({row['id'] for row in children}) == len(children)
            and {row['name'] for row in children} == {'publication / mirrors'},
            'Child pipeline must own only physical mirror publication')
    latest = max(children, key=lambda row: row['id'])
    require(latest['id'] == caller and latest.get('status') == 'running' and latest.get('allow_failure') is False,
            'Publication caller is not the latest actual running child job')
    bridges = inventory(read, prefix, parent, 'bridges')
    for row in bridges:
        JOBS.validate_identity(row, project_id=project, pipeline_id=parent, commit_sha=sha)
    matches = [row for row in bridges if row['name'] == 'publish / mirrors']
    require(bool(matches) and len({row['id'] for row in bridges}) == len(bridges), 'Actual publication bridge is missing')
    bridge = max(matches, key=lambda row: row['id'])
    downstream = bridge.get('downstream_pipeline')
    require(bridge.get('status') in {'running', 'success'} and bridge.get('allow_failure') is False
            and isinstance(downstream, dict) and type(downstream.get('id')) is int and downstream['id'] == child
            and downstream.get('sha') == sha and downstream.get('ref') == 'main'
            and ('project_id' not in downstream or type(downstream['project_id']) is int and downstream['project_id'] == project),
            'Actual parent bridge does not own this publication child')
    rows = inventory(read, prefix, parent, 'jobs')
    require({row.get('name') for row in rows if isinstance(row, dict)} == set(contracts),
            'Parent physical execution differs from source-owned contracts')
    qualified = JOBS.qualify_jobs(rows, project_id=project, pipeline_id=parent, commit_sha=sha,
        required_names=set(contracts), frontend_names={name for name, contract in contracts.items() if contract['frontend']})
    return qualified['selected_jobs'], parent_row['source'], bridge['id']


def accepted_review(read, route, sha):
    prefix = '/projects/' + str(route['project_id'])
    rows = read(prefix + '/repository/commits/' + sha + '/merge_requests?per_page=100')
    require(isinstance(rows, list) and len(rows) < 100 and all(isinstance(row, dict) for row in rows),
            'Complete native accepted merge inventory is required')
    matches = [row for row in rows if row.get('state') == 'merged' and row.get('merge_commit_sha') == sha]
    require(len(matches) == 1 and JOBS.positive(matches[0].get('iid')), 'Exactly one actual accepted merge is required')
    iid = matches[0]['iid']
    endpoint = prefix + '/merge_requests/' + str(iid)
    mr = read(endpoint)
    require(isinstance(mr, dict) and type(mr.get('iid')) is int and mr['iid'] == iid
            and type(mr.get('target_project_id')) is int and mr['target_project_id'] == route['project_id']
            and mr.get('state') == 'merged' and mr.get('merge_commit_sha') == sha and mr.get('target_branch') == 'main'
            and mr.get('draft') is False and mr.get('work_in_progress', False) is False,
            'Native merged review target or state differs')
    head = mr.get('sha')
    require(isinstance(head, str) and re.fullmatch(r'[a-f0-9]{40}', head)
            and isinstance(mr.get('diff_refs'), dict) and mr['diff_refs'].get('head_sha') == head
            and isinstance(mr.get('author'), dict) and isinstance(mr['author'].get('username'), str)
            and bool(mr['author']['username']) and isinstance(mr.get('labels'), list)
            and all(isinstance(label, str) for label in mr['labels']), 'Native merged review metadata is malformed')
    if mr['author']['username'] == 'bijux':
        require('owner-self-signoff' in mr['labels'], 'Owner-authored merge requires owner-self-signoff')
        review = 'owner-self-signoff'
    else:
        approvals = read(endpoint + '/approvals')
        require(isinstance(approvals, dict) and isinstance(approvals.get('approved_by'), list)
                and any(isinstance(row, dict) and isinstance(row.get('user'), dict)
                        and row['user'].get('username') == 'bijux' for row in approvals['approved_by'])
                and approvals.get('sha', head) == head, 'Actual owner approval for the merged review head is required')
        review = 'owner-approved'
    return iid, head, mr['author']['username'], review


def std_unit_coverage(root, artifact, route, sha, parent, selected, contracts, claimed):
    """Requalify each immutable unit body and compare its complete native envelope."""
    runner = load(source_file(root, 'shared/bijux-gitlab/contracts.py'), 'unit_coverage')
    pipeline = load(source_file(root, 'shared/bijux-gitlab/pipeline.py'), 'unit_pipeline')
    require(runner.PARTITION_COUNT == pipeline.CONTRACT_PARTITION_COUNT == 6,
            'Publication requires six source-owned contract partitions')
    units = {name: row for name, row in contracts.items() if row.get('operation') == 'contracts'}
    require(len(units) == 6 and all(isinstance(row.get('args'), list) and len(row['args']) == 1
                and type(row['args'][0]) is int for row in units.values())
            and {row['args'][0] for row in units.values()} == set(range(6)),
            'Every source-owned unit executor is required exactly once')
    require(isinstance(claimed, dict), 'Standards acceptance unit coverage is missing')
    receipts, owners, seen = [], [], set()
    for name, contract in sorted(units.items(), key=lambda pair: pair[1]['args'][0]):
        selected_owner = selected.get(name, {})
        owner = selected_owner.get('job_id')
        require(JOBS.positive(owner) and owner not in seen, 'Distinct actual unit job owners are required')
        seen.add(owner)
        raw = JOBS.validate_identity(selected_owner.get('raw_job'), project_id=route['project_id'],
                                     pipeline_id=parent, commit_sha=sha)
        require(raw['id'] == owner and raw['name'] == name and raw.get('status') == 'success'
                and raw.get('allow_failure') is False, 'Actual unit owner differs from its successful execution')
        archive = ARCHIVE.archive_members(artifact(owner, pipeline_id=parent, commit_sha=sha))
        prefix = f'artifacts/gitlab/jobs/{owner}/'
        relative = prefix + 'contracts/unit-results.json'
        require(relative in archive['files'] and all(path.startswith(prefix) for path in archive['files']),
                'Immutable unit archive is missing its receipt or contains unowned files')
        body = archive['files'][relative]
        require(0 < len(body) <= 16 * 1024 * 1024, 'Immutable unit receipt is missing or oversized')
        receipt = strict_json(body)
        require(isinstance(receipt, dict) and type(receipt.get('partition_index')) is int
                and receipt['partition_index'] == contract['args'][0], 'Unit receipt differs from its source-owned partition')
        receipts.append(receipt)
        owners.append({'partition_index': contract['args'][0], 'job_name': name, 'job_id': owner,
                       'receipt_path': relative, 'receipt_sha256': hashlib.sha256(body).hexdigest()})
    coverage = runner.verify_coverage(receipts, sha, expected_partitions=6)
    coverage.update(provider='gitlab', server_url='https://gitlab.com', project_id=route['project_id'],
                    project_path=route['project_path'], pipeline_id=parent, native_owners=owners)
    require(claimed == coverage, 'Reported unit coverage differs from independently requalified immutable owners')
    return coverage


def std_evidence(files, route, sha, parent, source, selected, report, contracts, *, root, artifact):
    root = Path(root).resolve()
    clean_source(root, sha)
    allowed = list(contracts[report].get('paths', [])) + ['artifacts/gitlab/jobs/' + str(selected[report]['job_id'])]
    require(all(any(name == prefix or name.startswith(prefix + '/') for prefix in allowed) for name in files),
            'Standards report archive contains unowned paths')
    path = 'artifacts/gitlab/acceptance/acceptance.json'
    require(path in files, 'Standards acceptance receipt is missing')
    receipt = strict_json(files[path])
    require(isinstance(receipt, dict) and type(receipt.get('schema_version')) is int
            and receipt['schema_version'] == 1 and receipt.get('server_url') == 'https://gitlab.com'
            and type(receipt.get('project_id')) is int and receipt['project_id'] == route['project_id']
            and receipt.get('project_path') == route['project_path'] and receipt.get('commit_sha') == sha
            and type(receipt.get('pipeline_id')) is int and receipt['pipeline_id'] == parent
            and receipt.get('pipeline_source') == source and receipt.get('ref') == 'main' and receipt.get('ref_protected') is True,
            'Standards acceptance source/parent/protection differs')
    require(isinstance(receipt.get('publication'), dict) and receipt['publication'].get('status') == 'pending',
            'Standards acceptance must leave publication pending')
    validation = receipt.get('validation', {})
    jobs = validation.get('jobs') if isinstance(validation, dict) else None
    require(isinstance(validation, dict) and validation.get('status') == 'passed'
            and isinstance(jobs, dict) and set(jobs) == set(selected) - {report},
            'Standards acceptance must cover every physical prerequisite')
    for name, entry in jobs.items():
        require(isinstance(entry, dict) and type(entry.get('job_id')) is int and entry['job_id'] == selected[name]['job_id'],
                'Standards acceptance prerequisite differs from the latest actual job')
        raw = JOBS.validate_identity(entry.get('raw_job'), project_id=route['project_id'], pipeline_id=parent, commit_sha=sha)
        require(raw['id'] == entry['job_id'] and raw['name'] == name and raw.get('status') == 'success'
                and raw.get('allow_failure') is False, 'Standards acceptance raw owner differs')
    std_unit_coverage(root, artifact, route, sha, parent, selected, contracts, validation.get('contract_coverage'))
    clean_source(root, sha)
    return path


def bound_digests(root, value):
    require(isinstance(value, dict) and bool(value), 'Publication requires source-bound evidence digests')
    for name, digest in value.items():
        require(isinstance(digest, str) and re.fullmatch(r'[a-f0-9]{64}', digest)
                and hashlib.sha256(source_file(root, name).read_bytes()).hexdigest() == digest,
                'Publication evidence input digest differs from accepted source')


def iac_evidence(root, files, route, sha, parent, source, owner):
    path = 'artifacts/gitlab/governance-plan.json'
    require(set(files) == {path, 'artifacts/gitlab/context.json', 'artifacts/gitlab/github-public-reads.json'},
            'IaC plan requires exactly its three sanitized receipt files')
    plan, context, gateway = (strict_json(files[name]) for name in (
        path, 'artifacts/gitlab/context.json', 'artifacts/gitlab/github-public-reads.json'))
    for row, authority in ((plan, 'read-only-plan'), (context, 'validation-only')):
        require(isinstance(row, dict) and type(row.get('version')) is int
                and row['version'] == 1 and row.get('authority') == authority
                and row.get('project_id') == str(route['project_id']) and row.get('project_path') == route['project_path']
                and row.get('commit') == sha and row.get('pipeline_id') == str(parent) and row.get('job_id') == str(owner)
                and row.get('source') == source and row.get('ref') == 'main' and row.get('protected_ref') is True,
                'IaC receipt native source/parent/owner differs')
    require(plan.get('status') == 'planned' and plan.get('application_ready') is False
            and plan.get('remote_writes') is False and plan.get('github_authentication') == 'anonymous',
            'IaC receipt is not a successful non-applicable anonymous plan')
    nested = plan.get('plan')
    require(isinstance(nested, dict) and nested.get('status') == 'planned' and nested.get('commit') == sha
            and nested.get('privileged') is False and nested.get('remote_writes') is False
            and isinstance(nested.get('plan_digest'), str) and re.fullmatch(r'[a-f0-9]{64}', nested['plan_digest'])
            and isinstance(nested.get('ruleset_plan'), list), 'IaC saved-plan receipt is incomplete or privileged')
    require(isinstance(gateway, dict) and gateway.get('authentication') == 'anonymous' and gateway.get('remote_writes') is False
            and type(gateway.get('failures')) is int and gateway['failures'] == 0
            and type(gateway.get('upstream_requests')) is int and 0 < gateway['upstream_requests'] <= 45,
            'IaC anonymous read evidence is failed or unbounded')
    require(isinstance(plan.get('native_input_digests'), dict)
            and set(plan['native_input_digests']) == {'.gitlab-ci.yml'}, 'IaC native CI input binding is missing')
    bound_digests(root, plan['native_input_digests'])
    bound_digests(root, nested.get('input_digests'))
    return path


def admit(root, environment, read=None, artifact=None):
    """Return admission only after immutable artifact and fresh native ownership agree."""
    root = Path(root).resolve()
    project_text = environment.get('CI_PROJECT_ID', '')
    require(project_text in {str(identifier) for identifier in ROUTES}, 'Canonical publication project is required')
    route = dict(ROUTES[int(project_text)])
    require(environment.get('GITLAB_CI') == 'true' and environment.get('CI_SERVER_URL') == 'https://gitlab.com'
            and environment.get('CI_PROJECT_PATH') == route['project_path']
            and environment.get('CI_PIPELINE_SOURCE') == 'parent_pipeline'
            and environment.get('CI_JOB_NAME') == 'publication / mirrors'
            and environment.get('CI_DEFAULT_BRANCH') == 'main' and environment.get('CI_COMMIT_BRANCH') == 'main'
            and environment.get('CI_COMMIT_REF_NAME') == 'main' and environment.get('CI_COMMIT_REF_PROTECTED') == 'true'
            and not environment.get('CI_COMMIT_TAG'), 'Publication requires the protected canonical main child job')
    sha = environment.get('CI_COMMIT_SHA', '')
    require(isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{40}', sha), 'Immutable publication source is required')
    identifiers = [environment.get(key, '') for key in ('CI_PIPELINE_ID', 'CI_JOB_ID', 'BIJUX_PARENT_PIPELINE_ID')]
    require(all(isinstance(value, str) and re.fullmatch(r'[1-9][0-9]*', value) for value in identifiers),
            'Actual publication child, caller and parent IDs are required')
    child, caller, parent = map(int, identifiers)
    require(child != parent, 'Publication child cannot claim itself as parent')
    clean_source(root, sha)
    contracts, report = required_contracts(root, route)
    read = read or PublicRead()
    selected, source, bridge = snapshot(read, route, sha, child, caller, parent, contracts)
    review = accepted_review(read, route, sha)
    owner = selected[report]['job_id']
    if artifact is None:
        transport = API.GitLabAPI(route['project_id'], project_path=route['project_path'],
                                 opener=build_opener(ProxyHandler({}), API.NoRedirect()))
        artifact = transport.artifact
    archive = ARCHIVE.archive_members(artifact(owner, pipeline_id=parent, commit_sha=sha))
    if route['name'] == 'bijux-std':
        evidence_path = std_evidence(archive['files'], route, sha, parent, source, selected, report, contracts,
                                     root=root, artifact=artifact)
    else:
        evidence_path = iac_evidence(root, archive['files'], route, sha, parent, source, owner)
    current, current_source, current_bridge = snapshot(read, route, sha, child, caller, parent, contracts)
    require({name: row['job_id'] for name, row in current.items()} == {name: row['job_id'] for name, row in selected.items()}
            and current_source == source and current_bridge == bridge and accepted_review(read, route, sha) == review,
            'Native publication ownership or accepted review changed during admission')
    clean_source(root, sha)
    return {'schema_version': 1, 'status': 'admitted', 'route': route, 'name': route['name'],
            'project_id': route['project_id'], 'project_path': route['project_path'], 'commit_sha': sha,
            'pipeline_id': child, 'job_id': caller, 'parent_pipeline_id': parent, 'report_job_id': owner,
            'mr_iid': review[0], 'review_head': review[1], 'review': review[3],
            'canonical_mr_url': 'https://gitlab.com/' + route['project_path'] + '/-/merge_requests/' + str(review[0]),
            'evidence_url': 'https://gitlab.com/' + route['project_path'] + '/-/jobs/' + str(owner) + '/artifacts/file/' + evidence_path,
            'archive_sha256': archive['archive_sha256']}
