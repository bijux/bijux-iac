"""Compose full fresh standards qualification from its existing owned registries."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shlex


NODE_VERSION = "24.21.0"
UV_VERSION = "0.11.17"
CONTRACT_PARTITION_COUNT = 6
PLAYWRIGHT_BASE_IMAGE = "mcr.microsoft.com/playwright@sha256:6446946a1d9fd62d9ae501312a2d76a43ee688542b21622056a372959b65d63d"
ROOT = Path(__file__).resolve().parents[2]


def runtime_image(root: Path = ROOT) -> str:
    root = Path(root).resolve()
    runtime = root / "shared/bijux-gitlab/runtime"
    paths = [runtime / name for name in ("image.lock.json", "Dockerfile", "build.sh")]
    if any(not path.is_file() or any(parent.is_symlink() for parent in (path, *path.parents)
            if parent.is_relative_to(root)) for path in paths):
        raise ValueError("CI runtime inputs must be ordinary source-owned files")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate CI runtime lock key")
            result[key] = value
        return result
    record = json.loads(paths[0].read_bytes(), object_pairs_hook=unique)
    keys = {"schema_version", "image", "base_image", "platform", "dockerfile_sha256", "build_script_sha256", "builder"}
    if (not isinstance(record, dict) or set(record) != keys or type(record["schema_version"]) is not int
            or record["schema_version"] != 1 or record["base_image"] != PLAYWRIGHT_BASE_IMAGE
            or record["platform"] != "linux/amd64" or not isinstance(record["image"], str)
            or re.fullmatch(r"registry[.]gitlab[.]com/bijux-oss/bijux-std/ci-runtime@sha256:[a-f0-9]{64}", record["image"]) is None):
        raise ValueError("CI runtime lock has an unsupported identity or source")
    if (record["dockerfile_sha256"] != hashlib.sha256(paths[1].read_bytes()).hexdigest()
            or record["build_script_sha256"] != hashlib.sha256(paths[2].read_bytes()).hexdigest()
            or paths[1].read_text().splitlines()[0] != "FROM " + PLAYWRIGHT_BASE_IMAGE):
        raise ValueError("CI runtime recipe differs from its verified image lock")
    builder = record["builder"]
    if (not isinstance(builder, dict) or set(builder) != {"project_id", "pipeline_id", "job_id", "source_sha", "image"}
            or type(builder["project_id"]) is not int or builder["project_id"] != 88948041
            or any(type(builder[key]) is not int or builder[key] <= 0 for key in ("pipeline_id", "job_id"))
            or not isinstance(builder["source_sha"], str) or re.fullmatch(r"[a-f0-9]{40}", builder["source_sha"]) is None
            or not isinstance(builder["image"], str) or re.fullmatch(r"moby/buildkit@sha256:[a-f0-9]{64}", builder["image"]) is None
            or re.findall(r"^builder_image='([^']+)'$", paths[2].read_text(), re.M) != [builder["image"]]):
        raise ValueError("CI runtime lock does not bind its actual canonical builder")
    return record["image"]


PLAYWRIGHT_IMAGE = runtime_image()


def literal(path: Path, name: str):
    declarations = [node.value for node in ast.parse(path.read_text()).body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == name
                            for target in node.targets)]
    if len(declarations) != 1:
        raise ValueError(f"Exactly one owned {name} declaration is required")
    return ast.literal_eval(declarations[0])


def job_contracts(root: Path = ROOT) -> dict:
    execution = root / "tests/bijux-docs/execution"
    engines = json.loads((execution / "browser_partitions.json").read_text())["engines"]
    batches = json.loads((execution / "browser_ownership/registry.json").read_text())["batches"]
    catalogue = literal(root / "tests/bijux-docs/catalogue/execution.py", "GROUPS")
    catalogue_paths = literal(root / "tests/bijux-docs/catalogue/execution.py", "ARTIFACT_PATHS")
    renderers = literal(execution / "renderer_controls.py", "GROUPS")
    jobs = {}

    def add(name, operation, *, stage="validation", frontend=False, args=(), paths=(), needs=None):
        jobs[name] = dict(operation=operation, stage=stage, frontend=frontend,
                          args=list(args), paths=list(paths), needs=needs,
                          image="ruby:3.3.12-bookworm" if operation in {"standard", "contracts"} else PLAYWRIGHT_IMAGE)

    add("std / input plan", "plan", stage="planning", paths=["artifacts/bijux-docs/input-plan"])
    add("std / standard", "standard")
    add("std / contracts", "contracts", args=[0])
    for index in range(1, CONTRACT_PARTITION_COUNT):
        add(f"std / contracts / partition {index + 1}", "contracts", args=[index])
    add("policy / canonical review", "policy")
    plan = ["std / input plan"]
    for group in catalogue:
        add("std / catalogue " + group, "catalogue", frontend=True, args=[group], needs=plan,
            paths=["artifacts/bijux-docs/catalogue/reports/" + group]
                  + ["artifacts/" + path for path in catalogue_paths[group]])
    add("std / publication commands", "commands", frontend=True, needs=plan,
        paths=["artifacts/bijux-docs/publication-commands"])
    for group in renderers:
        add("std / renderer controls / " + group, "renderer", frontend=True,
            args=[group], needs=plan, paths=["artifacts/bijux-docs/renderer-controls/" + group])
    fixture_paths = ["browser-fixtures.tar.gz", "browser-fixtures.sha256", "browser-packages.tar.gz",
                     "browser-packages.json", "producer-envelope.json", "inventories", "renderer-source-observation.json"]
    add("std / navigation fixtures", "fixtures", stage="fixtures", frontend=True, needs=plan,
        paths=["artifacts/bijux-docs/" + path for path in fixture_paths])
    fixture = ["std / navigation fixtures"]
    for batch in batches:
        for engine in engines:
            add(f"std / navigation {batch} / {engine}", "browser", stage="browsers",
                frontend=True, args=[batch, engine], needs=fixture,
                paths=["artifacts/bijux-docs/shards"])
    add("std / persisted native reader / chromium", "persisted", stage="browsers",
        frontend=True, needs=fixture, paths=["artifacts/bijux-docs/persisted-reader"])
    for engine in engines:
        add("std / frontend fault controls / " + engine, "browser-faults", stage="browsers",
            frontend=True, args=[engine], needs=fixture,
            paths=["artifacts/bijux-docs/frontend-faults/" + engine])
    add("std / frontend public artifact fault controls", "public-faults", frontend=True,
        needs=plan, paths=["artifacts/bijux-docs/frontend-faults/public"])
    add("std / navigation", "navigation", stage="qualification", frontend=True,
        paths=["artifacts/bijux-docs/navigation-qualification.json",
               "artifacts/bijux-docs/frontend-faults/qualification.json"])
    add("std / report", "report", stage="acceptance", paths=["artifacts/gitlab/acceptance", "artifacts/bijux-checks"])
    return jobs


def compose(root: Path = ROOT) -> dict:
    pipeline = {
        "workflow": {"rules": [
            {"if": '$CI_SERVER_URL != "https://gitlab.com" || $CI_PROJECT_ID != "88948041" || $CI_PROJECT_PATH != "bijux-oss/bijux-std"', "when": "never"},
            {"if": '$CI_PIPELINE_SOURCE == "merge_request_event"'},
            {"if": '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS', "when": "never"},
            {"if": '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH'},
            {"if": '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_TAG && $CI_COMMIT_REF_PROTECTED == "true"'},
            {"if": '$CI_PIPELINE_SOURCE == "web" || $CI_PIPELINE_SOURCE == "schedule"'},
            {"when": "never"},
        ]},
        "stages": ["planning", "validation", "fixtures", "browsers", "qualification", "acceptance", "publication"],
        "variables": {"GIT_DEPTH": "0", "PYTHONDONTWRITEBYTECODE": "1", "VERIFICATION_MODE": "full",
                      "EXPECTED_FRONTEND": "true", "FF_SCRIPT_SECTIONS": "true"},
        "default": {"tags": ["saas-linux-medium-amd64"], "interruptible": True},
    }
    for name, contract in job_contracts(root).items():
        job = {
            "stage": contract["stage"], "image": contract["image"],
            "timeout": "3 minutes" if contract["frontend"] else "30 minutes" if contract["operation"] == "contracts" else "20 minutes",
            "before_script": [] if contract["image"] == PLAYWRIGHT_IMAGE else ["apt-get update && apt-get install --yes --no-install-recommends python3 python3-venv python3-yaml git make curl ca-certificates perl shellcheck xz-utils jq"],
            "script": ["python3 -B shared/bijux-gitlab/execute.py --job " + shlex.quote(name)],
            "artifacts": {"when": "always", "expire_in": "1 year" if contract["operation"] == "report" else "14 days",
                          "paths": contract["paths"] + ["artifacts/gitlab/jobs/$CI_JOB_ID/"]},
        }
        if contract["needs"] is not None:
            job["needs"] = contract["needs"]
        else:
            job["dependencies"] = []
        if contract["operation"] == "report":
            job["when"] = "always"
        pipeline[name] = job
    pipeline["publish / mirrors"] = {
        "stage": "publication", "needs": ["std / report"],
        "rules": [{"if": '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH && $CI_COMMIT_REF_PROTECTED == "true" && $BIJUX_MIRROR_PUBLICATION_READY == "true"'}, {"when": "never"}],
        "variables": {"BIJUX_PARENT_PIPELINE_ID": "$CI_PIPELINE_ID"},
        "trigger": {"include": [{"local": "shared/bijux-gitlab/ci/publication.yml"}], "strategy": "depend"},
        "interruptible": False,
    }
    return pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = ROOT / "shared/bijux-gitlab/ci/standards.yml"
    body = json.dumps(compose(), indent=2) + "\n"
    if args.check:
        if path.read_text() != body:
            raise SystemExit("GitLab standards include differs from the owned job contracts")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


if __name__ == "__main__":
    main()
