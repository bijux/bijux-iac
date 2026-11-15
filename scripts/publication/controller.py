"""Coordinate existing manual publishers after independent native IaC admission."""

from __future__ import annotations

import base64
from contextlib import chdir
from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import ModuleType

from scripts.inventory.publication import (
    documentation_destination,
    validate_request,
    validate_publisher,
    workflow_policy,
)
from scripts.inventory.repositories import validated_inventory
from scripts.publication.credentials import (
    ACTOR,
    ACTOR_ID,
    APP_ID,
    installation_client,
    require,
)


class PublicationFailure(ValueError):
    """Carry only the sanitized outcome across the CLI exception boundary."""

    def __init__(self, receipt):
        self.receipt = receipt
        super().__init__("Manual publication request failed")


@dataclass(frozen=True)
class Request:
    operation: str
    repository: str
    workflow: str
    commit: str
    tag: str = ""
    candidate_run: str = ""
    source_pipeline_id: int | None = None

    @classmethod
    def from_environment(cls, environment):
        pipeline = environment.get("PUBLICATION_TARGET_PIPELINE_ID", "")
        require(
            not pipeline
            or isinstance(pipeline, str)
            and re.fullmatch(r"[1-9][0-9]*", pipeline),
            "Native target pipeline ID must be a positive integer",
        )
        return cls(
            environment.get("PUBLICATION_OPERATION", "preflight"),
            *(
                environment.get("PUBLICATION_TARGET_" + key, "")
                for key in ("REPOSITORY", "WORKFLOW", "COMMIT", "TAG", "CANDIDATE_RUN")
            ),
            source_pipeline_id=int(pipeline) if pipeline else None,
        )

    def validate(self, inventory):
        require(
            self.operation in {"verify-credential", "preflight", "dispatch"},
            "Explicit manual operation is unsupported",
        )
        require(
            all(
                isinstance(value, str)
                for value in (
                    self.repository,
                    self.workflow,
                    self.commit,
                    self.tag,
                    self.candidate_run,
                )
            ),
            "Publication request fields must be strings",
        )
        validate_request(
            inventory,
            self.repository,
            self.workflow,
            self.commit,
            self.tag,
            require_published=self.operation != "verify-credential",
            candidate_run=self.candidate_run,
        )
        if self.repository in {"bijux-std", "bijux-iac"}:
            require(
                type(self.source_pipeline_id) is int and self.source_pipeline_id > 0,
                "Migrated publication source requires its actual native pipeline ID",
            )
        else:
            require(
                self.source_pipeline_id is None,
                "Legacy publication source requires an empty native pipeline ID",
            )


def admit_legacy(root, client, repository, workflow, commit, tag, trusted):
    """Bind explicit readers to the unchanged accepted publisher policy helper."""
    policy = workflow_policy()
    live = client.read(
        f"repos/bijux/{repository}/contents/.github/workflows/{workflow}.yml?ref={commit}"
    )
    document = policy.parse_workflow(
        base64.b64decode(live["content"]), workflow + ".yml"
    )
    validate_publisher(policy, workflow, document)
    path = root / ".bijux/shared/bijux-gh/scripts/publication_admission.py"
    require(
        path.is_file() and not path.is_symlink(),
        "Accepted publisher helper is unavailable",
    )
    module = ModuleType("bijux_selected_publisher_admission")
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    module.api = client.read

    def check_runs(name, sha):
        pages = client.pages(f"repos/{name}/commits/{sha}/check-runs?per_page=100")
        require(
            all(
                isinstance(page, dict) and isinstance(page.get("check_runs"), list)
                for page in pages
            ),
            "Publisher check inventory is malformed",
        )
        return [run for page in pages for run in page["check_runs"]]

    def associated_pulls(name, sha):
        pages = client.pages(f"repos/{name}/commits/{sha}/pulls?per_page=100")
        require(
            all(isinstance(page, list) for page in pages),
            "Publisher pull inventory is malformed",
        )
        return [pull for page in pages for pull in page]

    module.check_runs, module.associated_pulls = check_runs, associated_pulls
    planned_dispatch = {
        "PUBLICATION_REPOSITORY": "bijux/" + repository,
        "PUBLICATION_EVENT": "workflow_dispatch",
        "PUBLICATION_REF": "refs/heads/main",
        "PUBLICATION_ACTOR": ACTOR,
        "PUBLICATION_TRIGGERING_ACTOR": ACTOR,
        "PUBLICATION_ACTOR_ID": str(ACTOR_ID),
        "PUBLICATION_CONTROLLER_ACTOR_ID": trusted,
        "PUBLICATION_COMMIT": commit,
        "PUBLICATION_RUN_SHA": commit,
        "PUBLICATION_WORKFLOW": workflow,
        "PUBLICATION_TAG": tag,
    }
    # This qualifies the downstream request contract. Native controller facts
    # remain separate; the eventual publisher rechecks its real event and actor.
    with chdir(root):
        return module.admit(planned_dispatch)


