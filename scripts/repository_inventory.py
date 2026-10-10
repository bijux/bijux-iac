from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "inventory/repositories.json"

FAMILY_REPOSITORIES = {
    "bijux-iac": ("foundation", "terraform", "not-applicable", "not-applicable"),
    "bijux-std": ("foundation", "make", "not-applicable", "not-applicable"),
    "bijux.github.io": ("hubs", "docs", "published", "not-applicable"),
    "bijux-masterclass": ("hubs", "docs", "published", "not-applicable"),
    "bijux-genomics": ("rust", "rust", "planned", "planned"),
    "bijux-core": ("rust", "rust", "published", "published"),
    "bijux-atlas": ("rust", "rust", "published", "published"),
    "bijux-gnss": ("rust", "rust", "published", "published"),
    "bijux-canon": ("python", "python", "published", "published"),
    "bijux-pollenomics": ("python", "python", "published", "published"),
    "bijux-proteomics": ("python", "python", "published", "published"),
    "bijux-phylogenetics": ("python", "python", "published", "published"),
}

BASELINE_REQUIRED_STATUS_CHECKS = {
    "policy / github",
    "policy / pr approval",
    "std / standard",
    "std / report",
}


def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate inventory key: {key}")
        result[key] = value
    return result


def load_inventory(path: Path = INVENTORY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)


def canonical_inventory(inventory: dict[str, Any]) -> str:
    repositories = {repo["name"]: repo for repo in inventory["repositories"]}
    class_order = ("foundation", "hubs", "rust", "python")
    repository_keys = ("name", "class", "stack", "delivery", "settings", "governance")
    normalized = {
        "version": inventory["version"],
        "classes": {name: inventory["classes"][name] for name in class_order},
        "repository_settings_defaults": inventory["repository_settings_defaults"],
        "repositories": [{key: repositories[name][key] for key in repository_keys} for name in FAMILY_REPOSITORIES],
    }
    return json.dumps(normalized, indent=2) + "\n"


def merged_repository_settings(
    inventory: dict[str, Any],
    repository: dict[str, Any],
) -> dict[str, Any]:
    return {
        **inventory["repository_settings_defaults"],
        **repository["settings"],
    }


def validated_inventory() -> dict[str, Any]:
    from validate_repo_inventory import validate_inventory

    inventory = load_inventory()
    validate_inventory(inventory)
    return inventory


def validate_owner(owner: str) -> None:
    if owner != "bijux":
        raise SystemExit("governance owner must be bijux")
