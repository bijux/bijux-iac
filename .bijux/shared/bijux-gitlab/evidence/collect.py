"""Collect fresh native evidence only from source-declared physical job owners."""
from __future__ import annotations

import fnmatch
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
from types import ModuleType
from threading import Lock


def load_path(path, name):
    module = ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


HERE = Path(__file__).resolve().parent
API = load_path(HERE / 'api.py', 'bijux_native_collection_api')
JOBS = API.JOBS
ARCHIVE = load_path(HERE / 'archive.py', 'bijux_native_collection_archive')
TRACE = load_path(HERE / 'trace.py', 'bijux_native_collection_trace')
CI = load_path(HERE.parents[2] / 'tests/bijux-docs/execution/ci_context.py', 'bijux_native_collection_context')
require = JOBS.require
MAX_COLLECTED_BYTES = 2 * 1024 * 1024 * 1024


def ordinary_artifact_path(name):
    return (isinstance(name, str) and name.startswith('artifacts/') and len(name) <= 4096
            and '\\' not in name and ':' not in name and not any(ord(character) < 32 for character in name)
            and all(part not in ('', '.', '..') for part in name.split('/')))


def owner_paths(root, contract):
    paths = list(contract['paths'])
    if contract['operation'] == 'browser':
        batch, engine = contract['args']
        registry = json.loads((root / 'tests/bijux-docs/execution/browser_ownership/registry.json').read_bytes())['batches']
        require(batch in registry and engine in ('chromium', 'firefox', 'webkit'), 'Unknown source-owned browser executor')
        paths = ['artifacts/bijux-docs/shards/' + group + '-' + engine for group in registry[batch]]
    require(all(ordinary_artifact_path(path) for path in paths), 'Source-owned artifact paths must remain under artifacts')
    return paths


def qualify_members(root, *, contract, owner_job, files, selected_jobs, context):
    paths = owner_paths(Path(root), contract) + ['artifacts/gitlab/jobs/' + str(owner_job['id'])]
    selected_ids = {record['job_id'] for record in selected_jobs.values()}
    expected_pipeline = {key: value for key, value in CI.validate(context).items() if key != 'job_id'}
    producer = selected_jobs.get('std / navigation fixtures', {}).get('job_id')
    def bind(identity, exact=None):
        identity = CI.validate(identity)
        require({key: value for key, value in identity.items() if key != 'job_id'} == expected_pipeline,
                'Native receipt belongs to another project, pipeline or source')
        require(int(identity['job_id']) in selected_ids, 'Native receipt names an unselected physical job')
        require(exact is None or identity['job_id'] == str(exact), 'Native receipt executor differs from its artifact owner')
    def nested(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'ci_context' or key == 'workflow' and isinstance(child, dict) and child.get('provider') == 'gitlab':
                    bind(child)
                else:
                    nested(child)
        elif isinstance(value, list):
            for child in value:
                nested(child)
    hashes = {}
    for name, data in files.items():
        require(ordinary_artifact_path(name) and isinstance(data, bytes), 'Unowned or malformed artifact member')
        require(any(fnmatch.fnmatchcase(name, path) or fnmatch.fnmatchcase(name, path.rstrip('/') + '/*') for path in paths),
                'Artifact member is outside its source-declared physical owner: ' + name)
        hashes[name] = hashlib.sha256(data).hexdigest()
        if not name.endswith('.json'):
            continue
        try:
            value = json.loads(data)
        except (ValueError, UnicodeError):
            require(PurePosixPath(name).name not in ('producer-envelope.json', 'command-receipt.json', 'renderer-controls.json',
                                                   'receipt.json', 'execution.json', 'navigation-qualification.json'),
                    'Native receipt JSON is malformed')
            continue
        if isinstance(value, dict):
            if 'ci_context' in value:
                bind(value['ci_context'], owner_job['id'])
            if 'workflow' in value and (PurePosixPath(name).name in ('command-receipt.json', 'renderer-controls.json', 'receipt.json')
                                       or isinstance(value['workflow'], dict) and value['workflow'].get('provider') == 'gitlab'):
                bind(value['workflow'], owner_job['id'])
            if isinstance(value.get('executor'), dict) and 'ci_context' in value['executor']:
                bind(value['executor']['ci_context'], owner_job['id'])
            if isinstance(value.get('producer'), dict) and 'ci_context' in value['producer']:
                require(producer is not None, 'Native execution has no selected fixture producer')
                bind(value['producer']['ci_context'], producer)
        nested(value)
    return hashes


def merge_files(root, files, *, seen):
    root = Path(root).resolve()
    planned = {}
    for name, data in files.items():
        require(ordinary_artifact_path(name) and isinstance(data, bytes), 'Merged evidence must belong under repository artifacts')
        destination = root / name
        require(not any(path.is_symlink() for path in (destination, *destination.parents)), 'Merged evidence path traverses a link')
        digest = hashlib.sha256(data).hexdigest()
        require(name not in seen or seen[name] == digest, 'Different physical owners collide on artifact bytes')
        if destination.exists():
            require(destination.is_file() and destination.stat().st_size == len(data)
                    and hashlib.sha256(destination.read_bytes()).hexdigest() == digest, 'Preserve existing nonidentical artifact bytes')
        planned[name] = digest
    for name, data in files.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(data)
    seen.update(planned)
    return planned


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.is_symlink(), 'Native observation cannot replace a link')
    body = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    if path.exists():
        require(path.read_bytes() == body, 'Preserve existing native observation')
    else:
        with path.open('xb') as stream:
            stream.write(body)


