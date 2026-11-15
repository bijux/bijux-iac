"""Bounded read-only GitLab.com transport, isolated from ambient credentials."""
from __future__ import annotations

from datetime import datetime, timezone
import copy
import hashlib
import json
from pathlib import Path
import re
import time
from types import ModuleType
from threading import RLock
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = 'https://gitlab.com/api/v4'
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_TRACE_BYTES = 32 * 1024 * 1024
MAX_PAGES = 100
MAX_REDIRECTS = 3


def source_module(name):
    path = Path(__file__).with_name(name + '.py')
    module = ModuleType('bijux_gitlab_native_' + name)
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


JOBS = source_module('jobs')
require = JOBS.require


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def storage_url(value):
    require(isinstance(value, str) and not any(character.isspace() for character in value), 'Invalid artifact redirect')
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ''
        valid_port = parsed.port in (None, 443)
    except ValueError:
        raise ValueError('Invalid artifact redirect') from None
    require(parsed.scheme == 'https' and valid_port and not parsed.username and not parsed.password and not parsed.fragment
            and (host.endswith('.gitlab-static.net') or host == 'storage.googleapis.com' or host.endswith('.s3.amazonaws.com')),
            'Artifact redirect is outside approved public GitLab storage')
    return value


def validated_project_path(value):
    require(isinstance(value, str) and len(value) <= 4096 and len(value.split('/')) >= 2
            and all(re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', part) for part in value.split('/')),
            'Native project namespace path is malformed')
    return value


class GitLabAPI:
    """Public reads by immutable project/job IDs; optional token is explicit only."""
    def __init__(self, project_id: int, *, project_path=None, read_token=None, opener=None, deadline_seconds=120, clock=time.monotonic):
        require(JOBS.positive(project_id), 'Positive immutable GitLab project ID is required')
        require(read_token is None or isinstance(read_token, str) and bool(read_token)
                and '\r' not in read_token and '\n' not in read_token, 'Dedicated read token is malformed')
        require(type(deadline_seconds) in (int, float) and 0 < deadline_seconds <= 180, 'Bounded public admission deadline is required')
        self.project_id, self._read_token = project_id, read_token
        self._expected_path = validated_project_path(project_path) if project_path is not None else None
        self._project = None
        self._snapshots = {}
        self._snapshot_lock = RLock()
        self._opener, self._clock = opener or build_opener(NoRedirect()), clock
        self._deadline = clock() + deadline_seconds
        self.observations = []

    def _remaining(self):
        remaining = self._deadline - self._clock()
        require(remaining > 0, 'Native GitLab evidence admission deadline expired')
        return min(20, remaining)

    def _read(self, endpoint, *, maximum, artifact=False, public_trace=False):
        prefix = '/projects/' + str(self.project_id) + '/'
        if public_trace:
            require(self._project is not None and isinstance(endpoint, str)
                    and re.fullmatch('/' + re.escape(self._project['path_with_namespace']) + r'/-/jobs/[1-9][0-9]*/raw', endpoint),
                    'Native raw trace endpoint differs from its verified project path')
        else:
            require(isinstance(endpoint, str) and (endpoint == prefix[:-1]
                    or re.fullmatch(re.escape(prefix) + r'(?:jobs/[1-9][0-9]*/artifacts|pipelines/[1-9][0-9]*/jobs\?include_retried=true&per_page=100&page=[1-9][0-9]*)', endpoint)),
                    'Native endpoint is outside its immutable project')
        url, redirected = ('https://gitlab.com' if public_trace else API) + endpoint, False
        for hop in range(MAX_REDIRECTS + 1):
            headers = {'Accept': 'text/plain' if public_trace else 'application/octet-stream' if artifact else 'application/json',
                       'User-Agent': 'bijux-gitlab-evidence', 'Cache-Control': 'no-cache'}
            if self._read_token is not None and not redirected and not public_trace:
                headers['PRIVATE-TOKEN'] = self._read_token
            request = Request(url, headers=headers, method='GET')
            try:
                response = self._opener.open(request, timeout=self._remaining())
            except HTTPError as error:
                code, location = error.code, error.headers.get('Location')
                error.close()
                if code in (301, 302, 303, 307, 308):
                    require((artifact or public_trace) and hop < MAX_REDIRECTS, 'Native metadata redirect or excessive storage redirects are refused')
                    url, redirected = storage_url(location), True
                    continue
                if code in (401, 403, 404):
                    raise ValueError('Public GitLab evidence read unavailable (HTTP ' + str(code)
                                     + '); a dedicated project read token may be required') from None
                raise ValueError('Native GitLab evidence transport failed with HTTP ' + str(code)) from None
            except (URLError, OSError):
                raise ValueError('Native GitLab evidence transport could not complete') from None
            with response:
                require(response.status == 200, 'Native evidence transport must return HTTP 200')
                retained_headers = {key.lower(): value for key, value in response.headers.items()}
                length = retained_headers.get('content-length')
                require(length is None or length.isdecimal() and int(length) <= maximum, 'Native evidence exceeds byte limit')
                pieces, count = [], 0
                while True:
                    remaining = self._remaining()
                    raw = getattr(getattr(response, 'fp', None), 'raw', None)
                    socket = getattr(raw, '_sock', None)
                    if socket is not None:
                        socket.settimeout(remaining)
                    piece = getattr(response, 'read1', response.read)(min(65536, maximum + 1 - count))
                    self._remaining()
                    if not piece:
                        break
                    count += len(piece)
                    require(count <= maximum, 'Native evidence exceeds byte limit')
                    pieces.append(piece)
                data = b''.join(pieces)
                require(length is None or int(length) == len(data), 'Native evidence byte count differs from transport')
            self.observations.append({'endpoint': endpoint, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                                      'storage_redirects': hop, 'headers': {key: value for key, value in retained_headers.items()
                                          if key in ('x-page', 'x-next-page', 'x-total', 'x-total-pages', 'content-length', 'content-type')}})
            return data, retained_headers
        raise ValueError('Native artifact redirect limit exceeded')

    def _json(self, endpoint, expected_type):
        data, headers = self._read(endpoint, maximum=MAX_JSON_BYTES)
        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, 'Duplicate native API JSON key')
                result[key] = value
            return result
        try:
            result = json.loads(data, object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise ValueError('Invalid native API JSON body') from None
        require(isinstance(result, expected_type), 'Native API JSON shape differs')
        return result, headers

    def pipeline_jobs(self, pipeline_id: int):
        require(JOBS.positive(pipeline_id), 'Positive immutable pipeline ID is required')
        with self._snapshot_lock:
            # A failed or incomplete refresh cannot leave an older snapshot
            # available as fresh ownership authority.
            self._snapshots.pop(pipeline_id, None)
            rows = self._pipeline_jobs(pipeline_id)
            self._snapshots[pipeline_id] = {row['id']: copy.deepcopy(row) for row in rows}
            return copy.deepcopy(rows)

    def _pipeline_jobs(self, pipeline_id):
        rows, identifiers = [], set()
        for page in range(1, MAX_PAGES + 1):
            endpoint = f'/projects/{self.project_id}/pipelines/{pipeline_id}/jobs?include_retried=true&per_page=100&page={page}'
            part, headers = self._json(endpoint, list)
            require(headers.get('x-page') == str(page) and 'x-next-page' in headers, 'Native pagination identity is missing or differs')
            following = headers['x-next-page']
            require(following in ('', str(page + 1)) and len(part) <= 100, 'Native pagination is incoherent')
            for row in part:
                require(isinstance(row, dict) and JOBS.positive(row.get('id')) and row['id'] not in identifiers, 'Duplicate or invalid native job ID')
                require(isinstance(row.get('pipeline'), dict) and row['pipeline'].get('id') == pipeline_id
                        and row['pipeline'].get('project_id') == self.project_id, 'Native page crosses pipeline ownership')
                identifiers.add(row['id']); rows.append(row)
            if not following:
                return rows
            require(len(part) == 100, 'Native job pagination is incomplete')
        raise ValueError('Native job pagination limit exceeded')

    def job(self, job_id: int, *, pipeline_id: int, commit_sha: str):
        require(JOBS.positive(job_id), 'Positive immutable job ID is required')
        require(JOBS.positive(pipeline_id), 'Positive immutable pipeline ID is required')
        with self._snapshot_lock:
            if pipeline_id not in self._snapshots:
                self.pipeline_jobs(pipeline_id)
            require(job_id in self._snapshots[pipeline_id], 'Immutable job is absent from its complete public pipeline snapshot')
            row = copy.deepcopy(self._snapshots[pipeline_id][job_id])
        JOBS.validate_identity(row, project_id=self.project_id, pipeline_id=pipeline_id, commit_sha=commit_sha)
        require(row['id'] == job_id, 'Authoritative native job ID differs')
        return row

    def project(self):
        with self._snapshot_lock:
            if self._project is None:
                row, _ = self._json(f'/projects/{self.project_id}', dict)
                require(type(row.get('id')) is int and row['id'] == self.project_id, 'Public project metadata returned another project ID')
                path = validated_project_path(row.get('path_with_namespace'))
                require(self._expected_path is None or path == self._expected_path, 'Public project path differs from native context')
                self._project = {'id': self.project_id, 'path_with_namespace': path}
            return dict(self._project)

    def trace(self, job_id: int, *, pipeline_id: int, commit_sha: str):
        row = self.job(job_id, pipeline_id=pipeline_id, commit_sha=commit_sha)
        require(row.get('status') == 'success', 'Native trace owner is not terminal success')
        path = self.project()['path_with_namespace']
        data, headers = self._read(f'/{path}/-/jobs/{job_id}/raw', maximum=MAX_TRACE_BYTES, public_trace=True)
        media_type = headers.get('content-type', '').split(';', 1)[0].strip().lower()
        require(media_type in ('text/plain', 'application/octet-stream', 'binary/octet-stream')
                and bool(data) and b'\x00' not in data
                and re.match(rb'\s*(?:<!doctype\s+html|<html\b|<head\b|<body\b|<form\b)', data[:4096], re.I) is None,
                'Public job trace is not native plaintext; HTML/sign-in/binary bodies are refused')
        return data

    def artifact(self, job_id: int, *, pipeline_id: int, commit_sha: str):
        row = self.job(job_id, pipeline_id=pipeline_id, commit_sha=commit_sha)
        require(row.get('status') == 'success' and row.get('erased_at') is None, 'Native artifact owner is not available terminal success')
        metadata = row.get('artifacts_file')
        require(isinstance(metadata, dict) and JOBS.positive(metadata.get('size')) and metadata['size'] <= MAX_ARCHIVE_BYTES
                and isinstance(metadata.get('filename'), str) and metadata['filename'], 'Native artifact archive metadata is missing or unbounded')
        expires = row.get('artifacts_expire_at')
        require(expires is None or JOBS.timestamp(expires) > datetime.now(timezone.utc), 'Native artifact expired')
        data, _ = self._read(f'/projects/{self.project_id}/jobs/{job_id}/artifacts', maximum=MAX_ARCHIVE_BYTES, artifact=True)
        require(len(data) == metadata['size'], 'Native artifact byte count differs from owning job metadata')
        return data
