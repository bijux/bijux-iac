"""Bind complete managed ruleset before-images without treating failed reads as absence."""
from __future__ import annotations

from scripts.github.api import gh_api_json, list_rulesets
from scripts.github.audit import RULESET_NAME


def ruleset_snapshot(inventory: dict) -> dict:
    snapshots = {}
    for repository in inventory["repositories"]:
        name = repository["name"]
        matches = [rule for rule in list_rulesets(name) if rule["target"] == "branch"
                   and rule["name"] in {RULESET_NAME, "main-pr-only-admin-bypass"}]
        if len(matches) > 1:
            raise ValueError(f"{name}: ambiguous managed ruleset before-image")
        if not matches:
            snapshots[name] = None
            continue
        identifier = matches[0]["id"]
        detail = gh_api_json(f"repos/bijux/{name}/rulesets/{identifier}")
        if (not isinstance(detail, dict) or type(identifier) is not int or identifier <= 0
                or detail.get("id") != identifier or detail.get("name") != matches[0]["name"]
                or detail.get("target") != "branch"
                or detail.get("source_type") != "Repository" or detail.get("source") != f"bijux/{name}"
                or not isinstance(detail.get("conditions"), dict)
                or not isinstance(detail.get("rules"), list)
                or not isinstance(detail.get("bypass_actors"), list)
                or not isinstance(detail.get("enforcement"), str)):
            raise ValueError(f"{name}: incomplete managed ruleset before-image")
        # Retain the complete response, including fields this policy does not
        # own. Any intervening difference invalidates the saved plan.
        snapshots[name] = detail
    return snapshots


def require_ruleset_snapshot(inventory: dict, expected: dict) -> None:
    names = {repository["name"] for repository in inventory["repositories"]}
    if not isinstance(expected, dict) or set(expected) != names:
        raise ValueError("saved preflight lacks complete managed ruleset before-images")
    if ruleset_snapshot(inventory) != expected:
        raise ValueError("live rulesets changed after planning; repeat preflight")
