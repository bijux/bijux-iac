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

    protected: list[str] = []
    review_counts: set[int] = set()
    enforce_admins_values: set[bool] = set()

    for repo in repositories:
        branch = repo["governance"]["branch_protection"]
        if not branch["enabled"]:
            continue
        protected.append(repo["name"])
        review_counts.add(branch["required_approving_review_count"])
        enforce_admins_values.add(branch["enforce_admins"])

    if len(review_counts) != 1:
        raise SystemExit(
            f"branch protection review count must be uniform for current Terraform shape: {sorted(review_counts)}"
        )
    if len(enforce_admins_values) != 1:
        raise SystemExit(
            "branch protection enforce_admins must be uniform for current Terraform shape"
        )

    return {
        "protected_repositories": sorted(protected),
        "required_approving_review_count": review_counts.pop(),
        "enforce_admins": enforce_admins_values.pop(),
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
