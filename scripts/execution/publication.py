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


def request(repository: str, workflow: str, commit: str, tag: str) -> dict:
    require_accepted_main()
    validate_request(validated_inventory(), repository, workflow, commit, tag)
    actor = os.environ.get("PUBLICATION_CONTROLLER_ACTOR", "")
    if actor != "bijux-publication[bot]":
        raise ValueError("publication requires the dedicated bijux-publication App bot")
    app = gh_api_json("apps/bijux-publication")
    if (str(app.get("id")) != os.environ.get("PUBLICATION_APP_ID")
            or app.get("owner", {}).get("login") != "bijux" or app.get("permissions") != APP_PERMISSIONS):
        raise ValueError("controller App must have exactly the configured publication permissions")
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


def dispatch(repository: str, workflow: str, commit: str, tag: str) -> dict:
    receipt = request(repository, workflow, commit, tag)
    receipt.update(controller_commit=os.environ["GITHUB_SHA"], controller_run=os.environ["GITHUB_RUN_ID"], status="admitted")
    path = ROOT / "artifacts/publication/request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    inputs = {"accepted_commit": commit}
    if workflow != "deploy-docs":
        inputs["release_tag"] = tag
    try:
        subprocess.run(["gh", "api", "--method", "POST", f"repos/bijux/{repository}/actions/workflows/{workflow}.yml/dispatches", "--input", "-"],
                       input=json.dumps({"ref": "main", "inputs": inputs}), text=True, check=True)
        receipt["status"] = "dispatched"
    except subprocess.CalledProcessError:
        receipt["status"] = "dispatch-failed"
        raise
    finally:
        path.write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["validate", "dispatch"])
    args = parser.parse_args()
    values = tuple(os.environ.get("PUBLICATION_TARGET_" + name, "") for name in ("REPOSITORY", "WORKFLOW", "COMMIT", "TAG"))
    if args.operation == "validate":
        require_accepted_main()
        validate_request(validated_inventory(), *values)
    else:
        dispatch(*values)


if __name__ == "__main__":
    main()
