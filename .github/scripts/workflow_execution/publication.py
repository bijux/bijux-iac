"""Manual publication API selection and local reusable caller admission."""
from __future__ import annotations

import copy
from .events import normalize_workflow_events
from .schema import WorkflowExecutionPolicy
from .refs import project_publication_refs


def manual_publication_entrypoints(policy: WorkflowExecutionPolicy | None) -> set[str]:
    if policy is None:
        return set()
    return {identity for identity, definition in policy.get("publication_entrypoints", {}).items()
            if definition["mode"] == "manual-only"}


def requires_publication_projection(policy: WorkflowExecutionPolicy | None) -> bool:
    return bool(manual_publication_entrypoints(policy))


def project_publication_entrypoints(workflow_id: str, document: dict, policy: WorkflowExecutionPolicy | None) -> dict:
    projected = copy.deepcopy(document)
    if workflow_id not in manual_publication_entrypoints(policy):
        return projected
    events = normalize_workflow_events(workflow_id, document)
    if "workflow_dispatch" not in events or set(events) - {"workflow_dispatch", "workflow_call"}:
        raise ValueError(f"{workflow_id} must expose its canonical dispatch/call publication API")
    # Dispatch input/help/default identity and every job remain source-owned.
    events.pop("workflow_call", None)
    projected["on"] = events
    return project_publication_refs(workflow_id, projected, policy)


def validate_publication_calls(documents: dict[str, dict], policy: WorkflowExecutionPolicy | None) -> None:
    manual = manual_publication_entrypoints(policy)
    if not manual:
        return
    forbidden = {f"./.github/workflows/{identity}.yml" for identity in manual}
    for path, document in documents.items():
        jobs = document.get("jobs")
        if not isinstance(jobs, dict):
            raise ValueError(f"{path} caller jobs must be an object")
        for identity, job in jobs.items():
            if not isinstance(job, dict):
                raise ValueError(f"{path} caller job {identity} must be an object")
            target = job.get("uses")
            if "uses" in job and (not isinstance(target, str) or not target.strip()):
                raise ValueError(f"{path} caller job {identity} uses must be a workflow reference")
            if isinstance(target, str) and target.strip().split("@", 1)[0] in forbidden:
                raise ValueError(f"{path} job {identity} calls manual-only publication entrypoint {target}")
