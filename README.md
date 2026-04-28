# bijux-iac

GitHub infrastructure-as-code governance for Bijux repositories.

Workspace policy baseline: [`/Users/bijan/bijux/README.md`](/Users/bijan/bijux/README.md)

`bijux-iac` owns live GitHub control-plane settings that are enforced through
the GitHub API, starting with `main` branch protection. `bijux-std` remains the
source of truth for repository-local standards content such as managed workflow
files, templates, scripts, and sync checks.

## Responsibility split

- `bijux-iac`: live GitHub settings, rules, and repo governance applied through
  Terraform.
- `bijux-std`: synchronized in-repo standards content and validation.

`bijux-iac` governs `bijux-std`, and `bijux-std` may still be consumed as a
standards source inside `bijux-iac`.

## Current managed surface

- GitHub `main` branch protection for public Bijux repositories that are
  marked `enabled` in [`inventory/repositories.json`](inventory/repositories.json)
- `bijux-genomics` is intentionally excluded while it remains private; enable it
  from `bijux-iac` when the public release path is opened

Future GitHub governance surfaces should be added here rather than embedded in
consumer repositories.

## Local verification

```bash
python3 scripts/validate_repo_inventory.py
python3 scripts/render_main_branch_protection_tfvars.py --check
terraform -chdir=infra/github/main-branch-protection fmt -check -recursive
terraform -chdir=infra/github/main-branch-protection init -backend=false
terraform -chdir=infra/github/main-branch-protection validate
```

## Required secret

Set repository secret on `bijux-iac`:

- `GH_ADMIN_TOKEN`: token with repository administration permission for managed
  Bijux repositories
