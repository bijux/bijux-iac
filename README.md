# bijux-iac

This repo is where we govern Bijux GitHub settings from one place.

Workspace policy baseline: [`/Users/bijan/bijux/README.md`](/Users/bijan/bijux/README.md)

Right now the live surface starts with `main` branch protection. More GitHub
admin surfaces should come here over time instead of being scattered inside the
other repos.

`bijux-iac` and `bijux-std` are close, but they are not the same job.

- `bijux-iac` is for live GitHub control-plane settings applied through the
  GitHub API with Terraform.
- `bijux-std` is for repository-local standards content that gets synced into
  repos and checked in CI.

So the split is simple:

- if it is a live repo/org setting, it belongs here
- if it is synced files inside repos, it belongs in `bijux-std`

`bijux-iac` governs `bijux-std`, and `bijux-std` can still be consumed here as
shared standards content.

## What we manage here now

- `main` branch protection for the public Bijux repos listed in
  [`inventory/repositories.json`](inventory/repositories.json)

`bijux-genomics` is excluded on purpose for now because it is still private.
When that repo is ready for a public release path, we turn it on here and let
it follow the same control plane.

## Local checks

```bash
python3 scripts/validate_repo_inventory.py
python3 scripts/render_main_branch_protection_tfvars.py --check
terraform -chdir=infra/github/main-branch-protection fmt -check -recursive
terraform -chdir=infra/github/main-branch-protection init -backend=false
terraform -chdir=infra/github/main-branch-protection validate
```

## Required secret

Set this secret on `bijux-iac`:

- `GH_ADMIN_TOKEN`: token with repository administration permission for the
  managed Bijux repositories
