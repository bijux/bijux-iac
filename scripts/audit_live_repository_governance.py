#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "inventory/repositories.json"
RULESET_NAME = "main-branch-protection"


def gh_api_json(path: str) -> object:
    output = subprocess.check_output(
        ["gh", "api", path],
        text=True,
    )
    return json.loads(output)


def merged_settings(inventory: dict[str, object], repository: dict[str, object]) -> dict[str, object]:
    defaults = inventory["repository_settings_defaults"]
    overrides = repository.get("settings", {})
    return {**defaults, **overrides}


def compare_settings(
    repository: str,
    expected: dict[str, object],
    live: dict[str, object],
) -> list[str]:
    mismatches: list[str] = []
    for key, expected_value in expected.items():
        live_value = live.get(key)
        if live_value != expected_value:
            mismatches.append(
                f"{repository}: repository setting {key} expected {expected_value!r} but found {live_value!r}"
            )
    return mismatches


def compare_ruleset(
    repository: str,
    expected_checks: list[str],
    live_rulesets: list[dict[str, object]],
) -> list[str]:
    for ruleset_summary in live_rulesets:
        if ruleset_summary.get("name") != RULESET_NAME:
            continue
        if ruleset_summary.get("target") != "branch":
            continue
        ruleset_id = ruleset_summary.get("id")
        if not isinstance(ruleset_id, int):
            return [f"{repository}: live ruleset summary for {RULESET_NAME} is missing an id"]
        ruleset = gh_api_json(f"repos/bijux/{repository}/rulesets/{ruleset_id}")
        if ruleset.get("enforcement") != "active":
            return [f"{repository}: {RULESET_NAME} exists but is not active"]
        conditions = ruleset.get("conditions", {})
        ref_name = conditions.get("ref_name", {}) if isinstance(conditions, dict) else {}
        include = ref_name.get("include", [])
        if include != ["~DEFAULT_BRANCH"]:
            return [
                f"{repository}: {RULESET_NAME} must target only ~DEFAULT_BRANCH, found {include!r}"
            ]

        rules = {
            rule.get("type"): rule.get("parameters", {})
            for rule in ruleset.get("rules", [])
            if isinstance(rule, dict)
        }
        if "deletion" not in rules:
            return [f"{repository}: {RULESET_NAME} is missing deletion protection"]
        if "non_fast_forward" not in rules:
            return [f"{repository}: {RULESET_NAME} is missing non-fast-forward protection"]

        pull_request = rules.get("pull_request")
        if not isinstance(pull_request, dict):
            return [f"{repository}: {RULESET_NAME} is missing pull_request parameters"]
        if pull_request.get("allowed_merge_methods") != ["merge"]:
            return [
                f"{repository}: {RULESET_NAME} allowed_merge_methods must be ['merge'], found {pull_request.get('allowed_merge_methods')!r}"
            ]
        if pull_request.get("required_approving_review_count") != 0:
            return [
                f"{repository}: {RULESET_NAME} required_approving_review_count must be 0"
            ]
        if pull_request.get("dismiss_stale_reviews_on_push") is not True:
            return [f"{repository}: {RULESET_NAME} must dismiss stale reviews on push"]
        if pull_request.get("required_review_thread_resolution") is not True:
            return [f"{repository}: {RULESET_NAME} must require review thread resolution"]

        required_status_checks = rules.get("required_status_checks")
        if not isinstance(required_status_checks, dict):
            return [f"{repository}: {RULESET_NAME} is missing required_status_checks parameters"]
        if required_status_checks.get("strict_required_status_checks_policy") is not True:
            return [f"{repository}: {RULESET_NAME} must use strict required status checks"]
        live_contexts = sorted(
            check["context"]
            for check in required_status_checks.get("required_status_checks", [])
            if isinstance(check, dict) and isinstance(check.get("context"), str)
        )
        if live_contexts != sorted(expected_checks):
            return [
                f"{repository}: {RULESET_NAME} required status checks expected {sorted(expected_checks)!r} but found {live_contexts!r}"
            ]
        return []
    return [f"{repository}: missing live repository ruleset {RULESET_NAME!r}"]


def main() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    repositories = inventory["repositories"]
    mismatches: list[str] = []

    for repository in repositories:
        name = repository["name"]
        expected_settings = merged_settings(inventory, repository)
        live_repository = gh_api_json(f"repos/bijux/{name}")
        live_settings = {
            key: live_repository.get(key)
            for key in expected_settings
        }
        mismatches.extend(compare_settings(name, expected_settings, live_settings))

        branch = repository["governance"]["branch_protection"]
        if branch["enabled"] and branch["engine"] == "ruleset":
            live_rulesets = gh_api_json(f"repos/bijux/{name}/rulesets")
            mismatches.extend(
                compare_ruleset(name, branch["required_status_checks"], live_rulesets)
            )

    if mismatches:
        raise SystemExit("\n".join(mismatches))

    print(f"live governance: OK ({len(repositories)} repositories)")


if __name__ == "__main__":
    main()
