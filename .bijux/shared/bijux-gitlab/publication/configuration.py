"""Compose the protected child independently of physical validation contracts."""
from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType


def child_pipeline():
    path = Path(__file__).resolve().parents[1] / 'pipeline.py'
    pipeline = ModuleType('bijux_publication_pipeline')
    pipeline.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), pipeline.__dict__)
    condition = ('$CI_SERVER_URL == "https://gitlab.com" && '
        '(($CI_PROJECT_ID == "88948041" && $CI_PROJECT_PATH == "bijux-oss/bijux-std") || '
        '($CI_PROJECT_ID == "88949971" && $CI_PROJECT_PATH == "bijux-oss/bijux-iac")) && '
        '$CI_COMMIT_BRANCH == "main" && $CI_COMMIT_REF_PROTECTED == "true" && '
        '$CI_PIPELINE_SOURCE == "parent_pipeline"')
    return {
        'workflow': {'rules': [{'if': condition}, {'when': 'never'}]},
        'stages': ['publication'],
        'variables': {'GIT_DEPTH': '0', 'PYTHONDONTWRITEBYTECODE': '1'},
        'publication / mirrors': {
            'stage': 'publication', 'image': pipeline.PLAYWRIGHT_IMAGE,
            'tags': ['saas-linux-medium-amd64'], 'timeout': '10 minutes',
            'interruptible': False, 'resource_group': 'accepted-mirror-publication',
            'environment': {'name': 'publication', 'action': 'prepare'},
            'before_script': ['apt-get update && apt-get install --yes --no-install-recommends openssh-client openssl'],
            'script': ['case "$CI_PROJECT_ID" in\n'
                       '  88948041) python3 -B shared/bijux-gitlab/publication/cli.py ;;\n'
                       '  88949971) python3 -B .bijux/shared/bijux-gitlab/publication/cli.py ;;\n'
                       '  *) exit 1 ;;\nesac'],
            'artifacts': {'when': 'always', 'expire_in': '1 year', 'paths': ['artifacts/publication/receipts/']},
        },
    }


if __name__ == '__main__':
    path = Path(__file__).resolve().parents[1] / 'ci/publication.yml'
    path.write_text(json.dumps(child_pipeline(), indent=2) + '\n')
