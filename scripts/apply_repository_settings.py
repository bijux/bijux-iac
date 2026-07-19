#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess

from repository_inventory import load_inventory, merged_repository_settings


def apply_settings(owner: str, name: str, settings: dict[str, object]) -> None:
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

    inventory = load_inventory()
    repositories = inventory["repositories"]
    for repository in repositories:
        name = repository["name"]
        settings = merged_repository_settings(inventory, repository)
        apply_settings(args.owner, name, settings)
        print(f"repository settings applied: {name}")

    print(f"repository settings: OK ({len(repositories)} repositories)")


if __name__ == "__main__":
    main()
