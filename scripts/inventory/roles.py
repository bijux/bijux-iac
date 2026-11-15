"""Keep family membership separate from the authority allowed to write policy."""

from __future__ import annotations

from scripts.inventory.repositories import FAMILY_REPOSITORIES
from scripts.inventory.authority import GITLAB_PROJECTS

GITLAB_DEVELOPMENT_REPOSITORIES = frozenset(GITLAB_PROJECTS)


def github_development_inventory(inventory: dict) -> dict:
    """Project legacy resources without mutating the complete capability family."""
    return {
        **inventory,
        "repositories": [
            row
            for row in inventory["repositories"]
            if row["name"] not in GITLAB_DEVELOPMENT_REPOSITORIES
        ],
    }


def require_github_development_repository(name: str) -> None:
    if name in GITLAB_DEVELOPMENT_REPOSITORIES:
        raise ValueError(
            f"{name}: GitLab-owned mirror cannot use legacy GitHub governance"
        )
    if name not in FAMILY_REPOSITORIES:
        raise ValueError("repository is outside the governed family")
