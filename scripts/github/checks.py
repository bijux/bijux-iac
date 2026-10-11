"""Verify and retain the accepted GitHub Actions producers before enforcement."""
from __future__ import annotations

import base64
import json
import re
import subprocess

from scripts.github.api import gh_api_json
from scripts.github.audit import STATUS_APP_ID
from scripts.inventory.repositories import ROOT, validated_inventory
from scripts.inventory.workflows import merged_workflow_execution

PR_ONLY_CHECKS = {"policy / pr approval"}


def check_runs(repository: str, commit: str) -> list[dict]:
    pages = json.loads(subprocess.check_output([
        "gh", "api", "--paginate", "--slurp",
        f"repos/bijux/{repository}/commits/{commit}/check-runs?per_page=100&filter=all",
    ], text=True))
    if not isinstance(pages, list) or not all(isinstance(page, dict) and isinstance(page.get("check_runs"), list) for page in pages):
        raise ValueError("malformed accepted-commit check response")
    runs = [run for page in pages for run in page["check_runs"]]
    if not all(isinstance(run, dict) and type(run.get("id")) is int
               and isinstance(run.get("name"), str) and isinstance(run.get("app"), dict)
               and type(run["app"].get("id")) is int and isinstance(run.get("head_sha"), str)
               for run in runs):
        raise ValueError("malformed accepted check run")
    return runs


def latest_producers(commit: str, runs: list[dict]) -> dict[str, dict]:
    latest = {}
    for run in runs:
        if run["head_sha"] != commit or run["app"]["id"] != STATUS_APP_ID:
            continue
        if run["id"] > latest.get(run["name"], {}).get("id", -1):
            latest[run["name"]] = run
    return latest


def accepted_merge(repository: str, main: dict, prs: list[dict]) -> dict:
    """Bind PR evidence to this exact main merge, never an older accepted head."""
    matches = [pr for pr in prs if pr.get("merged_at") and pr.get("merge_commit_sha") == main["sha"]]
    if len(matches) != 1:
        raise ValueError("current main must identify exactly one accepted pull request")
    pr = matches[0]
    parents = main.get("parents", [])
    head = pr.get("head", {}).get("sha") if isinstance(pr.get("head"), dict) else None
    if (not isinstance(parents, list) or len(parents) != 2
            or not all(isinstance(parent, dict) and isinstance(parent.get("sha"), str)
                       and re.fullmatch(r"[0-9a-f]{40}", parent["sha"]) for parent in parents)
            or parents[1].get("sha") != head
            or not isinstance(pr.get("base"), dict) or pr["base"].get("ref") != "main"
            or pr["base"].get("sha") != parents[0].get("sha")
            or not isinstance(pr["base"].get("repo"), dict)
            or pr["base"]["repo"].get("full_name") != f"bijux/{repository}"
            or pr.get("state") != "closed" or type(pr.get("number")) is not int
            or not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head)):
        raise ValueError("accepted verification requires an exact ancestry-preserving main merge")
    if not isinstance(pr.get("user"), dict) or not isinstance(pr["user"].get("login"), str):
        raise ValueError("accepted pull request must identify its original author")
    if (pr["user"]["login"] == "dependabot[bot]"
            or (pr["user"]["login"] == "github-actions[bot]"
                and pr["head"].get("ref") == "automation/dependency-lock-refresh")):
        raise ValueError("a dependency notification cannot establish accepted verification")
    return pr


