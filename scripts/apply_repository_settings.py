#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess

from repository_inventory import validated_inventory, merged_repository_settings, validate_owner


def apply_settings(owner: str, name: str, settings: dict[str, object]) -> None:
    validate_owner(owner)
    inventory = validated_inventory()
    repository = next((repo for repo in inventory["repositories"] if repo["name"] == name), None)
    if repository is None or settings != merged_repository_settings(inventory, repository):
        raise ValueError("settings must match the complete validated family inventory")
    subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"repos/{owner}/{name}",
            "--input",
            "-",
        ],
        input=json.dumps(settings),
        text=True,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply governed GitHub repository settings from inventory",
    )
    parser.add_argument("--owner", default="bijux", help="GitHub organization owner")
    args = parser.parse_args()

    validate_owner(args.owner)
    # Settings cannot be applied independently of the bound ruleset preflight.
    from governance_execution import apply, RECEIPT
    apply(json.loads(RECEIPT.read_text()))


if __name__ == "__main__":
    main()
