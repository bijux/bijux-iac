"""Read GitHub governance data without converting uncertainty into absence."""
from __future__ import annotations

import json
import subprocess


def gh_api_json(path: str) -> object:
    return json.loads(subprocess.check_output(["gh", "api", path], text=True))


def list_rulesets(repository: str) -> list[dict]:
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
