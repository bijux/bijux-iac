"""Audit every applicable live publisher and controller trust without dispatching."""
from __future__ import annotations

import argparse
import base64
import json
import subprocess

from scripts.github.api import gh_api_json
from scripts.inventory.repositories import ROOT, validated_inventory
from scripts.inventory.publication import WORKFLOWS, documentation_destination, publisher_declarations, validate_publisher, workflow_policy


def publication_mismatches(policy, declarations: dict, documents: dict) -> list[str]:
    failures = []
    for workflow in sorted(declarations):
        try:
            validate_publisher(policy, workflow, documents[workflow + ".yml"])
        except (KeyError, TypeError, ValueError) as error:
            failures.append(f"{workflow}: {error}")
    for path, document in documents.items():
        identity = path.removesuffix(".yml")
        if identity in WORKFLOWS and identity not in declarations:
            failures.append(f"{path}: publisher is not an applicable capability")
        try:
            # The common controller boundary also covers repositories with no
            # publishers, which must not acquire a renamed publishing path.
            caller_policy = {"publication_entrypoints": {name: {"mode": "manual-only", "controller": "iac"} for name in WORKFLOWS}}
            policy.validate_publication_calls({path: document}, caller_policy)
        except (TypeError, ValueError) as error:
            failures.append(f"{path}: {error}")
    return failures


def audit(inventory: dict, actor_id: str) -> dict:
    if not actor_id.isdecimal():
        raise ValueError("audit requires the configured publication App bot's numeric identity")
    declarations = publisher_declarations(inventory)
    policy = workflow_policy()
    receipt = {"remote_writes": False, "controller_actor_id": actor_id, "repositories": [], "mismatches": []}
    for repository in inventory["repositories"]:
        name = repository["name"]
        observation = {"repository": name, "publishers": sorted(declarations[name]), "mismatches": []}
        receipt["repositories"].append(observation)
        try:
            commit = gh_api_json(f"repos/bijux/{name}/commits/main")["sha"]
            observation["commit"] = commit
            tree = gh_api_json(f"repos/bijux/{name}/git/trees/{commit}?recursive=1")
            if tree.get("truncated") is not False or not isinstance(tree.get("tree"), list):
                raise ValueError("complete workflow discovery is unavailable")
            documents = {}
            for entry in tree["tree"]:
                path = entry["path"]
                if not path.startswith(".github/workflows/") or not path.endswith((".yml", ".yaml")):
                    continue
                try:
                    if entry.get("type") != "blob" or entry.get("mode") != "100644" or path.count("/") != 2:
                        raise ValueError("workflow must be a regular file directly under .github/workflows")
                    blob = gh_api_json(f"repos/bijux/{name}/git/blobs/{entry['sha']}")
                    documents[path.rsplit("/", 1)[-1]] = policy.parse_workflow(base64.b64decode(blob["content"]), path)
                except (KeyError, TypeError, ValueError, subprocess.CalledProcessError) as error:
                    observation["mismatches"].append(f"{path}: workflow audit unavailable: {error}")
            observation["mismatches"].extend(publication_mismatches(policy, declarations[name], documents))
        except (KeyError, TypeError, ValueError, subprocess.CalledProcessError) as error:
            observation["mismatches"].append(f"workflow audit unavailable: {error}")
        if declarations[name]:
            try:
                destination = documentation_destination(inventory, name)
                observation["documentation_destination"] = destination
                trust_repository = destination['repository']
                variable = gh_api_json(f"repos/bijux/{trust_repository}/actions/variables/BIJUX_PUBLICATION_ACTOR_ID")
                if variable.get("value") != actor_id:
                    observation["mismatches"].append("publisher trust does not identify the configured App bot")
            except (ValueError, subprocess.CalledProcessError) as error:
                observation["mismatches"].append(f"publisher trust audit unavailable: {error}")
        receipt["mismatches"].extend(f"{name}: {error}" for error in observation["mismatches"])
    receipt["status"] = "converged" if not receipt["mismatches"] else "drift"
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor-id", required=True)
    args = parser.parse_args()
    receipt = audit(validated_inventory(), args.actor_id)
    path = ROOT / "artifacts/publication/audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    if receipt["mismatches"]:
        raise SystemExit("\n".join(receipt["mismatches"]))
    print("manual publication policy: OK (12 repositories)")


if __name__ == "__main__":
    main()
