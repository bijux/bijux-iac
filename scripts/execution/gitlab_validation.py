"""Bind nonprivileged validation to its canonical GitLab checkout and job identity."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from scripts.inventory.repositories import ROOT

PROJECT_PATH = 'bijux-oss/bijux-iac'
PROJECT_ID = '88949971'
ARTIFACTS = ROOT / 'artifacts/gitlab'


def context(environment: dict[str, str]) -> dict:
    if (environment.get('CI_SERVER_URL') != 'https://gitlab.com'
            or environment.get('CI_PROJECT_PATH') != PROJECT_PATH
            or environment.get('CI_PROJECT_ID') != PROJECT_ID):
        raise ValueError('validation requires the canonical GitLab project identity')
    commit = environment.get('CI_COMMIT_SHA', '')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or commit != head:
        raise ValueError('validation source must equal the checked-out commit')
    for key in ('CI_PIPELINE_ID', 'CI_JOB_ID'):
        value = environment.get(key, '')
        if not value.isdecimal() or int(value) <= 0:
            raise ValueError('validation requires positive pipeline and job identifiers')
    source = environment.get('CI_PIPELINE_SOURCE')
    if source not in {'push', 'merge_request_event', 'web', 'schedule'}:
        raise ValueError('validation requires a supported pipeline source')
    if (not environment.get('CI_COMMIT_REF_NAME')
            or environment.get('CI_COMMIT_REF_PROTECTED') not in {'true', 'false'}):
        raise ValueError('validation requires an explicit source ref and protection state')
    return {'version': 1, 'authority': 'validation-only',
            'project_path': PROJECT_PATH, 'project_id': PROJECT_ID, 'commit': commit,
            'pipeline_id': environment['CI_PIPELINE_ID'], 'job_id': environment['CI_JOB_ID'],
            'source': source, 'ref': environment['CI_COMMIT_REF_NAME'],
            'protected_ref': environment['CI_COMMIT_REF_PROTECTED'] == 'true'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['context', 'blocked-plan'])
    args = parser.parse_args()
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if args.operation == 'blocked-plan':
        reason = ('GitLab live planning requires a dedicated read-only GitHub credential '
                  'and reviewed provider admission; GitHub workflow credentials/context cannot be reused. '
                  'No infrastructure apply or publication is authorized by this validation pipeline.')
        receipt = {'version': 1, 'status': 'blocked', 'reason': reason,
                   'remote_writes': False, 'application_ready': False}
        (ARTIFACTS / 'governance-plan-blocked.json').write_text(json.dumps(receipt, indent=2) + '\n')
        raise SystemExit(reason)
    receipt = context(dict(os.environ))
    (ARTIFACTS / 'context.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    main()
