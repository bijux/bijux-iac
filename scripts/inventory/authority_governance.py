"""Own desired control-plane and mirror policy independently of legacy Terraform."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.inventory.authority import (
    GITHUB_IDENTITIES,
    GITLAB_PROJECTS,
    PERSONAL_MIRRORS,
)
from scripts.inventory.repositories import ROOT, FAMILY_REPOSITORIES, unique_keys

PATH = ROOT / "inventory/authority-governance.json"
APP_ID = 5768636
RULESETS = {"bijux-std": (15229269, 27309240), "bijux-iac": (15864678, 27309246)}
DEPLOY_KEYS = {"bijux-std": 22049447, "bijux-iac": 22049448}


def desired_governance() -> dict:
    rows = []
    for name in ("bijux-std", "bijux-iac"):
        admission, history = RULESETS[name]
        rows.append(
            {
                "name": name,
                "publication_enabled": False,
                "canonical": {
                    "host": "gitlab.com",
                    "path": "bijux-oss/" + name,
                    "id": GITLAB_PROJECTS[name],
                    "execution_provider": "gitlab-ci",
                    "default_branch": "main",
                    "main": {
                        "push_access_level": 0,
                        "merge_access_level": 40,
                        "allow_force_push": False,
                    },
                    "publication_environment": {
                        "name": "publication",
                        "deploy_access_level": 40,
                    },
                },
                "github_mirror": {
                    "host": "github.com",
                    "path": "bijux/" + name,
                    "id": GITHUB_IDENTITIES[name],
                    "actions_enabled": False,
                    "app_id": APP_ID,
                    "admission_ruleset_id": admission,
                    "history_ruleset_id": history,
                    "history_guard_bypass": [],
                    "history_rules": ["deletion", "non_fast_forward"],
                    "restrict_updates": True,
                    "allows_fetch_and_merge": False,
                    "admission_bypass": [
                        {
                            "actor_id": APP_ID,
                            "actor_type": "Integration",
                            "bypass_mode": "always",
                        }
                    ],
                    "required_check": {
                        "context": "gitlab / validation",
                        "integration_id": APP_ID,
                    },
                    "pull_request_parameters": {
                        "allowed_merge_methods": ["merge"],
                        "required_approving_review_count": 0,
                        "dismiss_stale_reviews_on_push": True,
                        "required_review_thread_resolution": True,
                        "require_code_owner_review": False,
                        "require_last_push_approval": False,
                        "require_extra_approval_for_unattributed_changes": True,
                        "required_reviewers": [],
                    },
                },
                "personal_mirror": {
                    "host": "gitlab.com",
                    "path": "bijux/" + name,
                    "id": PERSONAL_MIRRORS[name],
                    "ci_enabled": False,
                    "shared_runners_enabled": False,
                    "group_runners_enabled": False,
                    "auto_devops_enabled": False,
                    "deploy_key_id": DEPLOY_KEYS[name],
                    "merge_access_level": 0,
                    "allow_force_push": False,
                },
            }
        )
    return {
        "version": 1,
        "claim": "desired",
        "repositories": rows,
        "product_publication": {
            "bijux-ontology": {
                "owner": "bijux-ontology",
                "controller": "iac",
                "mode": "manual-only",
                "enabled": False,
                "entrypoints": {},
                "standard_capabilities": ["common", "python"],
            }
        },
    }


def load_governance(path: Path = PATH) -> dict:
    return json.loads(path.read_text(), object_pairs_hook=unique_keys)


def validate_governance(
    policy: dict, *, require_standard: bool = True, standard: dict | None = None
) -> None:
    # Canonical JSON comparison distinguishes booleans from integer identities.
    if json.dumps(policy, sort_keys=True) != json.dumps(
        desired_governance(), sort_keys=True
    ):
        raise ValueError(
            "authority governance differs from the exact desired role and publisher contract"
        )
    if not require_standard:
        return
    if standard is None:
        standard = json.loads(
            (ROOT / ".github/standards/repo-config.manifest.json").read_text()
        )
    entries = standard.get("repositories", [])
    if len(entries) != 14 or {row.get("name") for row in entries} != set(
        FAMILY_REPOSITORIES
    ):
        raise ValueError(
            "authority governance requires an accepted fourteen-repository standard including Ontology"
        )
    ontology = next(row for row in entries if row["name"] == "bijux-ontology")
    if (
        ontology.get("standard_capabilities")
        != policy["product_publication"]["bijux-ontology"]["standard_capabilities"]
        or ontology.get("workflow_execution_policy", {}).get("main_verification")
        != "existing-events"
        or ontology.get("workflow_execution_policy", {}).get("publication_entrypoints")
        != {}
    ):
        raise ValueError(
            "Ontology capabilities and owned workflow/publication contract differ from accepted standards"
        )
