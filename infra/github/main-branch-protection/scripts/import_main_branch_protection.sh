#!/usr/bin/env bash
set -euo pipefail

# Bash 3.2 and Python 3.11 suffice; discovery and logs are repository-owned.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
export PYTHONPYCACHEPREFIX="${repo_root}/artifacts/python/pycache"
cd "${repo_root}"
exec python3 -m scripts.terraform.imports
