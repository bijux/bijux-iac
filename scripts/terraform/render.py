#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from scripts.inventory.repositories import ROOT, validated_inventory


TFVARS_PATH = ROOT / "infra/github/repository-rulesets/terraform.auto.tfvars.json"


def render_payload() -> dict:
    inventory = validated_inventory()
    repositories = {repository["name"]: repository for repository in inventory["repositories"]}
    return {
        "ruleset_repositories": sorted(repositories),
        "ruleset_required_approving_review_count": 0,
        "ruleset_required_status_checks": {
            name: repositories[name]["governance"]["branch_protection"]["required_status_checks"]
            for name in sorted(repositories)
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
                "generated tfvars drift: run python3 -m scripts.terraform.render --write"
            )
        print("tfvars: OK")
        return

    print(rendered, end="")


if __name__ == "__main__":
    main()
