"""Applicable publisher declarations owned by the accepted shared standard."""
from __future__ import annotations

import json
import re
import runpy

from scripts.inventory.repositories import ROOT, FAMILY_REPOSITORIES

WORKFLOWS = {"deploy-docs", "release-github", "release-ghcr", "release-crates", "release-pypi"}


def workflow_policy():
    return runpy.run_path(str(ROOT / ".github/scripts/check_workflow_projection.py"))["POLICY"]


def publisher_declarations(inventory: dict) -> dict:
    manifest = json.loads((ROOT / ".github/standards/repo-config.manifest.json").read_text())
    entries = manifest.get("repositories", [])
    if len(entries) != len(FAMILY_REPOSITORIES) or {entry["name"] for entry in entries} != set(FAMILY_REPOSITORIES):
        raise ValueError("publication standard must declare exactly the governed family")
    declarations = {}
    for entry in entries:
        allowed = WORKFLOWS & set(entry.get("workflow_allowlist", []))
        declared = entry.get("workflow_execution_policy", {}).get("publication_entrypoints", {})
        if set(declared) != allowed or any(value != ({"mode": "manual-only", "controller": "iac", "refs": "main-only"}
                                                    if name == "deploy-docs" else {"mode": "manual-only", "controller": "iac"})
                                           for name, value in declared.items()):
            raise ValueError(f"{entry['name']}: applicable publishers must require manual IaC control")
        declarations[entry["name"]] = declared
    if {entry["name"] for entry in inventory["repositories"]} != set(declarations):
        raise ValueError("publication inventory and accepted standard disagree")
    return declarations


def validate_request(inventory: dict, repository: str, workflow: str, commit: str, tag: str, *, require_published: bool = True) -> None:
    declarations = publisher_declarations(inventory)
    if repository not in declarations or workflow not in declarations[repository] or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("publication requires an applicable family publisher and immutable commit")
    selected = next(entry for entry in inventory["repositories"] if entry["name"] == repository)
    surface = "documentation" if workflow == "deploy-docs" else "packages"
    if require_published and selected["delivery"][surface] != "published":
        raise ValueError("publication capability is not active for this repository")
    if workflow == "deploy-docs":
        if tag:
            raise ValueError("documentation publication does not accept a release tag")
    elif not re.fullmatch(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", tag):
        raise ValueError("release publication requires an explicit version tag")


def validate_publisher(policy, workflow: str, document: dict) -> None:
    events = document.get("on")
    if not isinstance(events, dict) or set(events) != {"workflow_dispatch"}:
        raise ValueError("publisher must expose only manual dispatch")
    dispatch = events["workflow_dispatch"]
    inputs = dispatch.get("inputs", {}) if isinstance(dispatch, dict) else {}
    if not isinstance(inputs, dict) or not isinstance(inputs.get("accepted_commit"), dict) or inputs["accepted_commit"].get("required") is not True:
        raise ValueError("publisher must require an immutable accepted commit")
    if workflow != "deploy-docs" and (not isinstance(inputs.get("release_tag"), dict) or inputs["release_tag"].get("required") is not True):
        raise ValueError("publisher must require its release tag")
    jobs = document.get("jobs")
    if not isinstance(jobs, dict) or not all(isinstance(job, dict) for job in jobs.values()):
        raise ValueError("publisher jobs must be objects")
    if jobs.get("publication_admission") != policy.publication.controller_admission_job(workflow):
        raise ValueError("publisher admission differs from the accepted standard")
    for name, job in jobs.items():
        if name == "publication_admission":
            continue
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        condition = job.get("if", "")
        if (not isinstance(needs, list) or "publication_admission" not in needs
                or not isinstance(condition, str)
                or not condition.startswith("${{ needs.publication_admission.result == 'success' && (")
                or not condition.endswith(") }}")):
            raise ValueError("publisher jobs must depend on successful credential-free admission")
