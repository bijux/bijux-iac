"""Declare review-only dependency proposals and accepted-PR verification ownership."""
from __future__ import annotations

import json

from scripts.inventory.repositories import ROOT, FAMILY_REPOSITORIES

WORKFLOW_DEFAULTS = {
    "dependency_pull_requests": "notification-only",
    "main_verification": "accepted-pull-request",
    "dependency_merge": "owner-consolidation",
}


def merged_workflow_execution(inventory: dict, repository: dict) -> dict:
    return {**inventory["workflow_execution_defaults"],
            **repository["governance"]["workflow_execution"]}


def validate_workflow_execution(inventory: dict, *, require_standard: bool = True) -> None:
    if inventory.get("workflow_execution_defaults") != WORKFLOW_DEFAULTS:
        raise ValueError("workflow defaults must require review-only proposals and accepted-PR verification")
    for repository in inventory["repositories"]:
        overrides = repository["governance"].get("workflow_execution")
        expected = {"main_verification": "existing-events"} if repository["name"] == "bijux-masterclass" else {}
        if overrides != expected:
            raise ValueError(f"{repository['name']}: workflow exception must preserve only Masterclass's existing human events")
    if not require_standard:
        return
    manifest = json.loads((ROOT / ".github/standards/repo-config.manifest.json").read_text())
    entries = manifest.get("repositories", [])
    if len(entries) != len(FAMILY_REPOSITORIES) or {entry["name"] for entry in entries} != set(FAMILY_REPOSITORIES):
        raise ValueError("workflow standard must declare exactly the governed family")
    policies = {entry["name"]: entry.get("workflow_execution_policy", {}) for entry in entries}
    for repository in inventory["repositories"]:
        expected = merged_workflow_execution(inventory, repository)
        policy = policies[repository["name"]]
        if any(policy.get(key) != value for key, value in expected.items()):
            raise ValueError(f"{repository['name']}: workflow inventory and accepted standard disagree")