def default_public_reader(root, path):
    from scripts.publication.native import PublicRead, load_provider

    return PublicRead(load_provider(root))(path)


def retain_receipt(root, receipt):
    native = receipt.get("controller", {})
    pipeline, job = native.get("pipeline_id"), native.get("job_id")
    require(
        type(pipeline) is int and pipeline > 0 and type(job) is int and job > 0,
        "Receipt requires the admitted actual controller IDs",
    )
    folder = root / "artifacts/publication/control"
    require(
        not any(
            path.is_symlink()
            for path in (folder, *folder.parents)
            if path.is_relative_to(root)
        ),
        "Publication receipt destination must be an owned ordinary path",
    )
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{pipeline}-{job}.json"
    require(
        not path.is_symlink()
        and (not path.exists() or path.is_file() and path.stat().st_nlink == 1),
        "Publication receipt path is unsafe",
    )
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")


def execute(
    request,
    *,
    root,
    environment,
    controller_admitter=None,
    source_admitter=None,
    public_reader=None,
    client_factory=installation_client,
    legacy_admitter=admit_legacy,
    retain=None,
):
    root = Path(root).resolve()
    public_reader = public_reader or (lambda path: default_public_reader(root, path))
    if controller_admitter is None or source_admitter is None:
        from scripts.publication.native import admit_controller, admit_source

        controller_admitter = controller_admitter or admit_controller
        source_admitter = source_admitter or admit_source
    retain = retain or (lambda receipt: retain_receipt(root, receipt))
    receipt = {
        "version": 1,
        "authority": "manual-publication-request",
        "status": "blocked",
        "remote_writes": False,
    }
    attempted = False
    stage = "controller-admission"
    try:
        require(
            environment.get("CI_DEBUG_TRACE", "false").lower()
            in {"false", "0", "f", ""},
            "Publication refuses debug tracing",
        )
        controller = controller_admitter(root, environment)
        require(
            isinstance(controller, dict) and controller.get("status") == "admitted",
            "Native controller admission is required",
        )
        receipt["controller"] = controller
        stage = "request-validation"
        inventory = validated_inventory()
        request.validate(inventory)
        receipt.update(
            operation=request.operation,
            requested_repository=request.repository,
            requested_commit=request.commit,
            workflow=request.workflow,
            release_tag=request.tag,
        )
        migrated = request.repository in {"bijux-std", "bijux-iac"}
        stage = "source-admission"
        source = (
            source_admitter(
                root, request.repository, request.commit, request.source_pipeline_id
            )
            if migrated
            else None
        )
        if migrated:
            require(
                isinstance(source, dict) and source.get("status") == "admitted",
                "Native publication source admission is required",
            )
        if source is not None:
            receipt["requested_source"] = source
        stage = "destination-selection"
        route = (
            documentation_destination(inventory, request.repository)
            if request.workflow == "deploy-docs"
            else {"repository": request.repository, "path": None}
        )
        target = route["repository"]
        destination_commit = (
            request.commit
            if target == request.repository
            else public_reader(f"repos/bijux/{target}/commits/main").get("sha")
        )
        require(
            isinstance(destination_commit, str)
            and re.fullmatch(r"[a-f0-9]{40}", destination_commit),
            "Publisher destination requires an immutable current main SHA",
        )
        receipt["destination"] = {
            "repository": target,
            "commit": destination_commit,
            "path": route["path"],
        }
        receipt["status"] = "operation-not-completed"
        stage = "receipt"
        retain(receipt)
        stage = "credential"
        require(
            environment.get("BIJUX_PUBLICATION_APP_ID") == str(APP_ID)
            and environment.get("BIJUX_PUBLICATION_ACTOR_ID") == str(ACTOR_ID),
            "Existing dispatch App and actor IDs are required",
        )
        installation = environment.get("BIJUX_PUBLICATION_INSTALLATION_ID", "")
        require(
            isinstance(installation, str)
            and re.fullmatch(r"[1-9][0-9]*", installation),
            "Explicit dispatch installation ID is required",
        )
        client = client_factory(
            target,
            environment.get("BIJUX_PUBLICATION_APP_PRIVATE_KEY", ""),
            installation_id=int(installation),
        )
        require(
            client.repository == target,
            "Credential destination differs from the admitted publisher",
        )
        trusted = client.read(
            f"repos/bijux/{target}/actions/variables/BIJUX_PUBLICATION_ACTOR_ID"
        ).get("value")
        identity = client.read("users/" + ACTOR)
        require(
            trusted == str(ACTOR_ID)
            and identity.get("type") == "Bot"
            and type(identity.get("id")) is int
            and identity["id"] == ACTOR_ID
            and identity.get("login") == ACTOR,
            "Publisher trust differs from the existing dispatch App actor",
        )
        if request.operation == "verify-credential":
            metadata = client.read(f"repos/bijux/{target}")
            require(
                metadata.get("full_name") == "bijux/" + target
                and metadata.get("default_branch") == "main",
                "Publisher repository identity differs",
            )
            for endpoint, key in [
                (f"commits/{destination_commit}/check-runs?per_page=1", "check_runs"),
                ("actions/workflows?per_page=1", "workflows"),
                ("actions/variables?per_page=1", "variables"),
            ]:
                require(
                    isinstance(
                        client.read(f"repos/bijux/{target}/" + endpoint).get(key), list
                    ),
                    "Publisher credential reads are unavailable",
                )
            receipt.update(
                status="credential-verified",
                required_reads_verified=True,
                dispatch_write_permission_tested=False,
            )
        else:
            stage = "publisher-admission"
            receipt["destination_admission"] = legacy_admitter(
                root,
                client,
                target,
                request.workflow,
                destination_commit,
                request.tag,
                trusted,
            )
            if request.workflow == "release-npm":
                from scripts.execution.publication import npm_candidate

                receipt["npm_candidate"] = npm_candidate(
                    request.repository,
                    request.commit,
                    candidate_run=request.candidate_run,
                    reader=client.read,
                )
            receipt["status"] = "admitted"
        # Requalify actual native ownership after credential work, not only the
        # mutable refs. A later retry or changed bridge invalidates this request.
        stage = "ownership-refresh"
        require(
            controller_admitter(root, environment) == controller,
            "Native controller ownership changed",
        )
        if migrated:
            require(
                source_admitter(
                    root, request.repository, request.commit, request.source_pipeline_id
                )
                == source,
                "Native publication source ownership changed",
            )
        require(
            client.read(f"repos/bijux/{target}/commits/main").get("sha")
            == destination_commit,
            "Publisher destination main changed",
        )
        stage = "receipt"
        retain(receipt)
        if request.operation == "dispatch":
            inputs = {"accepted_commit": destination_commit}
            if request.workflow != "deploy-docs":
                inputs["release_tag"] = request.tag
            if request.workflow == "release-npm":
                inputs["candidate_run_id"] = str(receipt["npm_candidate"]["run_id"])
            receipt["status"] = "dispatching"
            receipt["remote_write_attempted"] = True
            receipt["remote_writes"] = None
            retain(receipt)
            stage = "dispatch"
            attempted = True
            receipt["dispatch"] = client.dispatch(request.workflow, inputs)
            receipt.update(status="dispatched", remote_writes=True)
        stage = "receipt"
        retain(receipt)
        return receipt
    except Exception as error:
        acknowledged = attempted and isinstance(receipt.get("dispatch"), dict)
        if acknowledged:
            identifier = receipt["dispatch"].get("workflow_run_id")
            acknowledged = type(identifier) is int and identifier > 0
        receipt.update(
            status=(
                "dispatch-receipt-failed"
                if acknowledged
                else "dispatch-failed" if attempted else "blocked"
            ),
            error_type=type(error).__name__,
            failed_stage=stage,
            remote_writes=True if acknowledged else None if attempted else False,
        )
        if acknowledged:
            receipt["receipt_retention_failed"] = True
        if not attempted and "remote_write_attempted" in receipt:
            receipt["remote_write_attempted"] = False
        if "controller" in receipt:
            try:
                retain(receipt)
            except Exception:
                receipt["receipt_retention_failed"] = True
        raise PublicationFailure(receipt) from None