def selected_identity(record):
    row = record['raw_job']
    return {key: row.get(key) for key in ('id', 'name', 'status', 'allow_failure', 'created_at', 'started_at', 'finished_at',
                                        'artifacts_file', 'artifacts_expire_at', 'erased_at')}


def collect(root, *, exclude_operations: set[str]):
    root = Path(root).resolve()
    require(exclude_operations in ({'report'}, {'navigation', 'report'}), 'Only the active aggregate and report may be excluded')
    require(os.environ.get('VERIFICATION_MODE', 'full') == 'full', 'Unsupported operation: gitlab retained-proof recovery')
    context = CI.execution_identity()
    require(context['server_url'] == 'https://gitlab.com', 'Native evidence requires its fixed GitLab.com origin')
    actual_head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    require(actual_head == context['commit_sha'], 'Native runner checkout differs from its pipeline source')
    require(not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root, text=True).strip(),
            'Native evidence admission requires the clean tracked checkout')
    pipeline = load_path(root / 'shared/bijux-gitlab/pipeline.py', 'bijux_native_source_job_contracts')
    contracts = pipeline.job_contracts(root)
    required = {name for name, contract in contracts.items() if contract['operation'] not in exclude_operations}
    frontend = {name for name in required if contracts[name]['frontend']}
    api = API.GitLabAPI(int(context['project_id']), project_path=context['project_path'],
                       read_token=os.environ.get('BIJUX_GITLAB_READ_TOKEN') or None)
    arguments = {'pipeline_id': int(context['pipeline_id']), 'commit_sha': context['commit_sha']}
    caller = api.job(int(context['job_id']), **arguments)
    require(caller['name'] in contracts and contracts[caller['name']]['operation'] in exclude_operations
            and caller.get('status') == 'running', 'Collector is not its actual active source-owned aggregate job')
    require(exclude_operations == ({'report'} if contracts[caller['name']]['operation'] == 'report' else {'navigation', 'report'}),
            'Collector exclusions differ from the active source-owned operation')
    audit = root / 'artifacts/gitlab/jobs' / context['job_id'] / 'evidence'
    records, traces, seen, expanded = {}, {}, {}, 0
    reservation = Lock()
    def reserve(size):
        nonlocal expanded
        with reservation:
            expanded += size
            require(expanded <= MAX_COLLECTED_BYTES, 'Native artifact union exceeds bounded expanded bytes')
    rows = api.pipeline_jobs(arguments['pipeline_id'])
    require({row['name'] for row in rows} <= set(contracts), 'Pipeline contains an unknown physical job owner')
    admission = JOBS.qualify_jobs(rows, project_id=int(context['project_id']), required_names=required, frontend_names=frontend, **arguments)
    write_json(audit / 'jobs-initial.json', rows)
    def fetch(item):
        name, record = item
        identifier = record['job_id']
        owner = api.job(identifier, **arguments)
        require(selected_identity({'raw_job': owner}) == selected_identity(record), 'Authoritative native job changed since inventory')
        raw_trace = api.trace(identifier, **arguments)
        lifecycle = TRACE.parse_sections(raw_trace, started_at=owner['started_at'], finished_at=owner['finished_at'])
        if name in frontend:
            require(sum(section['name'] == 'step_script' for section in lifecycle['sections']) == 1,
                    'Frontend owner requires its actual complete native step_script section: ' + name)
        data = api.artifact(identifier, **arguments)
        members = ARCHIVE.archive_members(data, reserve=reserve)
        hashes = qualify_members(root, contract=contracts[name], owner_job=owner, files=members['files'],
                                 selected_jobs=admission['selected_jobs'], context=context)
        return name, owner, raw_trace, lifecycle, members, hashes
    with ThreadPoolExecutor(max_workers=min(8, len(admission['selected_jobs']))) as executor:
        pending = executor.map(fetch, admission['selected_jobs'].items())
        for name, owner, raw_trace, lifecycle, members, hashes in pending:
            identifier = owner['id']
            traces[name] = lifecycle
            folder = audit / str(identifier)
            write_json(folder / 'job.json', owner)
            write_json(folder / 'trace.json', lifecycle)
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / 'trace.log'
            if target.exists():
                require(not target.is_symlink() and target.read_bytes() == raw_trace, 'Preserve original physical native trace')
            else:
                with target.open('xb') as stream:
                    stream.write(raw_trace)
            merge_files(root, members['files'], seen=seen)
            records[name] = {key: value for key, value in members.items() if key not in ('files', 'modes')}
            records[name].update(job_id=identifier, files_sha256=hashes)
            write_json(folder / 'artifact.json', records[name])
    final_rows = api.pipeline_jobs(arguments['pipeline_id'])
    final = JOBS.qualify_jobs(final_rows, project_id=int(context['project_id']), required_names=required, frontend_names=frontend, **arguments)
    require(set(final['selected_jobs']) == set(admission['selected_jobs'])
            and all(selected_identity(final['selected_jobs'][name]) == selected_identity(record)
                    for name, record in admission['selected_jobs'].items()), 'Native latest execution changed during body admission')
    write_json(audit / 'jobs-final.json', final_rows)
    write_json(audit / 'transport.json', api.observations)
    admission.update(caller=context, artifacts=records, traces=traces, files_sha256=seen,
                     audit=str(audit.relative_to(root)), final_raw_jobs=final_rows)
    admission['limits'].extend(['Only full fresh execution is supported; retained-proof recovery is unsupported.',
        'Artifact hashes describe bytes fetched by immutable successful native job ID; no provider artifact digest is invented.',
        'Actual trace sections are required for frontend script lifecycle; no independent per-command status is inferred.',
        'Native source, runtime, inventory, case and JUnit qualification remain mandatory.'])
    write_json(audit / 'admission.json', admission)
    return admission
