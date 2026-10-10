#!/usr/bin/env python3
"""Read-only preflight and application of its exact accepted-main inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from scripts.github.audit import audit, compare_settings
from scripts.github.api import gh_api_json, list_rulesets
from scripts.github.checks import require_producers
from scripts.github.settings import apply_settings
from scripts.terraform.imports import import_rulesets, WORK_DIR
from scripts.inventory.repositories import ROOT, validated_inventory, merged_repository_settings, validate_owner

ARTIFACTS = ROOT / "artifacts/governance"
RECEIPT = ARTIFACTS / "receipt.json"
PLAN = WORK_DIR / "governance.tfplan"
TERRAFORM_VERSION = "1.16.5"


def write_receipt(receipt: dict) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


def input_digests() -> dict[str, str]:
    paths = [ROOT / "inventory/repositories.json", ROOT / "Makefile", ROOT / "makes/root.mk",
             ROOT / ".github/standards/bijux-std.sha"]
    for directory in ("scripts", "infra/github/repository-rulesets", ".github/workflows"):
        paths.extend(p for p in (ROOT / directory).rglob("*") if p.is_file() and ".terraform" not in p.parts)
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def require_main(repository: str, event: str, ref: str, sha: str) -> None:
    if repository != "bijux/bijux-iac" or event != "workflow_dispatch" or ref != "refs/heads/main":
        raise ValueError("privileged governance requires manual dispatch on bijux/bijux-iac main")
    accepted = gh_api_json("repos/bijux/bijux-iac/commits/main")
    if not isinstance(accepted, dict) or accepted.get("sha") != sha or git_head() != sha:
        raise ValueError("application inputs must be the current accepted main commit")


def require_accepted_main() -> None:
    require_main(os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_EVENT_NAME", ""),
                 os.environ.get("GITHUB_REF", ""), os.environ.get("GITHUB_SHA", ""))
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise ValueError("application requires a clean accepted checkout")


def terraform(*arguments: str, capture: bool = False) -> str:
    environment = {**os.environ, "TF_DATA_DIR": str(ROOT / "artifacts/terraform/data")}
    result = subprocess.run(["terraform", f"-chdir={WORK_DIR}", *arguments], env=environment,
                            check=True, text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else ""


def settings_plan(inventory: dict, *, require_complete: bool = True) -> dict:
    changes = {}
    for repository in inventory["repositories"]:
        name = repository["name"]
        live = gh_api_json(f"repos/bijux/{name}")
        if not isinstance(live, dict) or live.get("full_name") != f"bijux/{name}" or live.get("default_branch") != "main":
            raise ValueError(f"{name}: repository identity/default branch could not be verified")
        expected = merged_repository_settings(inventory, repository)
        unavailable = [key for key in expected if key not in live]
        if (require_complete and unavailable) or any(type(live[key]) is not type(value) for key, value in expected.items() if key in live):
            raise ValueError(f"{name}: incomplete or malformed live settings")
        changes[name] = {"before": {key: live[key] for key in expected if key in live}, "after": expected}
        if unavailable:
            changes[name]["unavailable_to_reader"] = unavailable
    return changes


def verify_credential() -> dict:
    """Observe required administrative visibility without probing a write API."""
    require_accepted_main()
    inventory = validated_inventory()
    settings_plan(inventory)
    access, errors = [], []
    for repository in inventory["repositories"]:
        name = repository["name"]
        try:
            rulesets = [rule for rule in list_rulesets(name) if rule["name"] == "main-branch-protection"]
            if len(rulesets) != 1:
                raise ValueError("exactly one managed ruleset is needed to verify administrator visibility")
            detail = gh_api_json(f"repos/bijux/{name}/rulesets/{rulesets[0]['id']}")
            # GitHub returns bypass actors only to callers with ruleset write
            # permission. Their presence verifies scoped administrative visibility;
            # policy contents are evaluated separately by the complete live audit.
            if not isinstance(detail, dict) or not isinstance(detail.get("bypass_actors"), list):
                raise ValueError("ruleset administration visibility is unavailable")
            checks = gh_api_json(f"repos/bijux/{name}/commits/main/check-runs?per_page=1")
            prs = gh_api_json(f"repos/bijux/{name}/pulls?state=closed&base=main&per_page=1")
            if not isinstance(checks, dict) or not isinstance(checks.get("check_runs"), list) or not isinstance(prs, list):
                raise ValueError("check-run or pull-request reads could not be verified")
            access.append({"repository": name, "administration_visible": True, "check_and_pr_reads": True})
        except (ValueError, subprocess.CalledProcessError) as error:
            errors.append(f"{name}: {error}")
    receipt = {"status": "credential-verification-failed" if errors else "credential-verified",
               "commit": git_head(), "input_digests": input_digests(),
               "credential_access": access, "errors": errors, "remote_writes": False}
    write_receipt(receipt)
    if errors:
        raise ValueError("\n".join(errors))
    return receipt


def preflight(privileged: bool) -> dict:
    validate_owner(os.environ.get("TF_VAR_github_owner", "bijux"))
    inventory = validated_inventory()
    producers = None
    if privileged:
        require_accepted_main()
        producers = require_producers(inventory)
    version = json.loads(subprocess.check_output(["terraform", "version", "-json"], text=True))
    if version.get("terraform_version") != TERRAFORM_VERSION:
        raise ValueError(f"Terraform must be {TERRAFORM_VERSION}")
    receipt = {"status": "preflight", "commit": git_head(), "privileged": privileged,
               "remote_writes": False,
               "input_digests": input_digests(), "tools": {"terraform": TERRAFORM_VERSION, "github_provider": "6.13.0"},
               "settings": settings_plan(inventory, require_complete=privileged), "completed": [], "outstanding": []}
    if producers is not None:
        receipt["producer_evidence"] = producers
    write_receipt(receipt)
    subprocess.run(["make", "contract-tests", "terraform-validate"], cwd=ROOT, check=True)
    # Each execution rebuilds state from authoritative discovery, including retries.
    for state in WORK_DIR.glob("terraform.tfstate*"):
        state.unlink()
    import_rulesets()
    terraform("plan", "-input=false", f"-out={PLAN}")
    plan = json.loads(terraform("show", "-json", str(PLAN), capture=True))
    changes = plan.get("resource_changes", [])
    allowed = {f'github_repository_ruleset.main["{r["name"]}"]' for r in inventory["repositories"]}
    for change in changes:
        if change.get("mode") == "managed" and (change.get("address") not in allowed or "delete" in change["change"]["actions"]):
            raise ValueError("plan contains an unowned or destructive resource operation")
    # Terraform JSON and binary plans contain sensitive variable values. Retain
    # only reviewable action summaries in the uploaded receipt; never tokens.
    fields = {"name", "repository", "target", "enforcement", "conditions", "rules", "bypass_actors"}
    receipt["ruleset_plan"] = [{
        "address": c["address"], "actions": c["change"]["actions"],
        "before": {key: value for key, value in (c["change"].get("before") or {}).items() if key in fields},
        "after": {key: value for key, value in (c["change"].get("after") or {}).items() if key in fields},
    } for c in changes if c.get("mode") == "managed"]
    receipt["plan_digest"] = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    receipt["status"] = "planned"
    write_receipt(receipt)
    return receipt


def verify_receipt(receipt: dict) -> None:
    if receipt.get("status") != "planned" or receipt.get("privileged") is not True:
        raise ValueError("application requires a successful privileged preflight")
    if receipt.get("commit") != git_head() or receipt.get("input_digests") != input_digests():
        raise ValueError("preflight inputs changed; re-plan accepted main")
    if receipt.get("plan_digest") != hashlib.sha256(PLAN.read_bytes()).hexdigest():
        raise ValueError("saved plan changed; re-plan accepted main")


def apply(receipt: dict) -> None:
    require_accepted_main()
    verify_receipt(receipt)
    inventory = validated_inventory()
    current = settings_plan(inventory)
    if current != receipt["settings"]:
        raise ValueError("live settings changed after planning; repeat preflight")
    receipt["outstanding"] = [f"settings:{name}" for name, settings in current.items()
                              if compare_settings(name, settings["after"], settings["before"])] + [
                                  f"ruleset:{repository['name']}" for repository in inventory["repositories"]
                              ] + ["audit:family"]
    receipt["status"] = "applying"
    # A write-capable operation may partially succeed; the operation ledger and
    # post-apply audit establish the outcome rather than a preflight no-write flag.
    receipt.pop("remote_writes", None)
    write_receipt(receipt)
    try:
        for operation in list(receipt["outstanding"]):
            if not operation.startswith("settings:"):
                continue
            name = operation.split(":", 1)[1]
            apply_settings("bijux", name, current[name]["after"])
            receipt["completed"].append(operation)
            receipt["outstanding"].remove(operation)
            write_receipt(receipt)
        terraform("apply", "-input=false", str(PLAN))
        receipt["status"] = "applied"
    except Exception as error:
        receipt["status"] = "failed"
        receipt["error"] = str(error)
        raise
    finally:
        try:
            errors = audit(inventory)
            receipt["audit"] = errors
            for repository in inventory["repositories"]:
                operation = f"ruleset:{repository['name']}"
                if operation in receipt["outstanding"] and not any(error.startswith(repository['name'] + ":") for error in errors):
                    receipt["completed"].append(operation)
                    receipt["outstanding"].remove(operation)
            if not errors:
                receipt["completed"].append("audit:family")
                receipt["outstanding"].remove("audit:family")
            elif receipt["status"] != "failed":
                receipt["status"] = "failed"
                receipt["error"] = "post-apply family audit found drift"
        except Exception as error:
            receipt["status"] = "failed"
            receipt["audit_error"] = str(error)
        write_receipt(receipt)
    if receipt["status"] != "applied":
        raise ValueError("application did not converge; inspect the operation receipt")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["plan", "verify-credential", "preflight", "apply"])
    args = parser.parse_args()
    if args.operation == "apply":
        apply(json.loads(RECEIPT.read_text()))
    else:
        write_receipt({"status": "preflight", "commit": git_head(),
                       "input_digests": input_digests(), "remote_writes": False})
        if PLAN.exists():
            PLAN.unlink()
        try:
            if args.operation == "verify-credential":
                verify_credential()
            else:
                preflight(args.operation == "preflight")
        except Exception as error:
            receipt = json.loads(RECEIPT.read_text())
            receipt.update(status="credential-verification-failed" if args.operation == "verify-credential" else "preflight-failed", error=str(error))
            write_receipt(receipt)
            raise


if __name__ == "__main__":
    main()
