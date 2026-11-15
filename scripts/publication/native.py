"""Admit native manual control and migrated sources without borrowed CI authority."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess
import time
from types import ModuleType
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

NAMES = {'bijux-std': 88948041, 'bijux-iac': 88949971}
CURRENT_MAIN_REPOSITORIES = frozenset((*NAMES, 'bijux.github.io'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive(value):
    return type(value) is int and value > 0


def commit_id(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{40}', value), 'Immutable native source commit is required')
    return value


def git(root, *arguments):
    environment = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C', 'LC_ALL': 'C',
        'HOME': str(Path(root).absolute() / 'artifacts/publication-control/git-home'),
        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
        'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/bin/false'}
    try:
        result = subprocess.run(['git', '-c', 'credential.helper=', '-c', 'http.followRedirects=false',
            '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', '-C', str(root), *arguments],
            env=environment, text=True, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('Native publication source operation is unavailable') from None
    require(result.returncode == 0, 'Native publication requires an actual source checkout')
    return result.stdout.strip()


def ordinary(path):
    path = Path(path).absolute()
    require(path.is_file() and not any(parent.is_symlink() for parent in (path, *path.parents)),
            'Native publication inputs must be ordinary source files')
    return path


def clean_checkout(root, commit):
    root = Path(root).absolute()
    require(not any(parent.is_symlink() for parent in (root, *root.parents)), 'Native source checkout must not follow links')
    root = root.resolve()
    require(Path(git(root, 'rev-parse', '--show-toplevel')).resolve() == root
            and git(root, 'rev-parse', 'HEAD') == commit, 'Native checkout differs from the requested immutable source')
    require(not git(root, 'status', '--porcelain', '--untracked-files=all'), 'Native source checkout has modified or untracked inputs')
    return root


def load_provider(root):
    """Use only committed managed adoption; never substitute a sibling checkout."""
    root = Path(root).absolute()
    require(not any(parent.is_symlink() for parent in (root, *root.parents)),
            'Managed native provider checkout must not follow links')
    root = root.resolve()
    path = root / '.bijux/shared/bijux-gitlab/publication/admission.py'
    require(path.is_file(), 'Accepted managed native publication provider is unavailable; adopt the shared GitLab capability')
    ordinary(path)
    pin = ordinary(root / '.github/standards/bijux-std.sha')
    commit_id(pin.read_text().strip())
    for source in (path, pin):
        relative = str(source.relative_to(root))
        git(root, 'ls-files', '--error-unmatch', '--', relative)
    clean_checkout(root, git(root, 'rev-parse', 'HEAD'))
    module = ModuleType('bijux_managed_native_publication_provider')
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PublicRead:
    """Finite anonymous canonical metadata reads, with no inherited credentials."""
    def __init__(self, provider):
        self.provider = provider
        self.gitlab = provider.PublicRead()
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def __call__(self, path):
        if isinstance(path, str) and path.startswith('/projects/'):
            return self.gitlab(path)
        require(isinstance(path, str) and path in {'repos/bijux/' + name + '/commits/main' for name in CURRENT_MAIN_REPOSITORIES},
                'Unsupported native source mirror endpoint')
        deadline = time.monotonic() + 20
        request = Request('https://api.github.com/' + path, headers={'Accept': 'application/vnd.github+json',
            'User-Agent': 'bijux-native-publication', 'Cache-Control': 'no-cache', 'X-GitHub-Api-Version': '2026-03-10'}, method='GET')
        try:
            with self.opener.open(request, timeout=20) as response:
                require(response.status == 200 and response.geturl() == request.full_url,
                        'Anonymous current mirror metadata is unavailable')
                pieces, size = [], 0
                while True:
                    remaining = deadline - time.monotonic()
                    require(remaining > 0, 'Anonymous mirror read deadline expired')
                    socket = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                    if socket is not None:
                        socket.settimeout(remaining)
                    piece = getattr(response, 'read1', response.read)(min(65536, 4 * 1024 * 1024 + 1 - size))
                    require(time.monotonic() < deadline, 'Anonymous mirror read deadline expired')
                    if not piece:
                        break
                    size += len(piece)
                    require(size <= 4 * 1024 * 1024, 'Anonymous mirror metadata exceeds its byte limit')
                    pieces.append(piece)
        except (HTTPError, URLError, OSError):
            raise ValueError('Anonymous current mirror metadata is unavailable') from None
        return self.provider.strict_json(b''.join(pieces))


def route_for(provider, name):
    require(isinstance(name, str) and name in NAMES, 'Only migrated canonical native sources are supported')
    route = dict(provider.ROUTES[NAMES[name]])
    require(route.get('name') == name and route.get('project_id') == NAMES[name]
            and route.get('project_path') == 'bijux-oss/' + name, 'Managed native source route differs')
    return route


def current_refs(read, route, commit, *, mirror=False):
    prefix = '/projects/' + str(route['project_id'])
    project = read(prefix)
    require(isinstance(project, dict) and type(project.get('id')) is int and project['id'] == route['project_id']
            and project.get('path_with_namespace') == route['project_path'] and project.get('default_branch') == 'main',
            'Actual canonical project identity differs')
    main = read(prefix + '/repository/branches/main')
    require(isinstance(main, dict) and main.get('name') == 'main' and main.get('protected') is True
            and isinstance(main.get('commit'), dict) and main['commit'].get('id') == commit,
            'Native publication requires the current protected canonical main')
    if mirror:
        main = read('repos/bijux/' + route['name'] + '/commits/main')
        require(isinstance(main, dict) and main.get('sha') == commit, 'GitHub mirror main differs from requested native source')


def acquire_std_source(root, commit):
    """Acquire exactly the publicly accepted object without credentials or fallback."""
    destination = Path(root).absolute() / 'artifacts/publication-control/sources/bijux-std' / commit
    require(not any(parent.is_symlink() for parent in (destination, *destination.parents)),
            'Immutable Std source checkout cannot follow symbolic links')
    if destination.exists():
        return clean_checkout(destination, commit)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700)
    git(destination, 'init', '--quiet')
    git(destination, 'fetch', '--quiet', '--depth=1', '--no-tags', '--no-write-fetch-head',
        'https://github.com/bijux/bijux-std.git', commit)
    git(destination, 'checkout', '--quiet', '--detach', commit)
    return clean_checkout(destination, commit)


def current_source(provider, read, route, commit, pipeline, contracts, *, manual=False, mirror=False):
    current_refs(read, route, commit, mirror=mirror)
    prefix = '/projects/' + str(route['project_id'])
    parent = read(prefix + '/pipelines/' + str(pipeline))
    sources = {'web', 'api'} if manual else {'push', 'web', 'schedule'} | ({'api'} if route['name'] == 'bijux-iac' else set())
    require(isinstance(parent, dict) and type(parent.get('id')) is int and parent['id'] == pipeline
            and type(parent.get('project_id')) is int and parent['project_id'] == route['project_id']
            and parent.get('sha') == commit and parent.get('ref') == 'main' and parent.get('source') in sources,
            'Native source validation parent identity or event differs')
    rows = provider.inventory(read, prefix, pipeline, 'jobs')
    require(isinstance(rows, list) and {row.get('name') for row in rows if isinstance(row, dict)} == set(contracts),
            'Native source physical gates differ from the complete owned topology')
    selected = provider.JOBS.qualify_jobs(rows, project_id=route['project_id'], pipeline_id=pipeline,
        commit_sha=commit, required_names=set(contracts), frontend_names={name for name, row in contracts.items() if row['frontend']})['selected_jobs']
    return selected, parent


def owner(row):
    user = row.get('user') if isinstance(row, dict) else None
    require(isinstance(user, dict) and positive(user.get('id')) and user.get('username') == 'bijux',
            'Actual native owner identity is required')
    return user['id']


def controller_snapshot(provider, read, route, commit, child, caller, parent, contracts):
    selected, parent_row = current_source(provider, read, route, commit, parent, contracts, manual=True)
    actual_owner = owner(parent_row)
    prefix = '/projects/' + str(route['project_id'])
    child_row = read(prefix + '/pipelines/' + str(child))
    require(isinstance(child_row, dict) and type(child_row.get('id')) is int and child_row['id'] == child
            and type(child_row.get('project_id')) is int and child_row['project_id'] == route['project_id']
            and child_row.get('sha') == commit and child_row.get('ref') == 'main'
            and child_row.get('source') == 'parent_pipeline' and child_row.get('status') == 'running'
            and owner(child_row) == actual_owner, 'Actual running native control child differs')
    jobs = provider.inventory(read, prefix, child, 'jobs')
    require(bool(jobs) and {row.get('name') for row in jobs if isinstance(row, dict)} == {'publication / control'},
            'Native control child must own only its declared physical job')
    for row in jobs:
        provider.JOBS.validate_identity(row, project_id=route['project_id'], pipeline_id=child, commit_sha=commit)
    require(len({row['id'] for row in jobs}) == len(jobs), 'Duplicate native control execution')
    latest = max(jobs, key=lambda row: row['id'])
    require(latest['id'] == caller and latest.get('status') == 'running' and latest.get('allow_failure') is False
            and owner(latest) == actual_owner, 'Caller is not its latest actual owner-run native control job')
    bridges = provider.inventory(read, prefix, parent, 'bridges')
    for row in bridges:
        provider.JOBS.validate_identity(row, project_id=route['project_id'], pipeline_id=parent, commit_sha=commit)
    require(len({row['id'] for row in bridges}) == len(bridges), 'Duplicate native bridge identity')
    require(all(row['name'] != 'publish / mirrors' for row in bridges),
            'Manual publication control cannot start the automatic mirror bridge')
    matches = [row for row in bridges if row['name'] == 'publish / request']
    require(bool(matches), 'Actual native publication request bridge is missing')
    bridge = max(matches, key=lambda row: row['id'])
    downstream = bridge.get('downstream_pipeline')
    require(bridge.get('status') == 'running' and bridge.get('allow_failure') is False and owner(bridge) == actual_owner
            and isinstance(downstream, dict) and type(downstream.get('id')) is int and downstream['id'] == child
            and downstream.get('sha') == commit and downstream.get('ref') == 'main'
            and ('project_id' not in downstream or type(downstream['project_id']) is int and downstream['project_id'] == route['project_id']),
            'Actual running bridge does not own the native control child')
    return selected, parent_row['source'], bridge['id'], actual_owner


def freshness(selected):
    fields = ('id', 'name', 'status', 'allow_failure', 'artifacts_file', 'artifacts_expire_at', 'erased_at')
    return {name: {key: row['raw_job'].get(key) for key in fields} for name, row in selected.items()}


def artifact_reader(provider, route, artifact, commit, parent):
    if artifact is None:
        api = provider.API.GitLabAPI(route['project_id'], project_path=route['project_path'],
            opener=build_opener(ProxyHandler({}), provider.API.NoRedirect()))
        artifact = api.artifact
    observed = {}
    def fetch(identifier, *, pipeline_id, commit_sha):
        require(positive(identifier) and pipeline_id == parent and commit_sha == commit, 'Immutable native artifact owner differs')
        try:
            body = artifact(identifier, pipeline_id=pipeline_id, commit_sha=commit_sha)
        except (KeyError, OSError):
            raise ValueError('Immutable native artifact is unavailable') from None
        require(isinstance(body, bytes), 'Actual native ZIP bytes are required')
        record = {'job_id': identifier, 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}
        require(identifier not in observed or observed[identifier] == record, 'Native archive changed during admission')
        observed[identifier] = record
        return body
    return fetch, observed


def evidence(provider, root, route, commit, parent, source, selected, report, contracts, fetch):
    archive = provider.ARCHIVE.archive_members(fetch(selected[report]['job_id'], pipeline_id=parent, commit_sha=commit))
    if route['name'] == 'bijux-std':
        return provider.std_evidence(archive['files'], route, commit, parent, source, selected, report, contracts,
                                     root=root, artifact=fetch)
    return provider.iac_evidence(root, archive['files'], route, commit, parent, source, selected[report]['job_id'])


def proof(provider, route, commit, parent, selected, report, review, path, archives):
    return {'schema_version': 1, 'status': 'admitted', 'provider': 'gitlab', 'name': route['name'],
        'project_id': route['project_id'], 'project_path': route['project_path'], 'commit_sha': commit,
        'parent_pipeline_id': parent, 'report_job_id': selected[report]['job_id'], 'mr_iid': review[0],
        'review_head': review[1], 'review': review[3],
        'canonical_mr_url': 'https://gitlab.com/' + route['project_path'] + '/-/merge_requests/' + str(review[0]),
        'evidence_url': 'https://gitlab.com/' + route['project_path'] + '/-/jobs/' + str(selected[report]['job_id']) + '/artifacts/file/' + path,
        'required_jobs': {name: row['job_id'] for name, row in sorted(selected.items())},
        'archives': [archives[key] for key in sorted(archives)],
        'provider_sha256': hashlib.sha256(ordinary(provider.__file__).read_bytes()).hexdigest(), 'remote_writes': False}


def admit_controller(root, environment, *, provider=None, read=None, artifact=None):
    require(isinstance(environment, dict), 'Explicit native control environment is required')
    require(not any(key in environment for key in ('GITHUB_ACTIONS', 'GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')),
            'Native controller cannot borrow GitHub execution context')
    require(all(environment.get(key) == value for key, value in {'GITLAB_CI': 'true', 'CI_SERVER_URL': 'https://gitlab.com',
        'CI_PROJECT_ID': '88949971', 'CI_PROJECT_PATH': 'bijux-oss/bijux-iac', 'CI_DEFAULT_BRANCH': 'main',
        'CI_COMMIT_BRANCH': 'main', 'CI_COMMIT_REF_NAME': 'main', 'CI_COMMIT_REF_PROTECTED': 'true',
        'CI_PIPELINE_SOURCE': 'parent_pipeline', 'CI_JOB_NAME': 'publication / control'}.items())
        and not environment.get('CI_COMMIT_TAG'), 'Native control requires the actual protected canonical main child')
    commit = commit_id(environment.get('CI_COMMIT_SHA'))
    root = clean_checkout(root, commit)
    require(environment.get('CI_PROJECT_DIR') == str(root), 'Native control checkout directory differs')
    identifiers = [environment.get(key, '') for key in ('CI_PIPELINE_ID', 'CI_JOB_ID', 'BIJUX_PARENT_PIPELINE_ID')]
    require(all(isinstance(value, str) and re.fullmatch(r'[1-9][0-9]*', value) for value in identifiers),
            'Native control requires actual positive child/caller/parent IDs')
    child, caller, parent = map(int, identifiers)
    require(child != parent, 'Native control child cannot impersonate its parent')
    provider = provider or load_provider(root)
    route = route_for(provider, 'bijux-iac')
    contracts, report = provider.required_contracts(root, route)
    require(len(contracts) == 5, 'Native control requires the complete five-job IaC validation')
    read = read or PublicRead(provider)
    before = controller_snapshot(provider, read, route, commit, child, caller, parent, contracts)
    review = provider.accepted_review(read, route, commit)
    fetch, archives = artifact_reader(provider, route, artifact, commit, parent)
    path = evidence(provider, root, route, commit, parent, before[1], before[0], report, contracts, fetch)
    after = controller_snapshot(provider, read, route, commit, child, caller, parent, contracts)
    require(freshness(before[0]) == freshness(after[0]) and before[1:] == after[1:]
            and provider.accepted_review(read, route, commit) == review, 'Native control ownership or review changed during admission')
    clean_checkout(root, commit)
    return {**proof(provider, route, commit, parent, before[0], report, review, path, archives),
            'scope': 'controller', 'pipeline_id': child, 'job_id': caller, 'bridge_id': before[2], 'owner_id': before[3]}


def admit_source(root, name, commit, pipeline_id, *, provider=None, read=None, artifact=None, source_root=None):
    commit_id(commit)
    require(positive(pipeline_id), 'Actual native source pipeline ID is required')
    require(isinstance(name, str) and name in NAMES, 'Only migrated canonical native sources are supported')
    provider = provider or load_provider(root)
    route = route_for(provider, name)
    read = read or PublicRead(provider)
    current_refs(read, route, commit, mirror=True)
    if source_root is None:
        source_root = acquire_std_source(root, commit) if name == 'bijux-std' else root
    checkout = clean_checkout(source_root, commit)
    contracts, report = provider.required_contracts(checkout, route)
    require(len(contracts) == (83 if name == 'bijux-std' else 5), 'Native source requires its complete physical validation topology')
    before, parent = current_source(provider, read, route, commit, pipeline_id, contracts, mirror=True)
    review = provider.accepted_review(read, route, commit)
    fetch, archives = artifact_reader(provider, route, artifact, commit, pipeline_id)
    path = evidence(provider, checkout, route, commit, pipeline_id, parent['source'], before, report, contracts, fetch)
    after, current = current_source(provider, read, route, commit, pipeline_id, contracts, mirror=True)
    require(freshness(before) == freshness(after) and current['source'] == parent['source']
            and provider.accepted_review(read, route, commit) == review, 'Native source ownership, current main, or review changed during admission')
    clean_checkout(checkout, commit)
    return {**proof(provider, route, commit, pipeline_id, before, report, review, path, archives),
            'scope': 'source', 'pipeline_id': pipeline_id}
