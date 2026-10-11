"""Dispatch an admitted immutable publisher using a selected-repository App token."""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import re
import runpy
import subprocess

from scripts.execution.application import require_accepted_main
from scripts.github.api import gh_api_json
from scripts.inventory.repositories import ROOT, validated_inventory
from scripts.inventory.publication import documentation_destination, validate_request, validate_publisher, workflow_policy

APP_PERMISSIONS = {"actions": "write", "contents": "read", "checks": "read", "actions_variables": "read", "metadata": "read"}


def admit_controller(repository: str, workflow: str, commit: str, tag: str, *, credential_only: bool = False) -> str:
    require_accepted_main()
    validate_request(validated_inventory(), repository, workflow, commit, tag, require_published=not credential_only)
    actor = os.environ.get("PUBLICATION_CONTROLLER_ACTOR", "")
    if actor != "bijux-publication[bot]":
        raise ValueError("publication requires the dedicated bijux-publication App bot")
    app = gh_api_json("apps/bijux-publication")
    if (str(app.get("id")) != os.environ.get("PUBLICATION_APP_ID")
            or app.get("owner", {}).get("login") != "bijux" or app.get("permissions") != APP_PERMISSIONS):
        raise ValueError("controller App must have exactly the configured publication permissions")
    return actor


def resolve_destination(repository: str, workflow: str, commit: str) -> dict:
    """Select the real publisher before minting its single-repository credential."""
    route = (documentation_destination(validated_inventory(), repository) if workflow == "deploy-docs"
             else {"repository": repository, "path": None})
    target = route["repository"]
    accepted = commit if target == repository else gh_api_json(f"repos/bijux/{target}/commits/main").get("sha", "")
    if not isinstance(accepted, str) or not re.fullmatch(r"[0-9a-f]{40}", accepted):
        raise ValueError("publication destination requires an immutable accepted main commit")
    bound_target = os.environ.get("PUBLICATION_DESTINATION_REPOSITORY", "")
    bound_commit = os.environ.get("PUBLICATION_DESTINATION_COMMIT", "")
    if (bound_target or bound_commit) and (bound_target != target or bound_commit != accepted):
        raise ValueError("publication destination changed after credential-free selection")
    return {"repository": target, "commit": accepted, "path": route["path"]}


def admit_repository(repository: str, workflow: str, commit: str, tag: str, actor: str, trusted: str, *, public_source: bool = False) -> dict:
    """Admit one accepted revision without substituting another repository's inputs."""
    admission = runpy.run_path(str(ROOT / ".bijux/shared/bijux-gh/scripts/publication_admission.py"))
    reader = admission["public_api"] if public_source else gh_api_json
    live = reader(f"repos/bijux/{repository}/contents/.github/workflows/{workflow}.yml?ref={commit}")
    document = base64.b64decode(live["content"], validate=False)
    policy = workflow_policy()
    validate_publisher(policy, workflow, policy.parse_workflow(document, workflow + ".yml"))
    environment = {
        "PUBLICATION_REPOSITORY": "bijux/" + repository, "PUBLICATION_EVENT": "workflow_dispatch",
        "PUBLICATION_REF": "refs/heads/main", "PUBLICATION_ACTOR": actor,
        "PUBLICATION_TRIGGERING_ACTOR": actor,
        "PUBLICATION_ACTOR_ID": os.environ.get("PUBLICATION_CONTROLLER_ACTOR_ID", ""),
        "PUBLICATION_CONTROLLER_ACTOR_ID": trusted, "PUBLICATION_COMMIT": commit,
        "PUBLICATION_RUN_SHA": commit, "PUBLICATION_WORKFLOW": workflow, "PUBLICATION_TAG": tag,
    }
    return admission["admit"](environment, public_source=True) if public_source else admission["admit"](environment)


