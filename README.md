# bijux-iac

This repo is where we govern Bijux GitHub settings from one place.

Workspace policy baseline: [`/Users/bijan/bijux/README.md`](/Users/bijan/bijux/README.md)

`bijux-iac` owns the live GitHub control plane for the Bijux repository
family. The repo stays narrow on purpose: GitHub settings live here, while
repo-local shared content stays in `bijux-std`.

## What this repo is

This is the control-plane repository for live GitHub governance.

It is the place where repository inventory, Terraform inputs, validation
scripts, and GitHub-admin policy surfaces are defined so the public Bijux repos
can be governed from one source of truth.

## What lives here

- `inventory/`
  Repository inventory, classes, and per-repo governance inputs.
- `infra/github/main-branch-protection/`
  Terraform for the managed `main` branch protection surface.
- `scripts/`
  Validation and rendering scripts for repo inventory and Terraform inputs.
- `makes/`
  Repo-owned make targets for local validation and CI use.
- `.github`
  Managed GitHub workflows and standards content consumed from `bijux-std`.

## What does not live here

Do not use `bijux-iac` for:

- synced repo-local shared standards content
- product or domain code
- repo-specific docs content
- one-off local automation that belongs to only one consumer repo

So the split is:

- `bijux-iac` owns live GitHub admin governance
- `bijux-std` owns synced repo content and shared standards files

## How this repo works

The normal flow is straightforward:

1. define or change GitHub governance inputs here
2. validate the inventory and rendered Terraform inputs locally
3. run Terraform validation for the managed surface
4. apply the change through the GitHub API with the governed workflow or admin path

That keeps live GitHub policy centralized instead of being scattered through
consumer repos.

## What we manage here now

- `main` branch protection for the public Bijux repos listed in
  [`inventory/repositories.json`](inventory/repositories.json)

`bijux-genomics` is excluded on purpose for now because it is still private.
When that repo is ready for a public release path, it should move under the
same control plane here.

## Relationship to bijux-std

`bijux-iac` and `bijux-std` are close, but they are not the same job.

- `bijux-iac` owns live GitHub settings applied through the GitHub API
- `bijux-std` owns repo-local shared content that gets synced into repos and
  checked in CI

`bijux-iac` governs `bijux-std`, and `bijux-std` can still be consumed here as
managed shared content.

## Main commands

### Validate repository inventory

```bash
python3 scripts/validate_repo_inventory.py
```

### Check rendered Terraform inputs

```bash
python3 scripts/render_main_branch_protection_tfvars.py --check
```

### Validate the managed Terraform surface

```bash
terraform -chdir=infra/github/main-branch-protection fmt -check -recursive
terraform -chdir=infra/github/main-branch-protection init -backend=false
terraform -chdir=infra/github/main-branch-protection validate
```

## Required secret

Set this secret on `bijux-iac`:

- `GH_ADMIN_TOKEN`
  Token with repository administration permission for the managed Bijux
  repositories.

## License

This repository is licensed under the MIT License. Copyright 2026 Bijan
Mousavi <bijan@bijux.io>. See [`LICENSE`](LICENSE).
