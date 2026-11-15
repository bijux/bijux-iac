"""Run an admitted native manual request; the default operation is preflight."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import uuid

from scripts.inventory.repositories import ROOT
from scripts.publication.controller import PublicationFailure, Request, execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--operation",
        choices=["verify-credential", "preflight", "dispatch"],
        help="explicit operation; otherwise PUBLICATION_OPERATION or preflight",
    )
    arguments = parser.parse_args()
    environment = dict(os.environ)
    if arguments.operation is not None:
        environment["PUBLICATION_OPERATION"] = arguments.operation
    try:
        receipt = execute(
            Request.from_environment(environment), root=ROOT, environment=environment
        )
    except Exception as error:
        receipt = (
            {
                key: error.receipt[key]
                for key in (
                    "version",
                    "authority",
                    "status",
                    "error_type",
                    "remote_writes",
                    "remote_write_attempted",
                    "dispatch",
                    "receipt_retention_failed",
                    "failed_stage",
                )
                if key in error.receipt
            }
            if isinstance(error, PublicationFailure)
            else {
                "version": 1,
                "authority": "manual-publication-request",
                "status": "blocked",
                "error_type": type(error).__name__,
            }
        )
        folder = ROOT / "artifacts/publication/control"
        try:
            if any(
                path.is_symlink()
                for path in (folder, *folder.parents)
                if path.is_relative_to(ROOT)
            ):
                raise OSError("Unsafe fallback receipt destination")
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / ("blocked-" + uuid.uuid4().hex + ".json")
            with path.open("x") as stream:
                json.dump(receipt, stream, indent=2)
                stream.write("\n")
        except Exception:
            receipt["receipt_retention_failed"] = True
        print(json.dumps(receipt))
        return 1
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "operation": receipt["operation"],
                "remote_writes": receipt["remote_writes"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
