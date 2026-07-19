#!/usr/bin/env python3
from __future__ import annotations

from repository_inventory import (
    BASELINE_REQUIRED_STATUS_CHECKS,
    FAMILY_REPOSITORIES,
    load_inventory,
)


ALLOWED_CLASSES = {"foundation", "web-course", "python", "rust"}
ALLOWED_DELIVERY_STATES = {"not-applicable", "planned", "published"}
ALLOWED_ENGINES = {"branch_protection", "ruleset"}
ALLOWED_VISIBILITIES = {"public", "private"}
REPOSITORY_SETTING_TYPES = {
    "visibility": str,
    "has_issues": bool,
    "has_wiki": bool,
    "allow_merge_commit": bool,
    "allow_squash_merge": bool,
    "allow_rebase_merge": bool,
    "delete_branch_on_merge": bool,
    "allow_auto_merge": bool,
    "web_commit_signoff_required": bool,
}


def fail(message: str) -> None:
    raise SystemExit(message)


def validate_repository_settings(
    owner: str,
    settings: object,
    *,
    require_all_keys: bool,
) -> None:
    if not isinstance(settings, dict):
        fail(f"{owner}: repository settings must be an object")
    unknown_keys = set(settings) - set(REPOSITORY_SETTING_TYPES)
    if unknown_keys:
        fail(f"{owner}: unknown repository settings keys: {sorted(unknown_keys)}")
    if require_all_keys:
        missing_keys = set(REPOSITORY_SETTING_TYPES) - set(settings)
        if missing_keys:
            fail(f"{owner}: repository settings defaults missing keys: {sorted(missing_keys)}")
    for key, expected_type in REPOSITORY_SETTING_TYPES.items():
        if key not in settings:
            continue
        value = settings[key]
        if not isinstance(value, expected_type):
            fail(f"{owner}: repository settings {key} must be {expected_type.__name__}")
        if key == "visibility" and value not in ALLOWED_VISIBILITIES:
            fail(
                f"{owner}: repository settings visibility must be one of "
                f"{sorted(ALLOWED_VISIBILITIES)}"
            )


def validate_delivery(name: str, delivery: object) -> None:
    if not isinstance(delivery, dict):
        fail(f"{name}: delivery must be an object")
    if set(delivery) != {"documentation", "packages"}:
        fail(f"{name}: delivery must define documentation and packages")
    for surface, state in delivery.items():
        if state not in ALLOWED_DELIVERY_STATES:
            fail(
                f"{name}: delivery.{surface} must be one of "
                f"{sorted(ALLOWED_DELIVERY_STATES)}"
            )


def main() -> None:
    inventory = load_inventory()
    if inventory.get("version") != 2:
        fail("inventory version must be 2")

    classes = inventory.get("classes")
    if not isinstance(classes, dict):
        fail("inventory classes must be a mapping")

    unknown_defined = set(classes) - ALLOWED_CLASSES
    missing_defined = ALLOWED_CLASSES - set(classes)
    if unknown_defined:
        fail(f"unknown classes defined: {sorted(unknown_defined)}")
    if missing_defined:
        fail(f"missing class definitions: {sorted(missing_defined)}")

    repository_settings_defaults = inventory.get("repository_settings_defaults")
    validate_repository_settings(
        "inventory",
        repository_settings_defaults,
        require_all_keys=True,
    )
    if repository_settings_defaults["delete_branch_on_merge"] is not True:
        fail("inventory: merged branches must be deleted automatically")

    repositories = inventory.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        fail("inventory repositories must be a non-empty list")

    seen_names: set[str] = set()
    for repo in repositories:
        if not isinstance(repo, dict):
            fail("each repository entry must be an object")
        name = repo.get("name")
        repo_class = repo.get("class")
        stack = repo.get("stack")
        settings = repo.get("settings", {})
        governance = repo.get("governance")
        if not isinstance(name, str):
            fail(f"invalid repository name: {name!r}")
        if name in seen_names:
            fail(f"duplicate repository name: {name}")
        seen_names.add(name)
        if name not in FAMILY_REPOSITORIES:
            fail(f"{name}: repository is outside the governed Bijux family")

        expected_class, expected_stack, expected_docs, expected_packages = (
            FAMILY_REPOSITORIES[name]
        )
        if repo_class != expected_class:
            fail(f"{name}: class must be {expected_class!r}")
        if stack != expected_stack:
            fail(f"{name}: stack must be {expected_stack!r}")

        delivery = repo.get("delivery")
        validate_delivery(name, delivery)
        if delivery["documentation"] != expected_docs:
            fail(f"{name}: documentation delivery must be {expected_docs!r}")
        if delivery["packages"] != expected_packages:
            fail(f"{name}: package delivery must be {expected_packages!r}")

        validate_repository_settings(name, settings, require_all_keys=False)
        if not isinstance(governance, dict):
            fail(f"{name}: missing governance object")
        branch = governance.get("branch_protection")
        if not isinstance(branch, dict):
            fail(f"{name}: missing branch_protection object")
        if not isinstance(branch.get("enabled"), bool):
            fail(f"{name}: branch_protection.enabled must be bool")
        if branch.get("engine") not in ALLOWED_ENGINES:
            fail(
                f"{name}: branch_protection.engine must be one of "
                f"{sorted(ALLOWED_ENGINES)}"
            )
        if not isinstance(branch.get("required_approving_review_count"), int):
            fail(f"{name}: branch_protection.required_approving_review_count must be int")
        if not isinstance(branch.get("enforce_admins"), bool):
            fail(f"{name}: branch_protection.enforce_admins must be bool")
        required_status_checks = branch.get("required_status_checks")
        if not isinstance(required_status_checks, list):
            fail(f"{name}: branch_protection.required_status_checks must be list")
        if not all(isinstance(item, str) and item for item in required_status_checks):
            fail(
                f"{name}: branch_protection.required_status_checks entries "
                "must be non-empty strings"
            )
        if len(required_status_checks) != len(set(required_status_checks)):
            fail(f"{name}: required status checks must be unique")
        if branch["engine"] == "ruleset" and branch["enabled"]:
            if branch["required_approving_review_count"] != 0:
                fail(
                    f"{name}: ruleset-managed repositories must use "
                    "required_approving_review_count=0"
                )
            missing_checks = BASELINE_REQUIRED_STATUS_CHECKS - set(required_status_checks)
            if missing_checks:
                fail(f"{name}: missing baseline status checks: {sorted(missing_checks)}")

    missing_repositories = set(FAMILY_REPOSITORIES) - seen_names
    if missing_repositories:
        fail(f"missing governed repositories: {sorted(missing_repositories)}")

    print(f"inventory: OK ({len(repositories)} repositories)")


if __name__ == "__main__":
    main()
