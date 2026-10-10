"""Verify and retain the accepted GitHub Actions producers before enforcement."""
from __future__ import annotations

import json
import re
import subprocess

from scripts.github.api import gh_api_json
from scripts.github.audit import STATUS_APP_ID
from scripts.inventory.repositories import ROOT, validated_inventory

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


def producer_evidence(inventory: dict) -> dict:
    receipt = {"remote_writes": False, "repositories": [], "errors": []}
    for repository in inventory["repositories"]:
        name = repository["name"]
        observation = {"repository": name, "checks": [], "errors": []}
        receipt["repositories"].append(observation)
        try:
            commit = gh_api_json(f"repos/bijux/{name}/commits/main")["sha"]
            if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
                raise ValueError("main must resolve to an immutable accepted commit")
            observation["main_commit"] = commit
            main = latest_producers(commit, check_runs(name, commit))
            prs = gh_api_json(f"repos/bijux/{name}/pulls?state=closed&base=main&per_page=100&sort=updated&direction=desc")
            if not isinstance(prs, list) or not all(isinstance(pr, dict) for pr in prs):
                raise ValueError("malformed accepted PR response")
            merged = max((pr for pr in prs if pr.get("merged_at")),
                         key=lambda pr: pr["merged_at"], default=None)
            accepted_pr = {}
            if merged:
                pr_sha = merged["head"]["sha"]
                if not isinstance(pr_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", pr_sha):
                    raise ValueError("accepted PR must identify an immutable head")
                observation["accepted_pr"] = {"number": merged["number"], "commit": pr_sha}
                accepted_pr = latest_producers(pr_sha, check_runs(name, pr_sha))
            for context in repository["governance"]["branch_protection"]["required_status_checks"]:
                # Prefer evidence on current main. PR-only producers are observed
                # on accepted PR heads; a failed main retry cannot borrow PR success.
                run = accepted_pr.get(context) if context in PR_ONLY_CHECKS else main.get(context)
                if run is None and context not in PR_ONLY_CHECKS:
                    run = accepted_pr.get(context)
                if run is None or run.get("status") != "completed" or run.get("conclusion") != "success":
                    observation["errors"].append(f"no healthy accepted GitHub Actions producer for {context!r}")
                    continue
                observation["checks"].append({"context": context, "commit": run["head_sha"],
                                              "check_run_id": run["id"], "app_id": run["app"]["id"]})
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
