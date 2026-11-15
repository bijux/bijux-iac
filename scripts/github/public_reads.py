"""One bounded anonymous GitHub snapshot shared by Python and Terraform reads."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def strict_json(body: bytes) -> object:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate JSON object member')
            value[key] = item
        return value
    return json.loads(body, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON value')))


class ReadGateway:
    """Serve only accepted repository reads; retain a receipt, never credentials."""
    def __init__(self, repositories: set[str], evidence_path: Path, *, opener=None,
                 request_limit: int = 45, max_seconds: int = 180):
        self.repositories = repositories
        self.evidence_path = evidence_path
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()).open
        self.request_limit = request_limit
        self.max_seconds = max_seconds
        self.cache: dict[str, tuple[int, bytes]] = {}
        self.lock = threading.Lock()
        self.receipt = {'version': 1, 'authentication': 'anonymous', 'remote_writes': False,
                        'request_limit': request_limit, 'max_seconds': max_seconds,
                        'upstream_requests': 0, 'cache_hits': 0, 'failures': 0, 'requests': []}

    def route(self, target: str) -> str:
        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme or parsed.netloc or parsed.fragment or '%' in parsed.path:
            raise ValueError('absolute, escaped and fragmented routes are forbidden')
        path = parsed.path
        if path.startswith('/api/v3/'):
            path = path[len('/api/v3'):]
        pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True) if parsed.query else []
        query = dict(pairs)
        if len(query) != len(pairs):
            raise ValueError('duplicate query members are forbidden')
        if path == '/orgs/bijux' and not query:
            return path
        match = re.fullmatch(r'/repos/bijux/([^/]+)(/rulesets(?:/[1-9][0-9]*)?)?', path)
        if not match or match[1] not in self.repositories:
            raise ValueError('route is outside the accepted read-only inventory')
        suffix = match[2] or ''
        if suffix == '/rulesets':
            if set(query) - {'per_page', 'page'}:
                raise ValueError('ruleset-list query is not allowlisted')
            for key, value in query.items():
                if not value.isdecimal() or not 1 <= int(value) <= (100 if key == 'per_page' else 10):
                    raise ValueError('ruleset pagination is outside its bound')
            query.setdefault('per_page', '100')
            query.setdefault('page', '1')
        elif suffix.startswith('/rulesets/'):
            if query and query != {'includes_parents': 'false'}:
                raise ValueError('only direct ruleset detail reads are permitted')
        elif query:
            raise ValueError('repository metadata query is not allowlisted')
        return path + ('?' + urllib.parse.urlencode(sorted(query.items())) if query else '')

    def fetch(self, route: str) -> tuple[int, bytes]:
        with self.lock:
            if time.monotonic() >= self.deadline:
                raise ValueError('anonymous read snapshot exceeded its time budget')
            if route in self.cache:
                self.receipt['cache_hits'] += 1
                return self.cache[route]
            for attempt in range(3):
                remaining = self.deadline - time.monotonic()
                if self.receipt['upstream_requests'] >= self.request_limit or remaining <= 0:
                    raise ValueError('anonymous read request/time budget exhausted')
                request = urllib.request.Request('https://api.github.com' + route, headers={
                    'Accept': 'application/vnd.github+json', 'User-Agent': 'bijux-iac-read-plan',
                    'X-GitHub-Api-Version': '2022-11-28'})
                self.receipt['upstream_requests'] += 1
                status, body, headers = 0, b'', {}
                try:
                    with self.opener(request, timeout=min(20, remaining)) as response:
                        status, headers = response.status, response.headers
                        body = response.read(1024 * 1024 + 1)
                except urllib.error.HTTPError as error:
                    status, headers = error.code, error.headers
                    if status == 404 and route == '/orgs/bijux':
                        body = error.read(1024 * 1024 + 1)
                    else:
                        retry_after = headers.get('Retry-After', '')
                        retryable = status in {429, 500, 502, 503, 504} or (
                            status == 403 and retry_after.isdecimal() and int(retry_after) <= 2)
                        self.receipt['requests'].append({'path': route, 'status': status})
                        if retryable and attempt < 2:
                            time.sleep(min(2, int(retry_after)) if retry_after.isdecimal() else 1)
                            continue
                        raise ValueError(f'anonymous GitHub GET failed ({status}); no authenticated fallback') from None
                if status not in {200, 404} or len(body) > 1024 * 1024:
                    raise ValueError('unexpected response status or oversized anonymous JSON')
                strict_json(body)
                self.receipt['requests'].append({'path': route, 'status': status,
                                                'sha256': hashlib.sha256(body).hexdigest(),
                                                'bytes': len(body),
                                                'rate_limit_remaining': headers.get('X-RateLimit-Remaining')})
                self.cache[route] = status, body
                return status, body
            raise ValueError('anonymous GitHub retry budget exhausted')

    def __enter__(self):
        gateway = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                try:
                    if any(self.headers.get(key) for key in ('Authorization', 'Proxy-Authorization', 'Cookie')):
                        raise ValueError('credentials are forbidden at the anonymous gateway')
                    status, body = gateway.fetch(gateway.route(self.path))
                except (ValueError, OSError, urllib.error.URLError) as error:
                    gateway.receipt['failures'] += 1
                    status, body = 502, json.dumps({'message': str(error)}).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def denied(self):
                gateway.receipt['failures'] += 1
                self.send_error(405, 'anonymous governance planning permits GET only')

            do_POST = do_PUT = do_PATCH = do_DELETE = do_CONNECT = do_HEAD = do_OPTIONS = denied
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.deadline = time.monotonic() + self.max_seconds
        self.url = f'http://127.0.0.1:{self.server.server_port}/api/v3'
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.05), daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_path.write_text(json.dumps(self.receipt, indent=2, sort_keys=True) + '\n')
