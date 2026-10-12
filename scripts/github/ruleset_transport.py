"""Preserve complete API rules while changing only inventory-owned check bindings."""
from __future__ import annotations

import copy
import json
import subprocess

from scripts.github.api import gh_api_json
from scripts.github.audit import RULESET_NAME, STATUS_APP_ID, ruleset_mismatches

API_VERSION = "2022-11-28"


def api_plan(inventory: dict, snapshots: dict) -> list[dict]:
    """Refuse unrelated governance drift rather than repairing it in this transport."""
    names = {repository["name"] for repository in inventory["repositories"]}
    if not isinstance(snapshots, dict) or set(snapshots) != names:
        raise ValueError("API plan needs every complete ruleset before-image")
    operations = []
    for repository in inventory["repositories"]:
        name = repository["name"]
        before = snapshots[name]
        if (not isinstance(before, dict) or type(before.get("id")) is not int or before["id"] <= 0
                or before.get("source") != f"bijux/{name}" or before.get("source_type") != "Repository"
                or before.get("name") != RULESET_NAME or not isinstance(before.get("rules"), list)):
            raise ValueError(f"{name}: API transport requires an existing owned repository ruleset")
        rules = before["rules"]
        if not all(isinstance(rule, dict) and isinstance(rule.get("type"), str)
                   and set(rule).issubset({"type", "parameters"})
                   and isinstance(rule.get("parameters", {}), dict) for rule in rules):
            raise ValueError(f"{name}: unsupported API rule representation")
        status = [rule for rule in rules if rule["type"] == "required_status_checks"]
        if len(status) != 1:
            raise ValueError(f"{name}: API plan requires exactly one status-check rule")
        checks = status[0].get("parameters", {}).get("required_status_checks")
        if not isinstance(checks, list) or not all(isinstance(check, dict)
                and set(check) == {"context", "integration_id"}
                and isinstance(check["context"], str) and check["context"]
                and type(check["integration_id"]) is int and check["integration_id"] == STATUS_APP_ID
                for check in checks):
            raise ValueError(f"{name}: existing check bindings must be explicit Actions producers")
        existing = [check["context"] for check in checks]
        desired = repository["governance"]["branch_protection"]["required_status_checks"]
        if len(set(existing)) != len(existing) or not set(existing).issubset(desired):
            raise ValueError(f"{name}: API plan cannot remove or replace existing check bindings")
        after = copy.deepcopy(before)
        # The sole selector exception is the retained Python consumer's explicit
        # main selector. Its replacement still protects the same main branch.
        old_selector = {"ref_name": {"include": ["refs/heads/main"], "exclude": []}}
        if name == "bijux-pollenomics" and before.get("conditions") == old_selector:
            after["conditions"] = {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}
        baseline = copy.deepcopy(after)
        errors = ruleset_mismatches(name, existing, baseline)
        if errors:
            raise ValueError("API transport refuses unrelated baseline drift: " + "; ".join(errors))
        status_after = next(rule for rule in after["rules"] if rule["type"] == "required_status_checks")
        status_after["parameters"]["required_status_checks"].extend(
            {"context": context, "integration_id": STATUS_APP_ID} for context in desired if context not in existing)
        errors = ruleset_mismatches(name, desired, after)
        if errors:
            raise ValueError("API plan does not match the inventory: " + "; ".join(errors))
        # PUT accepts partial top-level updates. Unowned rules and parameters are
        # serialized unchanged, while omitted name/enforcement/bypass stay owned
        # by GitHub's existing object rather than a reduced provider schema.
        body = {"conditions": after["conditions"], "rules": after["rules"]}
        if json.loads(json.dumps(body, allow_nan=False)) != body:
            raise ValueError(f"{name}: API body is not a faithful JSON round trip")
        operations.append({"repository": name, "id": before["id"], "before": before,
                           "after": after, "body": body, "actions": ["no-op" if after == before else "update"]})
    return operations


def apply_api_operation(operation: dict) -> dict:
    """Reread immediately before a single write and verify every retained field."""
    endpoint = f"repos/bijux/{operation['repository']}/rulesets/{operation['id']}"
    if gh_api_json(endpoint) != operation["before"]:
        raise ValueError("live ruleset changed immediately before its API operation")
    if operation["actions"] == ["no-op"]:
        return operation["before"]
    subprocess.run(["gh", "api", "--method", "PUT", endpoint,
                    "-H", f"X-GitHub-Api-Version: {API_VERSION}", "--input", "-"],
                   input=json.dumps(operation["body"], allow_nan=False), text=True,
                   check=True, stdout=subprocess.DEVNULL)
    after = gh_api_json(endpoint)
    # Server-owned modification time changes on a successful PUT. Every other
    # response field, including unknown metadata, remains part of the comparison.
    if (not isinstance(after, dict) or set(after) != set(operation["after"])
            or {k: v for k, v in after.items() if k != "updated_at"}
            != {k: v for k, v in operation["after"].items() if k != "updated_at"}):
        raise ValueError("API ruleset readback changed retained fields or failed to apply the plan")
    return after
