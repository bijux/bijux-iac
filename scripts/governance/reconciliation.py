"""Compare role-specific provider observations; hidden data never becomes proof."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.inventory.authority_governance import load_governance, validate_governance
from scripts.inventory.repositories import ROOT, unique_keys

MISSING = object()


def reconcile(name: str, observed: dict, *, policy: dict | None = None) -> dict:
    policy = load_governance() if policy is None else policy
    validate_governance(policy, require_standard=False)
    profile = next((row for row in policy["repositories"] if row["name"] == name), None)
    if profile is None or not isinstance(observed, dict):
        raise ValueError(
            "Only a declared GitLab authority can have mirror observations"
        )
    differences, unavailable = [], []

    def value(path):
        current = observed
        for key in path.split("."):
            if not isinstance(current, dict) or key not in current:
                return MISSING
            current = current[key]
        return current

    def check(path, expected, actual=MISSING):
        actual = value(path) if actual is MISSING else actual
        if actual is MISSING:
            unavailable.append(path)
        elif json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
            differences.append({"field": path, "expected": expected, "actual": actual})

    def levels(path, key, *, deploy=None):
        rows = value(path)
        if rows is MISSING:
            return MISSING
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return {"invalid_access_levels": True}
        if deploy is not None:
            if any("deploy_key_id" not in row for row in rows):
                return MISSING
            rows = [row for row in rows if bool(row["deploy_key_id"]) is deploy]
        if any(key not in row for row in rows):
            return MISSING
        return [row[key] for row in rows]

    github, canonical, personal = (
        profile[key] for key in ("github_mirror", "canonical", "personal_mirror")
    )
    for prefix, identity in [
        ("github.repository", github),
        ("canonical.project", canonical),
        ("personal.project", personal),
    ]:
        check(prefix + ".id", identity["id"])
        check(
            prefix
            + (".full_name" if prefix.startswith("github") else ".path_with_namespace"),
            identity["path"],
        )
        check(prefix + ".default_branch", "main")
    check("github.actions.enabled", False)
    check("canonical.project.builds_access_level", "enabled")
    check("personal.project.builds_access_level", "disabled")
    for key in (
        "jobs_enabled",
        "shared_runners_enabled",
        "group_runners_enabled",
        "auto_devops_enabled",
    ):
        check("personal.project." + key, False)
    selector = {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
    for owner, identifier, bypass in [
        ("history_guard", github["history_ruleset_id"], []),
        ("admission", github["admission_ruleset_id"], github["admission_bypass"]),
    ]:
        prefix = "github." + owner
        for key, expected in {
            "id": identifier,
            "target": "branch",
            "enforcement": "active",
            "conditions": selector,
            "bypass_actors": bypass,
        }.items():
            check(prefix + "." + key, expected)
        rules = value(prefix + ".rules")
        if rules is MISSING:
            unavailable.append(prefix + ".rules")
            continue
        if not isinstance(rules, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("type"), str)
            for row in rules
        ):
            differences.append(
                {
                    "field": prefix + ".rules",
                    "expected": "typed rule list",
                    "actual": rules,
                }
            )
            continue
        kinds = sorted(row["type"] for row in rules)
        expected_kinds = (
            ["deletion", "non_fast_forward"]
            if owner == "history_guard"
            else ["pull_request", "required_status_checks", "update"]
        )
        check(prefix + ".rule_types", expected_kinds, kinds)
        if owner == "history_guard":
            continue
        by_kind = {row["type"]: row.get("parameters", {}) for row in rules}
        update = by_kind.get("update", {})
        if not isinstance(update, dict):
            differences.append(
                {"field": prefix + ".update", "expected": {}, "actual": update}
            )
        else:
            check(
                prefix + ".update.allows_fetch_and_merge",
                github["allows_fetch_and_merge"],
                update.get("update_allows_fetch_and_merge", False),
            )
        status = by_kind.get("required_status_checks", {})
        pr = by_kind.get("pull_request", {})
        if not isinstance(status, dict) or not isinstance(pr, dict):
            differences.append(
                {
                    "field": prefix + ".parameters",
                    "expected": "typed parameter objects",
                    "actual": None,
                }
            )
            continue
        for key, expected in {
            "required_status_checks": [github["required_check"]],
            "strict_required_status_checks_policy": True,
            "do_not_enforce_on_create": False,
        }.items():
            actual = status.get(key, MISSING)
            if actual is MISSING:
                unavailable.append(prefix + ".status." + key)
            else:
                check(prefix + ".status." + key, expected, actual)
        for key, expected in github["pull_request_parameters"].items():
            if key not in pr:
                unavailable.append(prefix + ".pull_request." + key)
            else:
                check(prefix + ".pull_request." + key, expected, pr[key])
    for prefix in ("canonical.main", "personal.main"):
        check(prefix + ".allow_force_push", False)
        check(prefix + ".unprotect_access_levels", [])
    for path, expected in [
        ("canonical.main.push_access_levels", [0]),
        ("canonical.main.merge_access_levels", [40]),
        ("personal.main.merge_access_levels", [0]),
        ("canonical.environment.deploy_access_levels", [40]),
    ]:
        actual = levels(path, "access_level")
        if actual is MISSING:
            unavailable.append(path)
        else:
            check(path, expected, actual)
    for path, key, deploy, expected in [
        (
            "personal.main.push_access_levels",
            "deploy_key_id",
            True,
            [personal["deploy_key_id"]],
        ),
        ("personal.main.push_access_levels", "access_level", False, []),
    ]:
        actual = levels(path, key, deploy=deploy)
        if actual is MISSING:
            unavailable.append(path)
        else:
            check(
                path + (".deploy_keys" if deploy else ".ordinary_roles"),
                expected,
                actual,
            )
    check("canonical.environment.name", "publication")
    for path in (
        "canonical.environment.deploy_access_levels",
        "canonical.main.push_access_levels",
        "canonical.main.merge_access_levels",
        "personal.main.push_access_levels",
        "personal.main.merge_access_levels",
    ):
        for key in ("user_id", "group_id"):
            actual = levels(path, key)
            if actual is MISSING:
                unavailable.append(path)
            else:
                check(path + "." + key, [], [x for x in actual if x is not None])
    return {
        "repository": name,
        "status": (
            "drift" if differences else "unavailable" if unavailable else "matched"
        ),
        "differences": differences,
        "unavailable": sorted(set(unavailable)),
        "declaration": "desired",
        "remote_writes": False,
        "application_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repository", required=True, choices=["bijux-std", "bijux-iac"]
    )
    parser.add_argument("--snapshot", required=True, type=Path)
    args = parser.parse_args()
    policy = load_governance()
    validate_governance(policy)
    snapshot = json.loads(args.snapshot.read_text(), object_pairs_hook=unique_keys)
    result = reconcile(args.repository, snapshot, policy=policy)
    output = ROOT / "artifacts/authority-governance"
    output.mkdir(parents=True, exist_ok=True)
    (output / (args.repository + "-reconciliation.json")).write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result, indent=2))
    if result["status"] != "matched":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
