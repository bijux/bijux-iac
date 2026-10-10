#!/usr/bin/env python3
from __future__ import annotations

import argparse

from scripts.inventory.repositories import (
    BASELINE_REQUIRED_STATUS_CHECKS,
    FAMILY_REPOSITORIES,
    load_inventory,
    canonical_inventory,
    INVENTORY_PATH,
    merged_repository_settings,
)


ALLOWED_CLASSES = {"foundation", "hubs", "python", "rust"}
ALLOWED_DELIVERY_STATES = {"not-applicable", "planned", "published"}
ALLOWED_VISIBILITIES = {"public"}
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


COMMON_SETTINGS = {
    "visibility": "public", "has_issues": True,
    "allow_merge_commit": True, "allow_squash_merge": False,
    "allow_rebase_merge": False, "delete_branch_on_merge": True,
    "allow_auto_merge": False, "web_commit_signoff_required": False,
}


def require_keys(owner: str, value: object, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        fail(f"{owner}: keys must be {sorted(keys)}")


def validate_common_settings(owner: str, settings: dict) -> None:
    for key, value in COMMON_SETTINGS.items():
        if settings[key] != value:
            fail(f"{owner}: shared setting {key} must be {value!r}")


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
        if not isinstance(state, str) or state not in ALLOWED_DELIVERY_STATES:
            fail(
                f"{name}: delivery.{surface} must be one of "
                f"{sorted(ALLOWED_DELIVERY_STATES)}"
            )


def validate_inventory(inventory: object) -> None:
    if not isinstance(inventory, dict):
        fail("inventory must be an object")
    require_keys("inventory", inventory, {"version", "classes", "repository_settings_defaults", "repositories"})
    if type(inventory.get("version")) is not int or inventory["version"] != 3:
        fail("inventory version must be 3")

    classes = inventory.get("classes")
    if not isinstance(classes, dict):
        fail("inventory classes must be a mapping")

    unknown_defined = set(classes) - ALLOWED_CLASSES
    missing_defined = ALLOWED_CLASSES - set(classes)
    if unknown_defined:
        fail(f"unknown classes defined: {sorted(unknown_defined)}")
    if missing_defined:
        fail(f"missing class definitions: {sorted(missing_defined)}")

    for name, definition in classes.items():
        require_keys(f"class {name}", definition, {"description"})
        if not isinstance(definition["description"], str) or not definition["description"].strip():
            fail(f"class {name}: description must be a nonempty string")

    repository_settings_defaults = inventory.get("repository_settings_defaults")
    validate_repository_settings(
        "inventory",
        repository_settings_defaults,
        require_all_keys=True,
    )
    validate_common_settings("inventory", repository_settings_defaults)

    repositories = inventory.get("repositories")
    if not isinstance(repositories, list) or not repositories:
        fail("inventory repositories must be a non-empty list")

    seen_names: set[str] = set()
    for repo in repositories:
        if not isinstance(repo, dict):
            fail("each repository entry must be an object")
        require_keys("repository", repo, {"name", "class", "stack", "delivery", "settings", "governance"})
        name = repo.get("name")
        repo_class = repo.get("class")
        stack = repo.get("stack")
        settings = repo["settings"]
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
        for key, value in settings.items():
            if value == repository_settings_defaults[key]:
                fail(f"{name}: redundant settings override {key}")
        validate_common_settings(name, merged_repository_settings(inventory, repo))
        require_keys(f"{name}: governance", governance, {"branch_protection"})
        if not isinstance(governance, dict):
            fail(f"{name}: missing governance object")
        branch = governance.get("branch_protection")
        if not isinstance(branch, dict):
            fail(f"{name}: missing branch_protection object")
        if branch.get("enabled") is not True:
            fail(f"{name}: branch protection must be enabled")
        if branch.get("engine") != "ruleset":
            fail(
                f"{name}: branch_protection.engine must be one of "
                "['ruleset']"
            )
        if type(branch.get("required_approving_review_count")) is not int:
            fail(f"{name}: branch_protection.required_approving_review_count must be int")
        allowed_branch_keys = {
            "enabled", "engine", "required_approving_review_count",
            "required_status_checks",
        }
        if set(branch) != allowed_branch_keys:
            fail(f"{name}: branch protection keys must be {sorted(allowed_branch_keys)}")
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

    from scripts.inventory.publication import publisher_declarations
    try:
        publisher_declarations(inventory)
    except ValueError as error:
        fail(str(error))

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and format the governed family inventory")
    parser.add_argument("--write", action="store_true", help="write canonical inventory formatting")
    args = parser.parse_args()
    inventory = load_inventory()
    validate_inventory(inventory)
    formatted = canonical_inventory(inventory)
    if args.write:
        INVENTORY_PATH.write_text(formatted, encoding="utf-8")
    elif INVENTORY_PATH.read_text(encoding="utf-8") != formatted:
        fail("inventory formatting drift: run the inventory validator with --write")
    print(f"inventory: OK ({len(inventory['repositories'])} repositories)")


if __name__ == "__main__":
    main()
