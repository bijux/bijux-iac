from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "inventory/repositories.json"

FAMILY_REPOSITORIES = {
    "bijux-iac": ("foundation", "terraform", "not-applicable", "not-applicable"),
    "bijux-std": ("foundation", "make", "not-applicable", "not-applicable"),
    "bijux.github.io": ("web-course", "docs", "published", "not-applicable"),
    "bijux-masterclass": ("web-course", "docs", "published", "not-applicable"),
    "bijux-canon": ("python", "python", "published", "published"),
    "bijux-proteomics": ("python", "python", "published", "published"),
    "bijux-pollenomics": ("python", "python", "published", "published"),
    "bijux-phylogenetics": ("python", "python", "published", "published"),
    "bijux-core": ("rust", "rust", "published", "published"),
    "bijux-atlas": ("rust", "rust", "published", "published"),
    "bijux-gnss": ("rust", "rust", "published", "published"),
    "bijux-genomics": ("rust", "rust", "planned", "planned"),
}

BASELINE_REQUIRED_STATUS_CHECKS = {
    "policy / github",
    "policy / pr approval",
    "std / standard",
    "std / report",
}


def load_inventory(path: Path = INVENTORY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def merged_repository_settings(
    inventory: dict[str, Any],
    repository: dict[str, Any],
) -> dict[str, Any]:
    return {
        **inventory["repository_settings_defaults"],
        **repository.get("settings", {}),
    }
