#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "inventory/repositories.json"
ALLOWED_CLASSES = {"foundation", "web-course", "python", "rust"}
ALLOWED_ENGINES = {"branch_protection", "ruleset"}


def main() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    if inventory.get("version") != 1:
        raise SystemExit("inventory version must be 1")

    classes = inventory.get("classes")
    if not isinstance(classes, dict):
        raise SystemExit("inventory classes must be a mapping")

    unknown_defined = set(classes) - ALLOWED_CLASSES
    missing_defined = ALLOWED_CLASSES - set(classes)
    if unknown_defined:
        raise SystemExit(f"unknown classes defined: {sorted(unknown_defined)}")
    if missing_defined:
        raise SystemExit(f"missing class definitions: {sorted(missing_defined)}")

    repositories = inventory.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        raise SystemExit("inventory repositories must be a non-empty list")

    seen_names: set[str] = set()
    for repo in repositories:
        if not isinstance(repo, dict):
            raise SystemExit("each repository entry must be an object")
        name = repo.get("name")
        repo_class = repo.get("class")
        stack = repo.get("stack")
        governance = repo.get("governance")
        if not isinstance(name, str) or not name.startswith("bijux"):
            raise SystemExit(f"invalid repository name: {name!r}")
        if name in seen_names:
            raise SystemExit(f"duplicate repository name: {name}")
        seen_names.add(name)
        if repo_class not in ALLOWED_CLASSES:
            raise SystemExit(f"{name}: invalid class {repo_class!r}")
        if not isinstance(stack, str) or not stack:
            raise SystemExit(f"{name}: missing stack")
        if not isinstance(governance, dict):
            raise SystemExit(f"{name}: missing governance object")
        branch = governance.get("branch_protection")
        if not isinstance(branch, dict):
            raise SystemExit(f"{name}: missing branch_protection object")
        if not isinstance(branch.get("enabled"), bool):
            raise SystemExit(f"{name}: branch_protection.enabled must be bool")
        if branch.get("engine") not in ALLOWED_ENGINES:
            raise SystemExit(
                f"{name}: branch_protection.engine must be one of {sorted(ALLOWED_ENGINES)}"
            )
        if not isinstance(branch.get("required_approving_review_count"), int):
            raise SystemExit(
                f"{name}: branch_protection.required_approving_review_count must be int"
            )
        if not isinstance(branch.get("enforce_admins"), bool):
            raise SystemExit(f"{name}: branch_protection.enforce_admins must be bool")
        required_status_checks = branch.get("required_status_checks")
        if not isinstance(required_status_checks, list):
            raise SystemExit(f"{name}: branch_protection.required_status_checks must be list")
        if not all(isinstance(item, str) and item for item in required_status_checks):
            raise SystemExit(
                f"{name}: branch_protection.required_status_checks entries must be non-empty strings"
            )
        if branch["engine"] == "ruleset" and branch["enabled"]:
            if branch["required_approving_review_count"] != 0:
                raise SystemExit(
                    f"{name}: ruleset-managed repositories must use required_approving_review_count=0"
                )
            if not required_status_checks:
                raise SystemExit(
                    f"{name}: ruleset-managed repositories must declare required status checks"
                )

    print(f"inventory: OK ({len(repositories)} repositories)")


if __name__ == "__main__":
    main()
