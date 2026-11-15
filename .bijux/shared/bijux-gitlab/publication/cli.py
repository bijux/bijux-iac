"""Publish protected accepted main using isolated, destination-scoped credentials."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import uuid
import re
from types import ModuleType
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

def owned_module(name):
    path = Path(__file__).resolve().with_name(name + '.py')
    result = ModuleType('bijux_gitlab_publication_' + name)
    result.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), result.__dict__)
    return result


admission, coordinator, github, refs = (
    owned_module(name) for name in ('admission', 'coordinator', 'github', 'refs'))

GITLAB_HOST_KEY = 'gitlab.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAfuCHKVTjquxvt6CM6tdG4SLp1Btn/nOeHHE5UOzRdf\n'
MIRRORS = {88949531: 'bijux/bijux-std', 88950131: 'bijux/bijux-iac'}


def verify_gitlab_mirror(project_id, token, *, opener=None):
    if type(project_id) is not int or project_id not in MIRRORS:
        raise ValueError('Unapproved personal GitLab mirror identity')
    github.credential(token)
    request = Request('https://gitlab.com/api/v4/projects/' + str(project_id),
                      headers={'PRIVATE-TOKEN': token, 'Accept': 'application/json',
                               'User-Agent': 'bijux-mirror-readback'}, method='GET')
    try:
        with (opener or build_opener(ProxyHandler({}), github.NoRedirect())).open(request, timeout=20) as response:
            body = response.read(4 * 1024 * 1024 + 1)
            if response.status != 200 or response.geturl() != request.full_url or len(body) > 4 * 1024 * 1024:
                raise ValueError('Mirror settings response is unavailable or oversized')
    except (HTTPError, URLError, OSError):
        raise ValueError('Scoped GitLab mirror settings read-back failed') from None
    record = admission.strict_json(body)
    if (not isinstance(record, dict) or type(record.get('id')) is not int or record['id'] != project_id
            or record.get('path_with_namespace') != MIRRORS[project_id]
            or record.get('default_branch') != 'main'
            or record.get('builds_access_level') != 'disabled'
            or any(record.get(key) is not False for key in
                   ('shared_runners_enabled', 'group_runners_enabled', 'auto_devops_enabled'))):
        raise ValueError('Actual mirror identity and disabled execution settings must be readable')
    return {key: record[key] for key in ('id', 'path_with_namespace', 'default_branch', 'builds_access_level',
                                         'shared_runners_enabled', 'group_runners_enabled', 'auto_devops_enabled')}


@contextmanager
def credential_environment(root, original, token, ssh_key_file):
    """Never inherit interactive helpers or upload a credential-bearing run file."""
    key = Path(ssh_key_file)
    if not key.is_file() or key.is_symlink() or key.stat().st_size > 65536:
        raise ValueError('A protected destination SSH key file is required')
    output = root / 'artifacts/publication'
    if any(path.is_symlink() for path in (root / 'artifacts', output, output / 'receipts')):
        raise ValueError('Publication artifacts must not follow symbolic links')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='auth-', dir=output) as folder:
        private = Path(folder)
        home = private / 'home'
        home.mkdir()
        ssh = private / 'gitlab-key'
        ssh.touch(mode=0o600)
        ssh.write_bytes(key.read_bytes())
        hosts = private / 'known_hosts'
        hosts.write_text(GITLAB_HOST_KEY)
        askpass = private / 'github-askpass'
        askpass.write_text('#!/usr/bin/env python3\nimport os,sys\n'
                          'question=sys.argv[1] if len(sys.argv)>1 else ""\n'
                          'if "Username" in question: print("x-access-token")\n'
                          'elif "Password" in question: print(os.environ["BIJUX_PUBLICATION_GITHUB_TOKEN"])\n'
                          'else: raise SystemExit(1)\n')
        askpass.chmod(0o700)
        environment = {key: original[key] for key in ('PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT') if key in original}
        environment.update(HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
            GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
            GIT_ASKPASS=str(askpass), BIJUX_PUBLICATION_GITHUB_TOKEN=token,
            GIT_SSH_COMMAND='ssh -F /dev/null -o GlobalKnownHostsFile=/dev/null -o IdentitiesOnly=yes -o IdentityAgent=none -o StrictHostKeyChecking=yes '
                '-o UserKnownHostsFile=' + shlex.quote(str(hosts)) + ' -i ' + shlex.quote(str(ssh)))
        yield environment


def preview(root, remote, candidate, environment):
    before = refs.remote_main(root, remote, environment=environment)
    refs.git(root, 'fetch', '--quiet', '--no-tags', '--no-write-fetch-head', remote, before, environment=environment)
    refs.branch_action(root, before, candidate)


def named_branch(root, remote, branch, candidate, environment):
    refs.object_id(candidate)
    if re.fullmatch(r'publication/gitlab-[1-9][0-9]*-' + candidate[:12], branch) is None:
        raise ValueError('Only deterministic publication branches may be created')
    reference = 'refs/heads/' + branch
    rows = refs.git(root, 'ls-remote', '--refs', remote, reference, environment=environment).splitlines()
    if rows:
        if len(rows) != 1 or rows[0].split() != [candidate, reference]:
            raise ValueError('Existing publication branch differs from the accepted source')
        return {'before': candidate, 'after': candidate, 'status': 'unchanged'}
    refs.git(root, 'push', '--porcelain', remote, candidate + ':' + reference, environment=environment)
    rows = refs.git(root, 'ls-remote', '--refs', remote, reference, environment=environment).splitlines()
    if len(rows) != 1 or rows[0].split() != [candidate, reference]:
        raise ValueError('Publication branch acknowledgement differs')
    return {'before': None, 'after': candidate, 'status': 'created'}


def main():
    original = dict(os.environ)
    if original.get('CI_DEBUG_TRACE', 'false') == 'true':
        raise ValueError('Publishing credentials cannot run under debug tracing')
    root = Path(subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip()).resolve()
    proof = admission.admit(root, original)
    route = proof['route']
    token = github.installation_token(int(original['BIJUX_MIRROR_GITHUB_APP_ID']),
        int(original['BIJUX_MIRROR_GITHUB_INSTALLATION_ID']), original['BIJUX_MIRROR_GITHUB_APP_KEY'],
        route['github_repository_id'])
    gh = github.GitHub('bijux/' + proof['name'], route['github_repository_id'], token)
    read_token = original['BIJUX_MIRROR_GITLAB_READ_TOKEN']
    verify = lambda: verify_gitlab_mirror(route['personal_gitlab_project_id'], read_token)
    with credential_environment(root, original, token, original['BIJUX_MIRROR_GITLAB_SSH_KEY']) as environment:
        remotes = {'github': 'https://github.com/bijux/' + proof['name'] + '.git',
                   'gitlab': 'git@gitlab.com:bijux/' + proof['name'] + '.git'}
        gh.verify_mirror()
        verify()
        for remote in remotes.values():
            preview(root, remote, proof['commit_sha'], environment)
        def publish(host, branch, candidate):
            if branch == 'main':
                return refs.publish_branch(root, remotes[host], candidate, environment=environment)
            if host != 'github':
                raise ValueError('Feature branches are not published to the personal GitLab mirror')
            return named_branch(root, remotes[host], branch, candidate, environment)
        path = root / 'artifacts/publication/receipts' / (proof['commit_sha'] + '-' + str(proof['job_id']) + '.json')
        receipt = coordinator.coordinate(proof, gh, verify, publish, path)
    print(json.dumps({'status': receipt['status'], 'commit_sha': proof['commit_sha']}))
    return 0 if receipt['status'] == 'published' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (KeyError, ValueError, OSError, subprocess.SubprocessError) as error:
        output = Path('artifacts/publication/receipts')
        try:
            coordinator.retain(output / ('blocked-' + uuid.uuid4().hex + '.json'),
                               {'schema_version': 1, 'status': 'blocked', 'error_type': type(error).__name__})
        except (OSError, ValueError):
            print('Publication receipt output was refused', file=sys.stderr)
        print('Mirror publication is blocked:', type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
