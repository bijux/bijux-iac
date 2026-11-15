"""Admit a native source identity and run an anonymous, non-applicable live plan."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request

from scripts.execution.application import input_digests
from scripts.execution.gitlab_validation import ARTIFACTS, PROJECT_ID, PROJECT_PATH, context
from scripts.github.public_reads import NoRedirect, ReadGateway, strict_json
from scripts.inventory.repositories import ROOT, validated_inventory
from scripts.inventory.roles import github_development_inventory


def public_gitlab_json(suffix: str) -> object:
    request = urllib.request.Request(f'https://gitlab.com/api/v4/projects/{PROJECT_ID}' + suffix,
                                     headers={'User-Agent': 'bijux-iac-read-plan', 'Accept': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=20) as response:
        payload = response.read(4 * 1024 * 1024 + 1)
        if response.status != 200 or len(payload) > 4 * 1024 * 1024:
            raise ValueError('native read-plan identity response is invalid or oversized')
        return strict_json(payload)


def admit(environment: dict[str, str], *, read=public_gitlab_json) -> dict:
    identity = context(environment)
    project = read('')
    if (not isinstance(project, dict) or project.get('id') != int(PROJECT_ID)
            or project.get('path_with_namespace') != PROJECT_PATH or project.get('default_branch') != 'main'):
        raise ValueError('native read-plan canonical project/default branch mismatch')
    pipeline = read(f'/pipelines/{identity["pipeline_id"]}')
    if (not isinstance(pipeline, dict) or pipeline.get('id') != int(identity['pipeline_id'])
            or pipeline.get('project_id') != int(PROJECT_ID) or pipeline.get('sha') != identity['commit']
            or pipeline.get('source') != identity['source']):
        raise ValueError('native read-plan pipeline identity mismatch')
    jobs = []
    for page in range(1, 6):
        response = read(f'/pipelines/{identity["pipeline_id"]}/jobs?per_page=100&page={page}')
        if not isinstance(response, list) or not all(isinstance(row, dict) for row in response):
            raise ValueError('native read-plan job listing is malformed')
        jobs.extend(response)
        if len(response) < 100:
            break
    else:
        raise ValueError('native read-plan job listing exceeded its bound')
    matches = [row for row in jobs if row.get('id') == int(identity['job_id'])]
    if (len(matches) != 1 or environment.get('CI_JOB_NAME') != 'governance-plan'
            or matches[0].get('name') != 'governance-plan' or matches[0].get('status') != 'running'
            or matches[0].get('pipeline', {}).get('id') != int(identity['pipeline_id'])
            or matches[0].get('commit', {}).get('id') != identity['commit']):
        raise ValueError('native read-plan requires its actual running pipeline job')
    source, ref, commit = identity['source'], identity['ref'], identity['commit']
    if source == 'merge_request_event':
        iid = environment.get('CI_MERGE_REQUEST_IID', '')
        if not iid.isdecimal() or int(iid) <= 0:
            raise ValueError('native read-plan requires a merge request identifier')
        mr = read(f'/merge_requests/{iid}')
        if (not isinstance(mr, dict) or mr.get('iid') != int(iid) or mr.get('state') != 'opened'
                or mr.get('project_id') != int(PROJECT_ID) or mr.get('source_project_id') != int(PROJECT_ID)
                or mr.get('target_project_id') != int(PROJECT_ID) or mr.get('sha') != commit
                or mr.get('source_branch') != ref or mr.get('target_branch') != project['default_branch']
                or pipeline.get('ref') != f'refs/merge-requests/{iid}/head'):
            raise ValueError('native read-plan merge request head/project identity mismatch')
        identity['merge_request_iid'] = int(iid)
    elif pipeline.get('ref') != ref:
        raise ValueError('native read-plan ref differs from its pipeline')
    kind = 'tags' if environment.get('CI_COMMIT_TAG') else 'branches'
    branch = read(f'/repository/{kind}/' + urllib.parse.quote(ref, safe=''))
    if (not isinstance(branch, dict) or branch.get('name') != ref or branch.get('commit', {}).get('id') != commit
            or type(branch.get('protected')) is not bool or branch['protected'] != identity['protected_ref']):
        raise ValueError('native read-plan ref head/protection identity mismatch')
    if kind == 'tags' and (source != 'push' or not identity['protected_ref']):
        raise ValueError('native tag plans require an actual protected push tag')
    if source in {'web', 'schedule'} and (ref != project['default_branch'] or not identity['protected_ref']):
        raise ValueError('manual/scheduled native plans require the protected default branch')
    return {**identity, 'authority': 'read-only-plan', 'application_ready': False, 'remote_writes': False}


def anonymous_environment(environment: dict[str, str], url: str, runtime: Path) -> dict[str, str]:
    """Use an allowlist so provider/CLI/config fallbacks cannot acquire host authority."""
    home, temporary = runtime / 'home', runtime / 'tmp'
    home.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(parents=True, exist_ok=True)
    result = {key: environment[key] for key in ('PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT') if key in environment}
    result.update({'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'), 'TMPDIR': str(temporary),
                   'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPYCACHEPREFIX': str(runtime / 'pycache'),
                   'TF_IN_AUTOMATION': 'true', 'TF_INPUT': 'false', 'TF_CLI_CONFIG_FILE': os.devnull,
                   'TF_VAR_github_owner': 'bijux', 'TF_VAR_github_token': '',
                   'GITHUB_BASE_URL': url.rstrip('/') + '/', 'GITHUB_LEGACY_CLIENT': 'false',
                   'BIJUX_GITHUB_READ_URL': url.rstrip('/'), 'GH_PATH': str(runtime / 'no-github-cli'),
                   'GH_CONFIG_DIR': str(home / '.config/gh')})
    return result


def require_clean_source() -> None:
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        raise ValueError('native read-plan requires a clean exact source checkout')


def complete_receipt(identity: dict, plan: dict) -> dict:
    if (plan.get('status') != 'planned' or plan.get('privileged') is not False
            or plan.get('remote_writes') is not False or plan.get('commit') != identity['commit']
            or plan.get('input_digests') != input_digests()):
        raise ValueError('native read-plan requires the exact successful unprivileged plan receipt')
    return {**identity, 'status': 'planned', 'github_authentication': 'anonymous',
            'native_input_digests': {'.gitlab-ci.yml': hashlib.sha256((ROOT / '.gitlab-ci.yml').read_bytes()).hexdigest()},
            'plan': plan}


def main() -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    receipt = {'version': 1, 'status': 'failed', 'authority': 'read-only-plan',
               'remote_writes': False, 'application_ready': False, 'github_authentication': 'anonymous'}
    path = ARTIFACTS / 'governance-plan.json'
    try:
        identity = admit(dict(os.environ))
        receipt.update(identity)
        require_clean_source()
        inventory = validated_inventory()
        repositories = {row['name'] for row in github_development_inventory(inventory)['repositories']}
        with ReadGateway(repositories, ARTIFACTS / 'github-public-reads.json') as gateway:
            environment = anonymous_environment(dict(os.environ), gateway.url, ROOT / 'artifacts/plan')
            subprocess.run([sys.executable, '-B', '-m', 'scripts.execution.application', 'plan'],
                           cwd=ROOT, env=environment, timeout=600, check=True)
        if gateway.receipt['failures']:
            raise ValueError('anonymous read boundary recorded a failed or denied request')
        # Recheck source head and native job identity after all live reads complete.
        if admit(dict(os.environ)) != identity:
            raise ValueError('native read-plan source identity changed during planning')
        require_clean_source()
        plan = json.loads((ROOT / 'artifacts/governance/receipt.json').read_text())
        receipt = complete_receipt(identity, plan)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        receipt['error'] = str(error)
        path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        raise SystemExit(f'native anonymous governance plan failed: {error}') from None
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    print('Anonymous live governance plan completed; application and publication remain unauthorized.')


if __name__ == '__main__':
    main()
