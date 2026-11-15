"""Publish accepted GitLab evidence to a bounded, Actions-disabled GitHub mirror."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = 'https://api.github.com'
MAX_BODY = 4 * 1024 * 1024
MAX_PAGES = 10
PERMISSIONS = {'contents': 'write', 'pull_requests': 'write', 'statuses': 'write',
               'workflows': 'write', 'administration': 'read', 'metadata': 'read'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive(value):
    return type(value) is int and value > 0


def object_id(value):
    require(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{40}', value),
            'Publication requires an immutable commit SHA')
    return value


def credential(value):
    require(isinstance(value, str) and bool(value) and len(value) <= 16384
            and all(32 < ord(character) < 127 for character in value),
            'Explicit publication authentication is required')
    return value


def canonical_url(value, operation):
    require(isinstance(value, str) and re.fullmatch(
        r'https://gitlab[.]com/bijux-oss/[A-Za-z0-9_][A-Za-z0-9_.-]*/-/' + operation + r'/[1-9][0-9]*', value),
        'Canonical native GitLab evidence URL is required')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPFailure(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__('GitHub publication HTTP request failed (' + str(code) + ')')


class APIClient:
    def __init__(self, token, opener=None):
        self._token = credential(token)
        self._opener = opener or build_opener(NoRedirect())

    def _open(self, request, remaining):
        for attempt in range(3):
            try:
                return self._opener.open(request, timeout=remaining())
            except HTTPError as error:
                code = error.code
                retry_after = (error.headers or {}).get('Retry-After')
                error.close()
                delay = 0.25 * (attempt + 1) if code in (502, 503, 504) else None
                if code == 429 and isinstance(retry_after, str) and re.fullmatch(r'[0-2]', retry_after.strip()):
                    delay = int(retry_after.strip())
                if request.get_method() != 'GET' or attempt == 2 or delay is None:
                    raise HTTPFailure(code) from None
                require(delay < remaining(), 'GitHub publication retry exceeds its HTTP deadline')
                if delay:
                    time.sleep(delay)

    def request(self, method, path, payload=None, *, deadline=None, expected=None):
        require(method in {'GET', 'POST'} and isinstance(path, str)
                and re.fullmatch(r'/[A-Za-z0-9_./%?=&:+-]+', path), 'Unsupported GitHub publication request')
        deadline = min(deadline, time.monotonic() + 20) if deadline is not None else time.monotonic() + 20
        def remaining():
            result = deadline - time.monotonic()
            require(result > 0, 'GitHub publication HTTP deadline expired')
            return min(20, result)
        request = Request(API + path, data=None if payload is None else json.dumps(payload).encode(),
            headers={'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + self._token,
                     'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2026-03-10',
                     'User-Agent': 'bijux-accepted-publication'}, method=method)
        try:
            with self._open(request, remaining) as response:
                require(response.status == (expected if expected is not None else 201 if method == 'POST' else 200),
                        'GitHub publication returned an unexpected HTTP status')
                require(response.geturl() == request.full_url, 'GitHub publication redirects are refused')
                headers = {key.lower(): value for key, value in response.headers.items()}
                require(headers.get('content-type', '').split(';')[0].strip().lower() == 'application/json',
                        'GitHub publication requires a native JSON response')
                length = headers.get('content-length')
                require(length is None or length.isdecimal() and int(length) <= MAX_BODY,
                        'GitHub publication response exceeds its byte limit')
                pieces, count = [], 0
                while True:
                    timeout = remaining()
                    raw = getattr(getattr(response, 'fp', None), 'raw', None)
                    socket = getattr(raw, '_sock', None)
                    if socket is not None:
                        socket.settimeout(timeout)
                    piece = getattr(response, 'read1', response.read)(min(65536, MAX_BODY + 1 - count))
                    remaining()
                    if not piece:
                        break
                    count += len(piece)
                    require(count <= MAX_BODY, 'GitHub publication response exceeds its byte limit')
                    pieces.append(piece)
                require(length is None or int(length) == count, 'GitHub publication response is incomplete')
                body = b''.join(pieces)
        except HTTPError as error:
            code = error.code
            error.close()
            raise HTTPFailure(code) from None
        except (URLError, OSError):
            raise ValueError('GitHub publication transport is unavailable') from None
        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, 'GitHub publication response has duplicate JSON keys')
                result[key] = value
            return result
        try:
            value = json.loads(body, object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise ValueError('GitHub publication response is not unambiguous JSON') from None
        return value, headers


class GitHub:
    def __init__(self, repository: str, repository_id: int, token: str, opener=None):
        require(isinstance(repository, str) and re.fullmatch(r'bijux/[A-Za-z0-9_][A-Za-z0-9_.-]*', repository)
                and '..' not in repository and positive(repository_id), 'Exact Bijux publication repository is required')
        self.repository, self.repository_id = repository, repository_id
        self._prefix = '/repos/' + repository
        self._api = APIClient(token, opener)

    def _read(self, suffix, *, deadline=None):
        return self._api.request('GET', self._prefix + suffix, deadline=deadline)[0]

    def _write(self, suffix, payload, *, expected=201):
        return self._api.request('POST', self._prefix + suffix, payload, expected=expected)[0]

    def _repository(self, row):
        require(isinstance(row, dict) and type(row.get('id')) is int and row['id'] == self.repository_id
                and row.get('full_name') == self.repository, 'GitHub mirror repository identity differs')

    def verify_mirror(self):
        row = self._read('')
        self._repository(row)
        require(row.get('default_branch') == 'main' and row.get('archived') is False and row.get('disabled') is False,
                'GitHub mirror must have an available main default branch')
        settings = self._read('/actions/permissions')
        require(isinstance(settings, dict) and settings.get('enabled') is False,
                'GitHub Actions must remain disabled on the publication mirror')
        return {'repository': self.repository, 'repository_id': self.repository_id, 'actions_enabled': False}

    def status(self, sha, evidence_url):
        object_id(sha)
        canonical_url(evidence_url, 'pipelines')
        self.verify_mirror()
        wanted = {'state': 'success', 'context': 'gitlab / validation', 'target_url': evidence_url}
        row = self._write('/statuses/' + sha, {**wanted, 'description': 'Validated by the canonical GitLab pipeline'})
        require(isinstance(row, dict) and all(row.get(key) == value for key, value in wanted.items()),
                'GitHub did not acknowledge the native GitLab validation status')
        self.verify_mirror()
        return wanted

    def _pr(self, row, sha, *, number=None, branch=None):
        require(isinstance(row, dict) and positive(row.get('number'))
                and (number is None or row['number'] == number), 'Actual GitHub publication PR identity is required')
        expected_url = 'https://github.com/' + self.repository + '/pull/' + str(row['number'])
        require(row.get('html_url') == expected_url and row.get('state') in {'open', 'closed'},
                'GitHub publication PR URL or state differs')
        head, base = row.get('head'), row.get('base')
        require(isinstance(head, dict) and isinstance(base, dict) and head.get('sha') == sha
                and base.get('ref') == 'main', 'GitHub publication PR source or target differs')
        self._repository(head.get('repo'))
        self._repository(base.get('repo'))
        require(isinstance(head.get('ref'), str) and re.fullmatch(
            r'publication/gitlab-[1-9][0-9]*-' + sha[:12], head['ref'])
            and (branch is None or head['ref'] == branch), 'GitHub publication PR branch differs')
        return {'number': row['number'], 'url': expected_url, 'head_sha': sha, 'merged': row.get('merged') is True}

    def _existing(self, branch, sha):
        rows = []
        for page in range(1, MAX_PAGES + 1):
            query = urlencode({'state': 'all', 'head': 'bijux:' + branch, 'base': 'main', 'per_page': 100, 'page': page})
            path = self._prefix + '/pulls?' + query
            part, headers = self._api.request('GET', path)
            require(isinstance(part, list) and len(part) <= 100, 'GitHub publication PR inventory is malformed')
            for row in part:
                self._pr(row, sha, branch=branch)
            rows.extend(part)
            require(len(rows) <= 1, 'GitHub publication PR inventory is ambiguous')
            links = headers.get('link', '')
            matches = re.findall(r'<([^>]+)>;\s*rel="next"', links)
            require(len(matches) <= 1, 'GitHub publication pagination is ambiguous')
            if not matches:
                require('next' not in links, 'GitHub publication pagination is malformed')
                return rows[0] if rows else None
            parsed = urlsplit(matches[0])
            require(parsed.scheme == 'https' and parsed.netloc == 'api.github.com'
                    and parsed.path == self._prefix + '/pulls' and not parsed.fragment
                    and parse_qs(parsed.query) == {'state': ['all'], 'head': ['bijux:' + branch], 'base': ['main'],
                                                 'per_page': ['100'], 'page': [str(page + 1)]},
                    'GitHub publication pagination leaves its exact PR inventory')
        raise ValueError('GitHub publication PR pagination exceeded its bound')

    def _label(self, number):
        suffix = '/labels/gitlab-publication'
        try:
            label = self._read(suffix)
        except HTTPFailure as error:
            if error.code != 404:
                raise
            try:
                label = self._write('/labels', {'name': 'gitlab-publication', 'color': '6f42c1',
                                              'description': 'Accepted canonical GitLab publication'})
            except HTTPFailure as raced:
                if raced.code != 422:
                    raise
                label = self._read(suffix)
        require(isinstance(label, dict) and label.get('name') == 'gitlab-publication',
                'GitHub publication label was not acknowledged')
        labels = self._write('/issues/' + str(number) + '/labels', {'labels': ['gitlab-publication']}, expected=200)
        require(isinstance(labels, list) and any(isinstance(row, dict) and row.get('name') == 'gitlab-publication' for row in labels),
                'GitHub publication PR label was not acknowledged')

    def ensure_pr(self, branch, sha, mr_url, evidence_url):
        object_id(sha)
        canonical_url(mr_url, 'merge_requests')
        canonical_url(evidence_url, 'pipelines')
        require(mr_url.split('/-/')[0] == evidence_url.split('/-/')[0],
                'Canonical review and validation must belong to the same native project')
        iid = mr_url.rsplit('/', 1)[1]
        require(branch == 'publication/gitlab-' + iid + '-' + sha[:12],
                'Publication branch must bind the canonical MR and accepted commit')
        self.verify_mirror()
        existing = self._existing(branch, sha)
        if existing is None:
            ref = self._read('/git/ref/heads/' + branch)
            require(isinstance(ref, dict) and ref.get('ref') == 'refs/heads/' + branch
                    and isinstance(ref.get('object'), dict) and ref['object'].get('type') == 'commit'
                    and ref['object'].get('sha') == sha, 'GitHub publication head must already identify the accepted commit')
            try:
                row = self._write('/pulls', {'title': 'Publish accepted GitLab review !' + iid,
                    'head': branch, 'base': 'main', 'maintainer_can_modify': False,
                    'body': 'Canonical GitLab merge request: ' + mr_url + '\n\nValidation evidence: ' + evidence_url + '\n'})
            except HTTPFailure as error:
                if error.code != 422:
                    raise
                existing = self._existing(branch, sha)
                require(existing is not None, 'GitHub publication PR creation was not acknowledged')
                row = self._read('/pulls/' + str(existing['number']))
        else:
            row = self._read('/pulls/' + str(existing['number']))
        result = self._pr(row, sha, number=existing['number'] if existing is not None else None, branch=branch)
        require(isinstance(row.get('body'), str) and mr_url in row['body'] and evidence_url in row['body'],
                'GitHub publication PR must link canonical review and validation evidence')
        require(row['state'] == 'open' or row.get('merged') is True,
                'Closed unmerged GitHub publication PR cannot be replaced')
        self._label(result['number'])
        self.verify_mirror()
        return result

    def acknowledge_pr(self, number, sha):
        require(positive(number), 'Actual GitHub publication PR number is required')
        object_id(sha)
        self.verify_mirror()
        deadline = time.monotonic() + 45
        for attempt in range(6):
            row = self._read('/pulls/' + str(number), deadline=deadline)
            result = self._pr(row, sha, number=number)
            if row.get('merged') is True and row['state'] == 'closed':
                self.verify_mirror()
                return result
            require(row.get('merged') is False, 'GitHub publication merged acknowledgement is missing')
            if attempt < 5:
                require(time.monotonic() + 2 < deadline, 'GitHub publication acknowledgement deadline expired')
                time.sleep(2)
        raise ValueError('GitHub has not acknowledged the exact publication PR as merged')


def installation_token(app_id, installation_id, key_path, repository_id, *, opener=None):
    """Mint and independently scope an ephemeral token; credentials stay in memory."""
    require(all(positive(value) for value in (app_id, installation_id, repository_id)),
            'Explicit publisher App, installation, and repository IDs are required')
    key = Path(key_path)
    require(key.is_file() and not key.is_symlink(), 'A protected publisher App key file is required')
    encode = lambda body: base64.urlsafe_b64encode(body).rstrip(b'=')
    now = int(time.time())
    header = encode(json.dumps({'alg': 'RS256', 'typ': 'JWT'}, separators=(',', ':')).encode())
    claims = encode(json.dumps({'iat': now - 30, 'exp': now + 480, 'iss': str(app_id)}, separators=(',', ':')).encode())
    message = header + b'.' + claims
    try:
        signature = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(key),
                                    '-sigopt', 'rsa_padding_mode:pkcs1'], input=message,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        raise ValueError('Publisher App JWT signing failed') from None
    require(bool(signature), 'Publisher App JWT signature is unavailable')
    api = APIClient((message + b'.' + encode(signature)).decode('ascii'), opener)
    installation, _ = api.request('GET', '/app/installations/' + str(installation_id))
    require(isinstance(installation, dict) and type(installation.get('id')) is int and installation['id'] == installation_id
            and type(installation.get('app_id')) is int and installation['app_id'] == app_id
            and isinstance(installation.get('account'), dict) and installation['account'].get('login') == 'bijux'
            and installation.get('repository_selection') == 'selected' and installation.get('suspended_at') is None
            and installation.get('permissions') == PERMISSIONS, 'Publisher App installation identity or permissions differ')
    minted, _ = api.request('POST', '/app/installations/' + str(installation_id) + '/access_tokens',
                            {'repository_ids': [repository_id], 'permissions': PERMISSIONS})
    require(isinstance(minted, dict) and minted.get('permissions') == PERMISSIONS
            and minted.get('repository_selection') == 'selected', 'Publisher token has unverified scope or permissions')
    token = credential(minted.get('token'))
    try:
        expires = datetime.fromisoformat(minted['expires_at'].replace('Z', '+00:00'))
        seconds = (expires - datetime.now(timezone.utc)).total_seconds()
    except (KeyError, TypeError, AttributeError, ValueError):
        raise ValueError('Publisher token expiry is unavailable') from None
    require(0 < seconds <= 3600, 'Publisher token lifetime exceeds its permitted bound')
    repositories, headers = APIClient(token, opener).request('GET', '/installation/repositories?per_page=100')
    require(isinstance(repositories, dict) and type(repositories.get('total_count')) is int and repositories['total_count'] == 1
            and isinstance(repositories.get('repositories'), list) and len(repositories['repositories']) == 1
            and not headers.get('link'), 'Publisher token must expose exactly one repository')
    repository = repositories['repositories'][0]
    require(isinstance(repository, dict) and type(repository.get('id')) is int and repository['id'] == repository_id
            and isinstance(repository.get('full_name'), str)
            and re.fullmatch(r'bijux/[A-Za-z0-9_][A-Za-z0-9_.-]*', repository['full_name'])
            and isinstance(repository.get('owner'), dict) and repository['owner'].get('login') == 'bijux',
            'Publisher token repository read-back differs from its requested scope')
    return token
