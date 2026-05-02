#!/usr/bin/env bash
set -euo pipefail

readonly TFVARS_PATH="terraform.auto.tfvars.json"
readonly IMPORT_LOG_PATH="$(mktemp)"

cleanup() {
  rm -f "${IMPORT_LOG_PATH}"
}
trap cleanup EXIT

mapfile -t legacy_repos < <(
  IMPORT_TFVARS_PATH="${TFVARS_PATH}" python3 - <<'PY'
import json
import os

with open(os.environ["IMPORT_TFVARS_PATH"], encoding="utf-8") as handle:
    data = json.load(handle)

for repo in data.get("legacy_branch_protection_repositories", []):
    print(repo)
PY
)

mapfile -t ruleset_repos < <(
  IMPORT_TFVARS_PATH="${TFVARS_PATH}" python3 - <<'PY'
import json
import os

with open(os.environ["IMPORT_TFVARS_PATH"], encoding="utf-8") as handle:
    data = json.load(handle)

for repo in data.get("ruleset_repositories", []):
    print(repo)
PY
)

lookup_ruleset_id() {
  local repo="$1"
  RULESET_REPO="${repo}" TF_VAR_GITHUB_TOKEN="${TF_VAR_github_token}" python3 - <<'PY'
import json
import os
import urllib.request

repo = os.environ["RULESET_REPO"]
token = os.environ["TF_VAR_GITHUB_TOKEN"]
request = urllib.request.Request(
    f"https://api.github.com/repos/bijux/{repo}/rulesets",
    headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    },
)
with urllib.request.urlopen(request) as response:
    rulesets = json.load(response)

for ruleset in rulesets:
    if ruleset.get("target") != "branch":
        continue
    if ruleset.get("name") not in {"main-pr-only-admin-bypass", "main-branch-protection"}:
        continue
    print(ruleset["id"])
    raise SystemExit(0)
PY
}

for repo in "${legacy_repos[@]}"; do
  if [[ -z "${repo}" ]]; then
    continue
  fi
  resource_address="github_branch_protection.main[\"${repo}\"]"
  import_id="${repo}:main"

  echo "Importing ${import_id}"
  if terraform import -input=false "${resource_address}" "${import_id}" >"${IMPORT_LOG_PATH}" 2>&1; then
    continue
  fi

  if grep -q "Cannot import non-existent remote object" "${IMPORT_LOG_PATH}" \
    || grep -q "could not find a branch protection rule with the pattern 'main'" "${IMPORT_LOG_PATH}"; then
    echo "No existing branch protection for ${import_id}; Terraform will create it."
    continue
  fi

  cat "${IMPORT_LOG_PATH}" >&2
  exit 1
done

for repo in "${ruleset_repos[@]}"; do
  if [[ -z "${repo}" ]]; then
    continue
  fi

  ruleset_id="$(lookup_ruleset_id "${repo}" || true)"
  if [[ -z "${ruleset_id}" ]]; then
    echo "No existing repository ruleset for ${repo}; Terraform will create it."
    continue
  fi

  resource_address="github_repository_ruleset.main[\"${repo}\"]"
  import_id="${repo}:${ruleset_id}"

  echo "Importing ${import_id}"
  if terraform import -input=false "${resource_address}" "${import_id}" >"${IMPORT_LOG_PATH}" 2>&1; then
    continue
  fi

  if grep -q "Cannot import non-existent remote object" "${IMPORT_LOG_PATH}"; then
    echo "No existing repository ruleset for ${repo}; Terraform will create it."
    continue
  fi

  cat "${IMPORT_LOG_PATH}" >&2
  exit 1
done
