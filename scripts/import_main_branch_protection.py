#!/usr/bin/env python3
"""Import verified live rulesets into the isolated Terraform working state."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from audit_live_repository_governance import list_rulesets, RULESET_NAME
from render_main_branch_protection_tfvars import render_payload
from repository_inventory import ROOT, validated_inventory, validate_owner

WORK_DIR = ROOT / "artifacts/terraform/module"


def discover_ruleset(repository: str) -> int | None:
    matches = [rule for rule in list_rulesets(repository)
               if rule["target"] == "branch" and rule["name"] in {RULESET_NAME, "main-pr-only-admin-bypass"}]
    if len(matches) > 1:
        raise ValueError(f"{repository}: ambiguous managed ruleset discovery")
    return matches[0]["id"] if matches else None


def discover_all(inventory: dict) -> dict[str, int | None]:
    # Complete authoritative discovery before importing anything. A failed lookup
    # must never leave a partial discovery mistaken for permission to create.
    return {repository["name"]: discover_ruleset(repository["name"])
            for repository in inventory["repositories"]}


def import_rulesets() -> None:
    validate_owner(os.environ.get("TF_VAR_github_owner", "bijux"))
    inventory = validated_inventory()
    committed = ROOT / "infra/github/main-branch-protection/terraform.auto.tfvars.json"
    expected = render_payload()
    if json.loads(committed.read_text()) != expected or json.loads((WORK_DIR / committed.name).read_text()) != expected:
        raise SystemExit("import requires validated, identical governed and working Terraform inputs")
    discovery = discover_all(inventory)
    log_dir = ROOT / "artifacts/governance/imports"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "discovery.json").write_text(json.dumps(discovery, indent=2) + "\n")
    environment = {**os.environ, "TF_DATA_DIR": str(ROOT / "artifacts/terraform/data")}
    for repository, identifier in discovery.items():
        if identifier is None:
            print(f"{repository}: authoritative lookup verified absence")
            continue
        with (log_dir / f"{repository}.log").open("w") as log:
            subprocess.run([
                "terraform", f"-chdir={WORK_DIR}", "import", "-input=false",
                f'github_repository_ruleset.main["{repository}"]', f"{repository}:{identifier}",
            ], env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        print(f"{repository}: imported ruleset {identifier}")


if __name__ == "__main__":
    import_rulesets()
