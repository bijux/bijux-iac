"""Dispatch an admitted immutable publisher using a selected-repository App token."""
from __future__ import annotations

import argparse
import base64
import json
import os
import runpy
import subprocess

from scripts.execution.application import require_accepted_main
from scripts.github.api import gh_api_json
from scripts.inventory.repositories import ROOT, validated_inventory
from scripts.inventory.publication import validate_request, validate_publisher, workflow_policy

APP_PERMISSIONS = {"actions": "write", "contents": "read", "checks": "read", "actions_variables": "read", "metadata": "read"}


def admit_controller(repository: str, workflow: str, commit: str, tag: str) -> str:
    require_accepted_main()
    validate_request(validated_inventory(), repository, workflow, commit, tag)
    actor = os.environ.get("PUBLICATION_CONTROLLER_ACTOR", "")
    if actor != "bijux-publication[bot]":
        raise ValueError("publication requires the dedicated bijux-publication App bot")
    app = gh_api_json("apps/bijux-publication")
    if (str(app.get("id")) != os.environ.get("PUBLICATION_APP_ID")
            or app.get("owner", {}).get("login") != "bijux" or app.get("permissions") != APP_PERMISSIONS):
        raise ValueError("controller App must have exactly the configured publication permissions")
    return actor


def request(repository: str, workflow: str, commit: str, tag: str) -> dict:
    actor = admit_controller(repository, workflow, commit, tag)
    live = gh_api_json(f"repos/bijux/{repository}/contents/.github/workflows/{workflow}.yml?ref={commit}")
    document = base64.b64decode(live["content"], validate=False)
    policy = workflow_policy()
    validate_publisher(policy, workflow, policy.parse_workflow(document, workflow + ".yml"))
    trusted = gh_api_json(f"repos/bijux/{repository}/actions/variables/BIJUX_PUBLICATION_ACTOR_ID").get("value", "")
    environment = {
        "PUBLICATION_REPOSITORY": "bijux/" + repository, "PUBLICATION_EVENT": "workflow_dispatch",
        "PUBLICATION_REF": "refs/heads/main", "PUBLICATION_ACTOR": actor,
        "PUBLICATION_TRIGGERING_ACTOR": actor,
        "PUBLICATION_ACTOR_ID": os.environ.get("PUBLICATION_CONTROLLER_ACTOR_ID", ""),
        "PUBLICATION_CONTROLLER_ACTOR_ID": trusted, "PUBLICATION_COMMIT": commit,
        "PUBLICATION_RUN_SHA": commit, "PUBLICATION_WORKFLOW": workflow, "PUBLICATION_TAG": tag,
    }
    admit = runpy.run_path(str(ROOT / ".bijux/shared/bijux-gh/scripts/publication_admission.py"))["admit"]
    return admit(environment)


def write_receipt(receipt: dict) -> None:
    path = ROOT / "artifacts/publication/request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n")


def verify_credential(repository: str, workflow: str, commit: str, tag: str) -> dict:
    """Verify the selected installation and required reads without dispatching."""
    receipt = {"repository": repository, "commit": commit, "controller_commit": os.environ["GITHUB_SHA"],
               "controller_run": os.environ["GITHUB_RUN_ID"], "status": "credential-verification-failed",
               "remote_writes": False, "dispatch_write_permission_tested": False}
    try:
        actor = admit_controller(repository, workflow, commit, tag)
        bot = gh_api_json(f"users/{actor}")
        if bot.get("type") != "Bot" or str(bot.get("id")) != os.environ.get("PUBLICATION_CONTROLLER_ACTOR_ID"):
            raise ValueError("configured publication actor ID must identify the dedicated App bot")
        prefix = f"repos/bijux/{repository}"
        live = gh_api_json(prefix)
        accepted = gh_api_json(prefix + "/commits/main")
        if live.get("full_name") != "bijux/" + repository or live.get("default_branch") != "main" or accepted.get("sha") != commit:
            raise ValueError("credential verification requires the selected current main commit")
        for endpoint, key in [("check-runs", "check_runs"), ("workflows", "workflows"), ("variables", "variables")]:
            path = prefix + (f"/commits/{commit}/check-runs?per_page=1" if endpoint == "check-runs" else f"/actions/{endpoint}?per_page=1")
            if not isinstance(gh_api_json(path).get(key), list):
                raise ValueError(f"publication credential {endpoint} read could not be verified")
        receipt.update(status="credential-verified", controller_actor_id=str(bot["id"]), required_reads_verified=True)
    finally:
        write_receipt(receipt)
    return receipt


def preflight(repository: str, workflow: str, commit: str, tag: str) -> dict:
    receipt = request(repository, workflow, commit, tag)
    receipt.update(controller_commit=os.environ["GITHUB_SHA"], controller_run=os.environ["GITHUB_RUN_ID"],
                   status="admitted", remote_writes=False)
    write_receipt(receipt)
    return receipt


def dispatch(repository: str, workflow: str, commit: str, tag: str) -> dict:
    receipt = preflight(repository, workflow, commit, tag)
    inputs = {"accepted_commit": commit}
    if workflow != "deploy-docs":
        inputs["release_tag"] = tag
    try:
        receipt["remote_write_attempted"] = True
        subprocess.run(["gh", "api", "--method", "POST", f"repos/bijux/{repository}/actions/workflows/{workflow}.yml/dispatches", "--input", "-"],
                       input=json.dumps({"ref": "main", "inputs": inputs}), text=True, check=True)
        receipt["status"] = "dispatched"
        receipt["remote_writes"] = True
    except subprocess.CalledProcessError:
        receipt["status"] = "dispatch-failed"
        receipt["remote_writes"] = None
        raise
    finally:
        write_receipt(receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["validate", "verify-credential", "preflight", "dispatch"])
    args = parser.parse_args()
    values = tuple(os.environ.get("PUBLICATION_TARGET_" + name, "") for name in ("REPOSITORY", "WORKFLOW", "COMMIT", "TAG"))
    if args.operation == "validate":
        if os.environ.get("PUBLICATION_OPERATION") not in {"verify-credential", "preflight", "dispatch"}:
            raise ValueError("publication operation must be explicit")
        require_accepted_main()
        validate_request(validated_inventory(), *values)
    else:
        {"verify-credential": verify_credential, "preflight": preflight, "dispatch": dispatch}[args.operation](*values)


if __name__ == "__main__":
    main()
