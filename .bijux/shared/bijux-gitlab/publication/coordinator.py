"""Acknowledge each destination independently and retain recoverable partial state."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re


ROUTES = {
    'bijux-std': (88948041, 1212849789, 88949531),
    'bijux-iac': (88949971, 1223469411, 88950131),
}


def checked_route(proof: dict) -> tuple[int, int, int]:
    name = proof.get('name')
    route = proof.get('route', {})
    expected = ROUTES.get(name)
    if (expected is None or not isinstance(route, dict)
            or tuple(route.get(key) for key in ('project_id', 'github_repository_id', 'personal_gitlab_project_id')) != expected
            or proof.get('project_id') != expected[0] or proof.get('project_path') != 'bijux-oss/' + name
            or route.get('project_path') != 'bijux-oss/' + name or route.get('name') != name
            or re.fullmatch(r'[a-f0-9]{40}', proof.get('commit_sha', '')) is None
            or type(proof.get('mr_iid')) is not int or proof['mr_iid'] <= 0):
        raise ValueError('Publication destination differs from the fixed admitted route')
    return expected


def retain(path: Path, receipt: dict) -> None:
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError('Publication receipt paths must not follow symbolic links')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.stat().st_size > 1024 * 1024:
            raise ValueError('Existing publication evidence cannot be replaced')
        previous = json.loads(path.read_bytes())
        identity = ('schema_version', 'canonical_project_id', 'commit_sha', 'validation_pipeline_id', 'validation_report_job_id')
        if not isinstance(previous, dict) or any(receipt.get(key) is None or previous.get(key) != receipt[key] for key in identity):
            raise ValueError('Existing evidence belongs to another publication')
    pending = path.with_name(path.name + '.pending')
    descriptor = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(receipt, stream, indent=2, sort_keys=True)
        stream.write('\n')
    os.replace(pending, path)


def coordinate(proof: dict, github, verify_gitlab, publish, path: Path) -> dict:
    """The write adapter must enforce ancestry and independently read back each ref."""
    route = checked_route(proof)
    native = github.verify_mirror()
    if native.get('repository_id') != route[1] or native.get('actions_enabled') is not False:
        raise ValueError('The GitHub destination must identify the non-executing publication mirror')
    destination = verify_gitlab()
    if destination.get('id') != route[2] or destination.get('builds_access_level') != 'disabled':
        raise ValueError('The GitLab destination must identify the non-executing publication mirror')
    candidate = proof['commit_sha']
    if type(proof.get('parent_pipeline_id')) is not int or proof['parent_pipeline_id'] <= 0:
        raise ValueError('The admitted parent validation pipeline identity is required')
    validation_url = 'https://gitlab.com/' + proof['project_path'] + '/-/pipelines/' + str(proof['parent_pipeline_id'])
    branch = f'publication/gitlab-{proof["mr_iid"]}-{candidate[:12]}'
    receipt = {'schema_version': 1, 'status': 'pending', 'canonical_project_id': route[0],
               'commit_sha': candidate, 'ref': 'refs/heads/main', 'canonical_mr_url': proof['canonical_mr_url'],
               'validation_url': validation_url, 'acceptance_url': proof['evidence_url'], 'validation_pipeline_id': proof['parent_pipeline_id'],
               'validation_report_job_id': proof['report_job_id'], 'destinations': {}}
    retain(path, receipt)
    stage = 'github/publication-branch'
    try:
        receipt['publication_branch'] = {'name': branch, **publish('github', branch, candidate)}
        retain(path, receipt)
        stage = 'github/validation-status'
        github.status(candidate, validation_url)
        stage = 'github/publication-record'
        pr = github.ensure_pr(branch, candidate, proof['canonical_mr_url'], validation_url)
        receipt['github_pull_request'] = pr
        retain(path, receipt)
        stage = 'github/default-branch'
        receipt['destinations']['github'] = publish('github', 'main', candidate)
        retain(path, receipt)
        stage = 'github/indirect-merge'
        receipt['github_pull_request'] = github.acknowledge_pr(pr['number'], candidate)
        retain(path, receipt)
        stage = 'gitlab/default-branch'
        receipt['destinations']['gitlab'] = publish('gitlab', 'main', candidate)
        retain(path, receipt)
        stage = 'mirror/read-back'
        after_github, after_gitlab = github.verify_mirror(), verify_gitlab()
        if (after_github.get('repository_id') != route[1] or after_github.get('actions_enabled') is not False
                or after_gitlab.get('id') != route[2] or after_gitlab.get('builds_access_level') != 'disabled'):
            raise ValueError('Mirror identity or execution setting changed during publication')
        receipt['status'] = 'published'
    except Exception as error:
        receipt.update(status='partial', failed_stage=stage, error_type=type(error).__name__)
    retain(path, receipt)
    return receipt
