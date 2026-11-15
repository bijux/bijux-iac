"""Qualify complete native job execution without inventing provider attempts."""
from __future__ import annotations

import copy
from datetime import datetime
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive(value):
    return type(value) is int and value > 0


def timestamp(value):
    require(isinstance(value, str) and bool(value), 'Actual timezone-bound GitLab timestamp is required')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as error:
        raise ValueError('Invalid native GitLab timestamp') from error
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, 'Timezone-bound GitLab timestamp is required')
    return parsed


def validate_identity(row, *, project_id, pipeline_id, commit_sha):
    require(positive(project_id) and positive(pipeline_id), 'Positive native project and pipeline IDs are required')
    require(isinstance(commit_sha, str) and re.fullmatch(r'[a-f0-9]{40}', commit_sha), 'Full native commit SHA is required')
    require(isinstance(row, dict) and positive(row.get('id'))
            and isinstance(row.get('name'), str) and bool(row['name']), 'Actual native job ID and name are required')
    pipeline = row.get('pipeline', {})
    require(isinstance(pipeline, dict) and positive(pipeline.get('project_id')) and positive(pipeline.get('id'))
            and pipeline.get('project_id') == project_id
            and pipeline.get('id') == pipeline_id and pipeline.get('sha') == commit_sha,
            'Job belongs to another project, pipeline or source')
    require(isinstance(row.get('commit'), dict) and row['commit'].get('id') == commit_sha,
            'Job commit differs from the pipeline source')
    return row


def qualify_jobs(jobs, *, project_id: int, pipeline_id: int, commit_sha: str,
                 required_names: set[str], frontend_names: set[str]) -> dict:
    require(isinstance(required_names, set) and bool(required_names)
            and all(isinstance(name, str) and bool(name) for name in required_names), 'Finite required job names are required')
    require(isinstance(frontend_names, set) and frontend_names <= required_names, 'Frontend names must belong to required execution')
    require(isinstance(jobs, list) and 0 < len(jobs) <= 10000, 'Bounded complete native job inventory is required')
    identifiers, latest = set(), {}
    for row in jobs:
        validate_identity(row, project_id=project_id, pipeline_id=pipeline_id, commit_sha=commit_sha)
        require(row['id'] not in identifiers, 'Duplicate native job ID')
        identifiers.add(row['id'])
        previous = latest.get(row['name'])
        if previous is None or previous['id'] < row['id']:
            latest[row['name']] = row
    require(required_names <= set(latest), 'Missing required native job execution')
    selected = {}
    for name in sorted(required_names):
        row = latest[name]
        require(row.get('status') == 'success' and row.get('allow_failure') is False,
                'Latest required job is not terminal success: ' + name)
        require(isinstance(row.get('runner'), dict) and positive(row['runner'].get('id')), 'Actual native runner ownership is required')
        created, started, finished = (timestamp(row.get(key)) for key in ('created_at', 'started_at', 'finished_at'))
        require(created <= started <= finished, 'Native job timestamps are out of order')
        seconds = (finished - started).total_seconds()
        if name in frontend_names:
            require(seconds < 180, 'Frontend job reached the strict 180-second whole-job limit: ' + name)
        selected[name] = {'job_id': row['id'], 'seconds': seconds, 'queue_seconds': (started - created).total_seconds(),
                          'frontend': name in frontend_names, 'raw_job': copy.deepcopy(row)}
    return {'schema': 1, 'provider': 'gitlab', 'status': 'passed', 'project_id': project_id,
            'pipeline_id': pipeline_id, 'commit_sha': commit_sha, 'strict_frontend_limit_seconds': 180,
            'selected_jobs': selected, 'raw_jobs': copy.deepcopy(jobs),
            'limits': ['Latest executions are selected by immutable native job ID; no global attempt is inferred.',
                       'Native case, runtime and artifact-body qualification remain mandatory.',
                       'Non-required jobs are retained without claiming their execution succeeded.']}
