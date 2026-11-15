"""Read GitHub governance data without converting uncertainty into absence."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import subprocess


def public_api_json(path: str) -> object:
    base = os.environ['BIJUX_GITHUB_READ_URL']
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
            or parsed.username or parsed.password or parsed.path != '/api/v3' or parsed.query or parsed.fragment
            or path.startswith('/') or '://' in path):
        raise ValueError('anonymous reads require the explicit loopback gateway')
    with urllib.request.urlopen(base + '/' + path, timeout=25) as response:
        return json.load(response)


def gh_api_json(path: str) -> object:
    if os.environ.get('BIJUX_GITHUB_READ_URL'):
        return public_api_json(path)
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def list_rulesets(repository: str) -> list[dict]:
    if os.environ.get('BIJUX_GITHUB_READ_URL'):
        pages = []
        for page in range(1, 11):
            response = public_api_json(f'repos/bijux/{repository}/rulesets?per_page=100&page={page}')
            pages.append(response)
            if not isinstance(response, list) or len(response) < 100:
                break
        else:
            raise ValueError('ruleset discovery exceeded its page bound')
    else:
        pages = json.loads(subprocess.check_output(
            ["gh", "api", "--paginate", "--slurp", f"repos/bijux/{repository}/rulesets?per_page=100"],
            text=True,
        ))
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise ValueError("ruleset discovery must return array pages")
    rulesets = [item for page in pages for item in page]
    if not all(isinstance(item, dict) and type(item.get("id")) is int
               and isinstance(item.get("name"), str) and isinstance(item.get("target"), str) and item.get("target") in {"branch", "tag", "push"}
               for item in rulesets):
        raise ValueError("malformed ruleset discovery response")
    return rulesets