def request(repository: str, workflow: str, commit: str, tag: str) -> dict:
    actor = admit_controller(repository, workflow, commit, tag)
    destination = resolve_destination(repository, workflow, commit)
    target = destination["repository"]
    trusted = gh_api_json(f"repos/bijux/{target}/actions/variables/BIJUX_PUBLICATION_ACTOR_ID").get("value", "")
    source = admit_repository(repository, workflow, commit, tag, actor, trusted, public_source=target != repository)
    receipt = source
    if target != repository:
        receipt = admit_repository(target, workflow, destination["commit"], tag, actor, trusted)
        receipt["requested_source"] = source
    # Source and destination must still be the admitted revisions at the dispatch boundary.
    for name, revision in {(repository, commit), (target, destination["commit"])}:
        reader = (runpy.run_path(str(ROOT / ".bijux/shared/bijux-gh/scripts/publication_admission.py"))["public_api"]
                  if name != target else gh_api_json)
        if reader(f"repos/bijux/{name}/commits/main").get("sha") != revision:
            raise ValueError("publication source or destination main changed during admission")
    receipt["destination"] = destination
    receipt["requested_repository"] = repository
    receipt["requested_commit"] = commit
    return receipt


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
        actor = admit_controller(repository, workflow, commit, tag, credential_only=True)
        destination = resolve_destination(repository, workflow, commit)
        receipt["destination"] = destination
        bot = gh_api_json(f"users/{actor}")
        if bot.get("type") != "Bot" or str(bot.get("id")) != os.environ.get("PUBLICATION_CONTROLLER_ACTOR_ID"):
            raise ValueError("configured publication actor ID must identify the dedicated App bot")
        if destination["repository"] != repository:
            public_reader = runpy.run_path(str(ROOT / ".bijux/shared/bijux-gh/scripts/publication_admission.py"))["public_api"]
            if public_reader(f"repos/bijux/{repository}/commits/main").get("sha") != commit:
                raise ValueError("credential verification requires the requested current main commit")
        prefix = f"repos/bijux/{destination['repository']}"
        live = gh_api_json(prefix)
        accepted = gh_api_json(prefix + "/commits/main")
        if (live.get("full_name") != "bijux/" + destination["repository"] or live.get("default_branch") != "main"
                or accepted.get("sha") != destination["commit"]):
            raise ValueError("credential verification requires the selected current main commit")
        for endpoint, key in [("check-runs", "check_runs"), ("workflows", "workflows"), ("variables", "variables")]:
            path = prefix + (f"/commits/{destination['commit']}/check-runs?per_page=1" if endpoint == "check-runs" else f"/actions/{endpoint}?per_page=1")
            if not isinstance(gh_api_json(path).get(key), list):
                raise ValueError(f"publication credential {endpoint} read could not be verified")
        receipt.update(status="credential-verified", controller_actor_id=str(bot["id"]), required_reads_verified=True)
        token = os.environ.get("GH_TOKEN", "")
        if token:
            # Diagnostic shape only: authentication treats the entire token as opaque.
            receipt["credential_transport"] = {
                "characters": len(token),
                "observed_format": "stateless" if token.startswith("ghs_") and token.count(".") == 2 else "opaque",
            }
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
    destination = receipt.get("destination", {"repository": repository, "commit": commit})
    inputs = {"accepted_commit": destination["commit"]}
    if workflow != "deploy-docs":
        inputs["release_tag"] = tag
    try:
        receipt["remote_write_attempted"] = True
        subprocess.run(["gh", "api", "--method", "POST", f"repos/bijux/{destination['repository']}/actions/workflows/{workflow}.yml/dispatches", "--input", "-"],
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
        validate_request(validated_inventory(), *values, require_published=os.environ["PUBLICATION_OPERATION"] != "verify-credential")
        destination = resolve_destination(values[0], values[1], values[2])
        if os.environ.get("GITHUB_OUTPUT"):
            with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
                output.write("repository=" + destination["repository"] + "\n")
                output.write("commit=" + destination["commit"] + "\n")
        write_receipt({"status": "operation-not-completed", "operation": os.environ["PUBLICATION_OPERATION"],
                       "repository": values[0], "workflow": values[1], "commit": values[2], "tag": values[3],
                       "controller_commit": os.environ["GITHUB_SHA"], "controller_run": os.environ["GITHUB_RUN_ID"],
                       "destination": destination, "remote_writes": False})
    else:
        {"verify-credential": verify_credential, "preflight": preflight, "dispatch": dispatch}[args.operation](*values)


if __name__ == "__main__":
    main()
