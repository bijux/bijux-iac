"""Preserve immutable object identities and refuse rewinds or divergent refs."""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess


def object_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r'[a-f0-9]{40}', value) is None:
        raise ValueError('An immutable Git object identity is required')
    return value


def git(root: Path, *arguments: str, environment=None) -> str:
    result = subprocess.run(['git', '-c', 'credential.helper=', '-c', 'http.followRedirects=false', '-C', str(root), *arguments],
                            env={**(os.environ if environment is None else environment), 'GIT_TERMINAL_PROMPT': '0'},
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode:
        raise ValueError('Git publication operation failed: ' + arguments[0])
    return result.stdout.strip()


def branch_action(root: Path, current: str, candidate: str) -> str:
    for value in (current, candidate):
        object_id(value)
        if git(root, 'cat-file', '-t', value) != 'commit':
            raise ValueError('A default branch must identify an actual commit')
    if current == candidate:
        return 'unchanged'
    result = subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', current, candidate],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode:
        raise ValueError('Publication refuses a destination rewind or divergent history')
    return 'advance'


def tag_action(current: str, candidate: str) -> str:
    object_id(candidate)
    if not current:
        return 'create'
    if object_id(current) != candidate:
        raise ValueError('Publication refuses to replace an existing tag object')
    return 'unchanged'


def remote_main(root: Path, remote: str, *, environment=None) -> str:
    rows = git(root, 'ls-remote', '--refs', remote, 'refs/heads/main', environment=environment).splitlines()
    if len(rows) != 1 or rows[0].split()[1:] != ['refs/heads/main']:
        raise ValueError('Publication requires one existing destination main branch')
    return object_id(rows[0].split()[0])


def publish_branch(root: Path, remote: str, candidate: str, *, environment=None) -> dict:
    object_id(candidate)
    before = remote_main(root, remote, environment=environment)
    git(root, 'fetch', '--quiet', '--no-tags', '--no-write-fetch-head', remote, before, environment=environment)
    action = branch_action(root, before, candidate)
    if action == 'advance':
        git(root, 'push', '--porcelain', remote, candidate + ':refs/heads/main', environment=environment)
    after = remote_main(root, remote, environment=environment)
    if after != candidate:
        raise ValueError('Destination did not acknowledge the exact accepted commit')
    return {'before': before, 'after': after, 'status': 'published' if action == 'advance' else 'unchanged'}
