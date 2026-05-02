#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "inventory/repositories.json"
TFVARS_PATH = ROOT / "infra/github/main-branch-protection/terraform.auto.tfvars.json"


def render_payload() -> dict:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    repositories = inventory.get("repositories", [])

    legacy_protected: list[str] = []
    legacy_review_counts: set[int] = set()
    legacy_enforce_admins_repositories: list[str] = []
    ruleset_repositories: list[str] = []
    ruleset_review_counts: set[int] = set()
    ruleset_required_status_checks: dict[str, list[str]] = {}

    for repo in repositories:
        branch = repo["governance"]["branch_protection"]
        if not branch["enabled"]:
            continue
        if branch["engine"] == "branch_protection":
            legacy_protected.append(repo["name"])
            legacy_review_counts.add(branch["required_approving_review_count"])
            if branch["enforce_admins"]:
                legacy_enforce_admins_repositories.append(repo["name"])
            continue

        ruleset_repositories.append(repo["name"])
        ruleset_review_counts.add(branch["required_approving_review_count"])
        ruleset_required_status_checks[repo["name"]] = branch["required_status_checks"]

    if len(legacy_review_counts) > 1:
        raise SystemExit(
            "legacy branch protection review count must be uniform for current Terraform shape: "
            f"{sorted(legacy_review_counts)}"
        )
    if len(ruleset_review_counts) > 1:
        raise SystemExit(
            "ruleset review count must be uniform for current Terraform shape: "
            f"{sorted(ruleset_review_counts)}"
        )
    return {
        "legacy_branch_protection_repositories": sorted(legacy_protected),
        "legacy_required_approving_review_count": (
            legacy_review_counts.pop() if legacy_review_counts else 1
        ),
        "legacy_enforce_admins_repositories": sorted(legacy_enforce_admins_repositories),
        "ruleset_repositories": sorted(ruleset_repositories),
        "ruleset_required_approving_review_count": (
            ruleset_review_counts.pop() if ruleset_review_counts else 0
        ),
        "ruleset_required_status_checks": {
            repo: ruleset_required_status_checks[repo]
            for repo in sorted(ruleset_required_status_checks)
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="write the tfvars file")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed tfvars file does not match the rendered payload",
    )
    args = parser.parse_args()

    payload = render_payload()
    rendered = json.dumps(payload, indent=2, sort_keys=False) + "\n"

    if args.write:
        TFVARS_PATH.write_text(rendered, encoding="utf-8")
        print(f"wrote {TFVARS_PATH}")
        return

    if args.check:
        current = TFVARS_PATH.read_text(encoding="utf-8")
        if current != rendered:
            raise SystemExit(
                f"generated tfvars drift: run python3 {Path(__file__).name} --write"
            )
        print("tfvars: OK")
        return

    print(rendered, end="")


if __name__ == "__main__":
    main()