def verify_remote_execution(repository: str, commit: str, expected: dict) -> None:
    response = gh_api_json(f"repos/bijux/{repository}/contents/.github/standards/repo-config.manifest.json?ref={commit}")
    if not isinstance(response, dict) or response.get("encoding") != "base64":
        raise ValueError("accepted consumer workflow declaration is unavailable")
    manifest = json.loads(base64.b64decode(response["content"]).decode("utf-8"))
    if (not isinstance(manifest, dict) or not isinstance(manifest.get("repositories"), list)
            or not all(isinstance(entry, dict) for entry in manifest["repositories"])):
        raise ValueError("accepted consumer workflow declaration is malformed")
    entries = [entry for entry in manifest["repositories"] if entry.get("name") == repository]
    if len(entries) != 1 or not isinstance(entries[0].get("workflow_execution_policy"), dict):
        raise ValueError("accepted consumer workflow declaration is malformed")
    if any(entries[0]["workflow_execution_policy"].get(key) != value for key, value in expected.items()):
        raise ValueError("accepted consumer has not adopted the declared workflow execution policy")


def producer_evidence(inventory: dict) -> dict:
    receipt = {"remote_writes": False, "repositories": [], "errors": []}
    for repository in inventory["repositories"]:
        name = repository["name"]
        observation = {"repository": name, "checks": [], "errors": []}
        receipt["repositories"].append(observation)
        try:
            main_commit = gh_api_json(f"repos/bijux/{name}/commits/main")
            commit = main_commit["sha"]
            if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
                raise ValueError("main must resolve to an immutable accepted commit")
            observation["main_commit"] = commit
            execution = merged_workflow_execution(inventory, repository)
            if execution["main_verification"] not in {"accepted-pull-request", "existing-events"}:
                raise ValueError("unknown main verification policy")
            accepted_only = execution["main_verification"] == "accepted-pull-request"
            main = {} if accepted_only else latest_producers(commit, check_runs(name, commit))
            prs = gh_api_json(f"repos/bijux/{name}/commits/{commit}/pulls?per_page=100")
            if not isinstance(prs, list) or not all(isinstance(pr, dict) for pr in prs):
                raise ValueError("malformed accepted PR response")
            merged = accepted_merge(name, main_commit, prs)
            if accepted_only:
                verify_remote_execution(name, commit, execution)
            pr_sha = merged["head"]["sha"]
            observation["verification_source"] = "accepted-pull-request" if accepted_only else "existing-events"
            observation["accepted_pr"] = {"number": merged["number"], "commit": pr_sha, "merge_commit": commit}
            accepted_pr = latest_producers(pr_sha, check_runs(name, pr_sha))
            for context in repository["governance"]["branch_protection"]["required_status_checks"]:
                # PR-only verification requires exact accepted merge ancestry and
                # adoption of that execution policy. Existing-event repositories
                # retain their current-main result, including failed retries.
                run = accepted_pr.get(context) if accepted_only or context in PR_ONLY_CHECKS else main.get(context)
                if run is None and context not in PR_ONLY_CHECKS:
                    run = accepted_pr.get(context)
                if run is None or run.get("status") != "completed" or run.get("conclusion") != "success":
                    observation["errors"].append(f"no healthy accepted GitHub Actions producer for {context!r}")
                    continue
                observation["checks"].append({"context": context, "commit": run["head_sha"],
                                              "check_run_id": run["id"], "app_id": run["app"]["id"]})
            current = gh_api_json(f"repos/bijux/{name}/commits/main")
            if not isinstance(current, dict) or current.get("sha") != commit:
                raise ValueError("main changed while accepted verification evidence was collected")
        except (KeyError, TypeError, ValueError, subprocess.CalledProcessError) as error:
            observation["errors"].append(f"producer discovery unavailable: {error}")
        receipt["errors"].extend(f"{name}: {error}" for error in observation["errors"])
    receipt["status"] = "producers-unverified" if receipt["errors"] else "producers-verified"
    return receipt


def require_producers(inventory: dict) -> dict:
    receipt = producer_evidence(inventory)
    path = ROOT / "artifacts/governance/producers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2) + "\n")
    if receipt["errors"]:
        raise ValueError("\n".join(receipt["errors"]))
    return receipt


if __name__ == "__main__":
    require_producers(validated_inventory())
    print("accepted check producers: OK (12 repositories)")
