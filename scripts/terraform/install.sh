#!/usr/bin/env bash
# Install the governed Terraform version into the repository artifact boundary.
set -euo pipefail
repo_root="$(git rev-parse --show-toplevel)"
tools="${repo_root}/artifacts/tools"
version=1.16.5
case "$(uname -s):$(uname -m)" in
  Linux:x86_64) platform=linux_amd64 ;;
  Linux:aarch64) platform=linux_arm64 ;;
  Darwin:arm64) platform=darwin_arm64 ;;
  *) echo 'unsupported Terraform validation platform' >&2; exit 1 ;;
esac
mkdir -p "${tools}"
archive="terraform_${version}_${platform}.zip"
source="https://releases.hashicorp.com/terraform/${version}"
curl --fail --silent --show-error --location "${source}/${archive}" -o "${tools}/${archive}"
curl --fail --silent --show-error --location "${source}/terraform_${version}_SHA256SUMS" -o "${tools}/terraform.sha256"
python3 -B - "${tools}" "${archive}" <<'PY'
import hashlib
from pathlib import Path
import sys
root, archive = Path(sys.argv[1]), sys.argv[2]
rows = [line.split()[0] for line in (root / 'terraform.sha256').read_text().splitlines()
        if line.endswith('  ' + archive)]
if len(rows) != 1 or hashlib.sha256((root / archive).read_bytes()).hexdigest() != rows[0]:
    raise SystemExit('Terraform archive digest mismatch')
PY
unzip -o "${tools}/${archive}" terraform -d "${tools}"
"${tools}/terraform" version
