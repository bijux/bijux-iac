#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess

from repository_inventory import validated_inventory, merged_repository_settings

RULESET_NAME = "main-branch-protection"
STATUS_APP_ID = 15368


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


def compare_settings(repository: str, expected: dict, live: dict) -> list[str]:
    return [f"{repository}: repository setting {key} expected {value!r} but found {live.get(key)!r}"
            for key, value in expected.items()
            if type(live.get(key)) is not type(value) or live.get(key) != value]


def ruleset_mismatches(repository: str, expected_checks: list[str], ruleset: dict) -> list[str]:
    mismatches = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            mismatches.append(f"{repository}: {RULESET_NAME} {message}")

    require(ruleset.get("name") == RULESET_NAME, "has an unexpected name")
    require(ruleset.get("target") == "branch", "must target branches")
    require(ruleset.get("enforcement") == "active", "must be active")
    # GitHub omits bypass actors for readers without ruleset write access. Unknown
    # bypass configuration cannot prove the no-bypass invariant.
    require(ruleset.get("bypass_actors") == [], "must expose an empty bypass_actors array")
    conditions = ruleset.get("conditions")
    conditions = conditions if isinstance(conditions, dict) else {}
    ref = conditions.get("ref_name")
    ref = ref if isinstance(ref, dict) else {}
    require(set(conditions) == {"ref_name"}, "must have only ref_name conditions")
    require(ref.get("include") == ["~DEFAULT_BRANCH"], f"include must be ['~DEFAULT_BRANCH'], found {ref.get('include')!r}")
    require(ref.get("exclude") == [], "must have no excluded refs")
    raw_rules = ruleset.get("rules")
    if not isinstance(raw_rules, list) or not all(isinstance(rule, dict) and isinstance(rule.get("type"), str) for rule in raw_rules):
        require(False, "rules must be an array of typed objects")
        raw_rules = []
    require(len({r['type'] for r in raw_rules}) == len(raw_rules), "has duplicate rule types")
    rules = {rule["type"]: rule.get("parameters", {}) for rule in raw_rules}
    for rule in ("deletion", "non_fast_forward"):
        require(rule in rules, f"is missing {rule} protection")
    pr = rules.get("pull_request")
    pr = pr if isinstance(pr, dict) else {}
    for key, value in {
        "allowed_merge_methods": ["merge"], "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": True, "required_review_thread_resolution": True,
        "require_code_owner_review": False, "require_last_push_approval": False,
    }.items():
        require(type(pr.get(key)) is type(value) and pr.get(key) == value, f"pull_request.{key} must be {value!r}")
    status = rules.get("required_status_checks")
    status = status if isinstance(status, dict) else {}
    require(status.get("strict_required_status_checks_policy") is True, "must use strict required checks")
    require(status.get("do_not_enforce_on_create") is False, "must enforce checks on creation")
    checks = status.get("required_status_checks")
    if not isinstance(checks, list) or not all(isinstance(check, dict) and isinstance(check.get("context"), str) for check in checks):
        require(False, "required status checks must be an array of context objects")
        checks = []
    contexts = sorted(check["context"] for check in checks)
    require(contexts == sorted(expected_checks), f"required contexts expected {sorted(expected_checks)!r} but found {contexts!r}")
    for check in checks:
        require(type(check.get("integration_id")) is int and check["integration_id"] == STATUS_APP_ID,
                f"check {check['context']!r} must be bound to GitHub Actions app {STATUS_APP_ID}")
    return mismatches


def compare_ruleset(repository: str, expected_checks: list[str], live_rulesets: list[dict]) -> list[str]:
    matching = [rule for rule in live_rulesets if rule.get("name") == RULESET_NAME]
    if len(matching) != 1:
        return [f"{repository}: expected one {RULESET_NAME} ruleset, found {len(matching)}"]
    identifier = matching[0].get("id")
    if type(identifier) is not int:
        return [f"{repository}: malformed ruleset id"]
    detail = gh_api_json(f"repos/bijux/{repository}/rulesets/{identifier}")
    if not isinstance(detail, dict):
        return [f"{repository}: malformed ruleset detail"]
    return ruleset_mismatches(repository, expected_checks, detail)


def audit(inventory: dict) -> list[str]:
    mismatches = []
    for repository in inventory["repositories"]:
        name = repository["name"]
        try:
            live = gh_api_json(f"repos/bijux/{name}")
            if not isinstance(live, dict):
                raise ValueError("malformed repository response")
            if live.get("default_branch") != "main":
                mismatches.append(f"{name}: default branch must be main")
            mismatches.extend(compare_settings(name, merged_repository_settings(inventory, repository), live))
        except (ValueError, subprocess.CalledProcessError) as error:
            mismatches.append(f"{name}: repository audit unavailable: {error}")
        try:
            mismatches.extend(compare_ruleset(name, repository["governance"]["branch_protection"]["required_status_checks"], list_rulesets(name)))
        except (ValueError, subprocess.CalledProcessError) as error:
            mismatches.append(f"{name}: ruleset audit unavailable: {error}")
    return mismatches


def main() -> None:
    inventory = validated_inventory()
    mismatches = audit(inventory)
    if mismatches:
        raise SystemExit("\n".join(mismatches))
    print(f"live governance: OK ({len(inventory['repositories'])} repositories)")


if __name__ == "__main__":
    main()
