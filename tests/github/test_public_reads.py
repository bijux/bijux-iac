"""Anonymous live planning must have a bounded, read-only API boundary."""
from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from scripts.inventory.repositories import ROOT


class Response(BytesIO):
    def __init__(self, payload=b'{}', status=200, headers=None):
        super().__init__(payload)
        self.status = status
        self.headers = headers or {}


class PublicReadsTests(unittest.TestCase):
    def gateway(self, root, **kwargs):
        from scripts.github.public_reads import ReadGateway
        return ReadGateway({'bijux-iac'}, root / 'reads.json', **kwargs)

    def test_repeated_provider_reads_share_one_anonymous_snapshot(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            calls = []
            def upstream(request, timeout):
                calls.append((request.full_url, dict(request.header_items()), timeout))
                return Response(b'{"id":17,"name":"main-branch-protection"}')
            with self.gateway(Path(directory), opener=upstream) as gateway:
                with urllib.request.urlopen(gateway.url + '/repos/bijux/bijux-iac/rulesets/17?includes_parents=false') as first:
                    self.assertEqual(json.load(first)['id'], 17)
                with urllib.request.urlopen(gateway.url + '/repos/bijux/bijux-iac/rulesets/17?includes_parents=false') as second:
                    self.assertEqual(json.load(second)['id'], 17)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], 'https://api.github.com/repos/bijux/bijux-iac/rulesets/17?includes_parents=false')
            self.assertFalse(any(k.lower() == 'authorization' for k in calls[0][1]))
            evidence = json.loads(Path(directory, 'reads.json').read_text())
            self.assertEqual(evidence['upstream_requests'], 1)
            self.assertEqual(evidence['cache_hits'], 1)
            self.assertEqual(evidence['remote_writes'], False)
            self.assertEqual(evidence['requests'][0]['status'], 200)
            self.assertEqual(len(evidence['requests'][0]['sha256']), 64)

    def test_gateway_denies_writes_credentials_unknown_routes_and_query_expansion(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            calls = []
            def upstream(request, timeout):
                calls.append(request)
                return Response()
            with self.gateway(Path(directory), opener=upstream) as gateway:
                for path, method, headers in [
                    ('/repos/bijux/bijux-iac', 'POST', {}),
                    ('/repos/bijux/bijux-iac', 'GET', {'Authorization': 'Bearer forbidden'}),
                    ('/repos/other/bijux-iac', 'GET', {}),
                    ('/repos/bijux/other', 'GET', {}),
                    ('/repos/bijux/bijux-iac/contents/private', 'GET', {}),
                    ('/repos/bijux/bijux-iac/rulesets?access_token=forbidden', 'GET', {}),
                    ('/repos/bijux/bijux-iac/rulesets?page=0', 'GET', {}),
                    ('/repos/bijux/bijux-iac/rulesets?per_page=101', 'GET', {}),
                    ('/repos/bijux/bijux-iac/rulesets/17?includes_parents=true', 'GET', {}),
                    ('/repos/bijux/bijux-iac/../other', 'GET', {}),
                ]:
                    with self.subTest(path=path, method=method), self.assertRaises(urllib.error.HTTPError):
                        urllib.request.urlopen(urllib.request.Request(gateway.url + path, method=method, headers=headers))
            self.assertEqual(calls, [])

    def test_upstream_failure_is_not_cached_as_absence_and_request_budget_is_hard(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            calls = []
            def upstream(request, timeout):
                calls.append(request)
                if len(calls) == 1:
                    raise urllib.error.HTTPError(request.full_url, 403, 'rate limit', {}, None)
                return Response(b'[]')
            with self.gateway(Path(directory), opener=upstream, request_limit=1) as gateway:
                for _ in range(2):
                    with self.assertRaises(urllib.error.HTTPError):
                        urllib.request.urlopen(gateway.url + '/repos/bijux/bijux-iac/rulesets')
            self.assertEqual(len(calls), 1)
            self.assertEqual(json.loads(Path(directory, 'reads.json').read_text())['failures'], 2)

    def test_invalid_json_and_oversize_body_cannot_become_plan_inputs(self):
        for payload in [b'not json', b'{"id":1,"id":2}', b' ' * (1024 * 1024 + 1)]:
            with self.subTest(size=len(payload)), tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
                with self.gateway(Path(directory), opener=lambda request, timeout: Response(payload)) as gateway:
                    with self.assertRaises(urllib.error.HTTPError):
                        urllib.request.urlopen(gateway.url + '/repos/bijux/bijux-iac')

    def test_only_org_lookup_can_return_not_found_and_transient_retries_are_bounded(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            def absent(request, timeout):
                raise urllib.error.HTTPError(request.full_url, 404, 'not found', {}, BytesIO(b'{"message":"Not Found"}'))
            with self.gateway(Path(directory), opener=absent) as gateway:
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(gateway.url + '/orgs/bijux')
                self.assertEqual(error.exception.code, 404)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(gateway.url + '/repos/bijux/bijux-iac')
                self.assertEqual(error.exception.code, 502)
            calls = []
            def unavailable(request, timeout):
                calls.append(request)
                raise urllib.error.HTTPError(request.full_url, 503, 'unavailable', {}, None)
            with self.gateway(Path(directory), opener=unavailable) as gateway, patch('scripts.github.public_reads.time.sleep'):
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(gateway.url + '/repos/bijux/bijux-iac')
            self.assertEqual(len(calls), 3)

    def test_existing_api_uses_explicit_loopback_transport_without_cli_fallback(self):
        from scripts.github.api import gh_api_json, list_rulesets
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            def upstream(request, timeout):
                data = ([{'id': 17, 'name': 'main-branch-protection', 'target': 'branch'}]
                        if '/rulesets?' in request.full_url else {'full_name': 'bijux/bijux-iac'})
                return Response(json.dumps(data).encode())
            with self.gateway(Path(directory), opener=upstream) as gateway, \
                    patch.dict('os.environ', {'BIJUX_GITHUB_READ_URL': gateway.url}), \
                    patch('scripts.github.api.subprocess.check_output', side_effect=AssertionError('CLI fallback forbidden')):
                self.assertEqual(gh_api_json('repos/bijux/bijux-iac')['full_name'], 'bijux/bijux-iac')
                self.assertEqual(list_rulesets('bijux-iac')[0]['id'], 17)

    def test_direct_ruleset_query_is_preserved_and_distinct_from_default_parent_read(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            calls = []
            def upstream(request, timeout):
                calls.append(request.full_url)
                return Response(json.dumps({'direct': request.full_url.endswith('?includes_parents=false')}).encode())
            with self.gateway(Path(directory), opener=upstream) as gateway:
                with urllib.request.urlopen(gateway.url + '/repos/bijux/bijux-iac/rulesets/17') as response:
                    self.assertFalse(json.load(response)['direct'])
                with urllib.request.urlopen(gateway.url + '/repos/bijux/bijux-iac/rulesets/17?includes_parents=false') as response:
                    self.assertTrue(json.load(response)['direct'])
            self.assertEqual(len(calls), 2)

    def test_concurrent_duplicate_gets_spend_one_upstream_request(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            calls = []
            def upstream(request, timeout):
                calls.append(request.full_url)
                time.sleep(0.02)
                return Response(b'{"id":17}')
            with self.gateway(Path(directory), opener=upstream) as gateway:
                def read(_):
                    status, body = gateway.fetch('/repos/bijux/bijux-iac/rulesets/17')
                    self.assertEqual(status, 200)
                    return json.loads(body)['id']
                with ThreadPoolExecutor(max_workers=8) as executor:
                    self.assertEqual(list(executor.map(read, range(8))), [17] * 8)
            self.assertEqual(len(calls), 1)
            self.assertEqual(gateway.receipt['cache_hits'], 7)

    def test_redirect_response_cannot_become_plan_input(self):
        from scripts.github.public_reads import NoRedirect
        request = urllib.request.Request('https://api.github.com/repos/bijux/bijux-iac')
        self.assertIsNone(NoRedirect().redirect_request(request, None, 302, 'moved', {}, 'https://other.test'))
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            with self.gateway(Path(directory), opener=lambda request, timeout: Response(b'{}', status=302)) as gateway:
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(gateway.url + '/repos/bijux/bijux-iac')
