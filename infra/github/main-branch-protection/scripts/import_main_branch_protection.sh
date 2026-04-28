#!/usr/bin/env bash
set -euo pipefail

readonly TFVARS_PATH="terraform.auto.tfvars.json"
readonly IMPORT_LOG_PATH="$(mktemp)"

cleanup() {
  rm -f "${IMPORT_LOG_PATH}"
}
trap cleanup EXIT

mapfile -t repos < <(
  IMPORT_TFVARS_PATH="${TFVARS_PATH}" python3 - <<'PY'
import json
import os

with open(os.environ["IMPORT_TFVARS_PATH"], encoding="utf-8") as handle:
    data = json.load(handle)

for repo in data.get("protected_repositories", []):
    print(repo)
PY
)

for repo in "${repos[@]}"; do
  if [[ -z "${repo}" ]]; then
    continue
  fi
  resource_address="github_branch_protection.main[\"${repo}\"]"
  import_id="${repo}:main"

  echo "Importing ${import_id}"
  if terraform import -input=false "${resource_address}" "${import_id}" >"${IMPORT_LOG_PATH}" 2>&1; then
    continue
  fi

  if grep -q "Cannot import non-existent remote object" "${IMPORT_LOG_PATH}"; then
    echo "No existing branch protection for ${import_id}; Terraform will create it."
    continue
  fi

  cat "${IMPORT_LOG_PATH}" >&2
  exit 1
done
