# GitHub Main Branch Governance

Terraform source for PR-only governance on repositories managed by `bijux-iac`.

## Managed repositories

Repository targets are rendered from
[`inventory/repositories.json`](../../../inventory/repositories.json) into
[`terraform.auto.tfvars.json`](terraform.auto.tfvars.json) by
[`scripts/render_main_branch_protection_tfvars.py`](../../../scripts/render_main_branch_protection_tfvars.py).

## Main branch policy

Two enforcement engines are supported during the rollout:

- `branch_protection`: legacy protection for repositories that still use direct GitHub branch protection.
- `ruleset`: repository rulesets with explicit required status checks and approval policy gates.

Ruleset-managed repositories use this baseline:

- pull request required
- zero built-in approving reviews
- required checks: `policy / github`, `policy / pr approval`, `std / standard`, `std / report`
- repository-specific required checks may be added on top of the baseline
- force push disabled
- branch deletion disabled
- conversation resolution required

Legacy branch-protection repositories keep the older direct review-count enforcement until they are migrated.

## CI flow

- `.github/workflows/github-governance-plan.yml` on pull requests
- `.github/workflows/github-governance-apply.yml` on `main` and manual dispatch

CI imports current legacy branch protection resources and repository rulesets before plan/apply so governance can run without a separate persistent Terraform backend. The import script reads the same repository list as Terraform to avoid configuration drift.

## Required secret

Set repository secret on `bijux-iac`:

- `GH_ADMIN_TOKEN`: token with repository administration permission for both managed repositories.
