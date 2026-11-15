"""Validate current source identities independently of planned publication routes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.inventory.repositories import ROOT, FAMILY_REPOSITORIES, unique_keys

AUTHORITY_PATH = ROOT / "inventory/repository-authority.json"

OSS_REPOSITORIES = {
    'bijux-iac', 'bijux-std', 'bijux-core', 'bijux-atlas', 'bijux-canon',
    'bijux-ontology', 'bijux-ro-crate-node', 'bijux-gnss',
}
RESEARCH_REPOSITORIES = {
    'bijux-pollenomics', 'bijux-genomics', 'bijux-proteomics', 'bijux-phylogenetics',
}
HUB_REPOSITORIES = {'bijux.github.io', 'bijux-masterclass'}
GITHUB_IDENTITIES = {
    'bijux-iac': 1223469411, 'bijux-std': 1212849789, 'bijux-core': 1037393076,
    'bijux-atlas': 1159562239, 'bijux-canon': 1200062971, 'bijux-ontology': 1423184160,
    'bijux-ro-crate-node': 1448868168, 'bijux-gnss': 1150170015,
    'bijux-pollenomics': 1189128916, 'bijux-genomics': 1150170629,
    'bijux-proteomics': 1134443068, 'bijux-phylogenetics': 1226329597,
    'bijux.github.io': 1037487722, 'bijux-masterclass': 1198852476,
}
GITLAB_PROJECTS = {'bijux-std': 88948041, 'bijux-iac': 88949971}
PERSONAL_MIRRORS = {'bijux-std': 88949531, 'bijux-iac': 88950131}


def require_keys(owner: str, value: object, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f'{owner}: authority keys must be {sorted(keys)}')


def validate_identity(owner: str, value: object, *, host: str, path: str, identifier: int | None,
                      provider: str) -> None:
    require_keys(owner, value, {'host', 'path', 'id', 'execution_provider'})
    if (value['host'] != host or value['path'] != path or value['execution_provider'] != provider
            or value['id'] != identifier or type(value['id']) is not type(identifier)):
        raise ValueError(f'{owner}: authority identity/provider differs from the approved route')


def validate_authority(inventory: dict) -> None:
    require_keys('authority inventory',inventory,{'version','repositories'})
    if type(inventory['version']) is not int or inventory['version'] != 1:
        raise ValueError('authority inventory version must be 1')
    if not isinstance(inventory['repositories'],list):
        raise ValueError('authority repositories must be a list')
    for row in inventory['repositories']:
        require_keys('authority repository',row,{'name','authority'})
        if not isinstance(row['name'],str):
            raise ValueError('authority repository name must be a string')
    names = [row['name'] for row in inventory['repositories']]
    if len(names) != 14 or set(names) != set(GITHUB_IDENTITIES):
        raise ValueError('authority must cover exactly the fourteen governed repositories')
    if set(FAMILY_REPOSITORIES) != set(names):
        raise ValueError('authority must cover the complete governed capability family')
    for row in inventory['repositories']:
        name = row['name']
        authority = row.get('authority')
        require_keys(name, authority, {'current', 'target', 'status', 'mirrors', 'mirror_publication'})
        if name in GITLAB_PROJECTS:
            validate_identity(name + ' current', authority['current'], host='gitlab.com',
                              path='bijux-oss/' + name, identifier=GITLAB_PROJECTS[name], provider='gitlab-ci')
        else:
            validate_identity(name + ' current', authority['current'], host='github.com',
                              path='bijux/' + name, identifier=GITHUB_IDENTITIES[name], provider='github-actions')
        if name in HUB_REPOSITORIES:
            if (authority['status'] != 'retained' or authority['target'] != authority['current']
                    or authority['mirrors'] != [] or authority['mirror_publication'] != {
                        'enabled': False, 'writer': None, 'branches': [], 'tags': []}
                    or authority['mirror_publication'].get('enabled') is not False):
                raise ValueError(f'{name}: retained GitHub authority cannot be enrolled or mirrored')
            continue
        namespace = 'bijux-oss/' if name in OSS_REPOSITORIES else 'bijux-edu/'
        validate_identity(name + ' target', authority['target'], host='gitlab.com',
                          path=namespace + name, identifier=GITLAB_PROJECTS.get(name), provider='gitlab-ci')
        if ((name in GITLAB_PROJECTS and authority['status'] not in ('preparing', 'active'))
                or (name not in GITLAB_PROJECTS and authority['status'] != 'planned')):
            raise ValueError(f'{name}: only declared control planes may activate; other product routes stay planned')
        mirrors = authority['mirrors']
        if not isinstance(mirrors, list) or len(mirrors) != 2:
            raise ValueError(f'{name}: both publication mirrors must be explicitly declared')
        seen_hosts = set()
        for mirror in mirrors:
            require_keys(name + ' mirror', mirror, {'host', 'path', 'id', 'execution_enabled'})
            host = mirror['host']
            expected_id = GITHUB_IDENTITIES[name] if host == 'github.com' else PERSONAL_MIRRORS.get(name)
            if (not isinstance(host, str) or host not in {'github.com', 'gitlab.com'} or host in seen_hosts
                    or mirror['path'] != 'bijux/' + name or mirror['execution_enabled'] is not False
                    or mirror['id'] != expected_id or type(mirror['id']) is not type(expected_id)):
                raise ValueError(f'{name}: mirror identity/execution differs from the approved route')
            seen_hosts.add(host)
        publication = authority['mirror_publication']
        enabled = name in GITLAB_PROJECTS and authority['status'] == 'active'
        if (publication != {'enabled': enabled, 'writer': 'protected-publisher',
                            'branches': ['main'], 'tags': 'approved-immutable'}
                or publication.get('enabled') is not enabled):
            raise ValueError(f'{name}: publication must match its recorded control-plane activation')


def load_authority(path: Path = AUTHORITY_PATH) -> dict:
    return json.loads(path.read_text(encoding='utf-8'),object_pairs_hook=unique_keys)


def canonical_authority(inventory: dict) -> str:
    rows = {row['name']:row for row in inventory['repositories']}
    return json.dumps({'version':inventory['version'],
        'repositories':[{'name':name,'authority':rows[name]['authority']} for name in GITHUB_IDENTITIES]},indent=2) + '\n'


def validated_authority() -> dict:
    inventory = load_authority()
    validate_authority(inventory)
    if AUTHORITY_PATH.read_text(encoding='utf-8') != canonical_authority(inventory):
        raise ValueError('authority formatting drift: run python3 -m scripts.inventory.authority --write')
    return inventory


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true',help='write canonical authority inventory formatting')
    args=parser.parse_args()
    try:
        inventory=load_authority()
        validate_authority(inventory)
        if args.write:
            AUTHORITY_PATH.write_text(canonical_authority(inventory),encoding='utf-8')
        else:
            validated_authority()
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(f"authority: OK ({len(inventory['repositories'])} repository roles)")


if __name__ == '__main__':
    main()
