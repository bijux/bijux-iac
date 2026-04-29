# GitHub Main Branch Protection Governance

Terraform source for PR-only protection on repositories managed by `bijux-iac`.

## Managed repositories

Repository targets are rendered from
[`inventory/repositories.json`](../../../inventory/repositories.json) into
[`terraform.auto.tfvars.json`](terraform.auto.tfvars.json) by
[`scripts/render_main_branch_protection_tfvars.py`](../../../scripts/render_main_branch_protection_tfvars.py).

## Main branch policy

- pull request required
- one approving review required
- admin bypass disabled for repositories listed in `enforce_admins_repositories`
- force push disabled
- branch deletion disabled
- conversation resolution required

Current admin-enforced repositories:

- `bijux-iac`
- `bijux-std`
- `bijux.github.io`
- `bijux-masterclass`

## CI flow

- `.github/workflows/github-governance-plan.yml` on pull requests
- `.github/workflows/github-governance-apply.yml` on `main` and manual dispatch

CI imports current branch protection resources before plan/apply so governance can run without a separate persistent Terraform backend. The import script reads the same repository list as Terraform to avoid configuration drift.

## Required secret

Set repository secret on `bijux-iac`:

- `GH_ADMIN_TOKEN`: token with repository administration permission for both managed repositories.
