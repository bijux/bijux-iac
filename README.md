# bijux-iac

`bijux-iac` is the live GitHub governance control plane for the Bijux
repository family. It turns a reviewed repository inventory into organization
settings and `main` branch rulesets, then audits GitHub to prove that the
declared policy is active.

The repository is intentionally narrow. It owns live administration; it does
not own product code, package release logic, or the shared files synchronized
into each repository.

## Why This Repository Exists

Repository settings are part of the production platform. If they are changed
manually, the family can drift in ways that are difficult to review or
reproduce: merge methods diverge, required checks disappear, stale branches
accumulate, or a renamed repository remains in an old policy list.

`bijux-iac` provides one reviewable path:

```mermaid
flowchart LR
    I["inventory/repositories.json"] --> V["Contract validation"]
    V --> S["GitHub repository settings"]
    V --> R["Rendered Terraform inputs"]
    R --> T["Repository rulesets"]
    S --> A["Live governance audit"]
    T --> A
```

Every write is derived from the committed inventory. Generated Terraform
inputs are checked into the repository so pull requests show the exact target
set before an apply can run.

## Ownership Boundaries

| Surface | Owner | Responsibility |
| --- | --- | --- |
| Live GitHub settings and rulesets | `bijux-iac` | Visibility, features, merge policy, branch deletion, sign-off policy, and `main` protection |
| Shared repository standards | `bijux-std` | Managed Make libraries, GitHub workflow sources, checks, documentation shell, generators, and checksums |
| Product behavior | Product repository | Domain code, package metadata, tests, release inputs, and product documentation |
| Portfolio website | `bijux.github.io` | Public landing site and links to published project documentation |

Managed content under `.bijux/shared/` and selected `.github/` paths is consumed
from the exact commit recorded in
[`.github/standards/bijux-std.sha`](.github/standards/bijux-std.sha). Those files
must be refreshed through the standards tooling, not edited locally.

## Governed Family

The inventory contains exactly twelve repositories: two foundations, two hubs,
four Rust products, and four Python products. Delivery state is
operational metadata: `published` means the public surface exists,
`planned` means it is deliberately not yet published, and `not-applicable`
means that repository does not own the surface.

| Repository | Role | Stack | Documentation | Packages |
| --- | --- | --- | --- | --- |
| `bijux-iac` | GitHub control plane | Terraform | Not applicable | Not applicable |
| `bijux-std` | Shared standards control plane | Make | Not applicable | Not applicable |
| `bijux.github.io` | Documentation hub | Docs | Published | Not applicable |
| `bijux-masterclass` | Learning hub | Docs | Published | Not applicable |
| `bijux-canon` | Product | Python | Published | Published |
| `bijux-proteomics` | Product | Python | Published | Published |
| `bijux-pollenomics` | Product | Python | Published | Published |
| `bijux-phylogenetics` | Product | Python | Published | Published |
| `bijux-core` | Product | Rust | Published | Published |
| `bijux-atlas` | Product | Rust | Published | Published |
| `bijux-gnss` | Product | Rust | Published | Published |
| `bijux-genomics` | Product | Rust | Planned | Planned |

Validation fails if a family member is missing, duplicated, renamed, assigned
the wrong stack, or given a delivery state that contradicts this contract.
This makes the `bijux-gnss` identity durable and prevents obsolete repository
names from re-entering the control plane.

Every entry uses the same `name`, `class`, `stack`, `delivery`, `settings`, and
`governance` shape, ordered by foundations, hubs, Rust products, and Python
products. Shared repository settings are declared once in
`repository_settings_defaults`. An explicit `settings: {}` inherits them;
nonempty objects declare only real differences. The four existing wiki overrides
remain visible. Overrides cannot weaken the common visibility, issues, merge,
branch-deletion, or sign-off contract, and restating a default is rejected.
Unknown or duplicate keys fail validation. The inventory validator's `--write`
option writes the canonical family order and formatting.

## Repository Layout

| Path | Purpose |
| --- | --- |
| [`inventory/repositories.json`](inventory/repositories.json) | Authoritative family, settings, delivery state, and ruleset inputs |
| [`scripts/inventory/`](scripts/inventory) | Family identity, canonical inventory formatting, and closed policy validation |
| [`scripts/github/`](scripts/github) | API reads, complete live audit, and bounded repository settings writes |
| [`scripts/terraform/`](scripts/terraform) | Deterministic ruleset inputs and authoritative imports |
| [`scripts/execution/`](scripts/execution) | Accepted-main preflight and application of the bound plan |
| [`infra/github/repository-rulesets/`](infra/github/repository-rulesets) | Locked Terraform module for the family’s main rulesets |
| [`tests/`](tests) | Offline contracts grouped by the same inventory, GitHub, Terraform, and execution boundaries |
| [`makes/`](makes) | Repository-owned composition of shared Make foundations |
| [`.bijux/shared/`](.bijux/shared) | Generated standards payload selected by capability |

## Governance Model

All managed repositories currently use an active ruleset targeting the default
branch. The baseline requires:

- pull requests for changes to `main`
- merge commits as the only merge method
- stale reviews dismissed after new pushes
- review conversations resolved before merge
- strict required status checks
- force pushes rejected
- branch deletion rejected

The baseline check contexts are:

- `policy / github`
- `policy / pr approval`
- `std / standard`
- `std / report`

Repository-specific checks may be added in the inventory. The current Python
release repositories also require `verification-ready` where that workflow is
available.

Merged pull-request branches are deleted automatically at the repository
settings layer. That setting does not weaken the ruleset prohibition against
deleting `main`.

## Change Flow

1. Edit [`inventory/repositories.json`](inventory/repositories.json).
2. Run `make test` to validate schema, family membership, delivery state, and
   generated Terraform parity.
3. If branch policy changed, regenerate the committed input:

   ```bash
   python3 -B -m scripts.terraform.render --write
   ```

4. Run the repository gates:

   ```bash
   make fmt
   make lint
   make ci
   ```

5. Open a pull request. The plan workflow validates the inventory, imports live
   ruleset state, and produces a Terraform plan without changing GitHub.
6. Merge only after required checks pass. Application is a separate manual
   dispatch on accepted `main`. Its serialized workflow completes inventory,
   settings discovery, imports, validation, producer checks, and a saved ruleset
   plan before changing any GitHub setting.
7. The workflow audits live settings and rulesets after apply. The same audit
   is available locally:

   ```bash
   make live-audit
   ```

The apply workflow uses no persistent Terraform backend. It imports live
resources into an ephemeral runner state on every execution. This avoids
committing or centrally storing state, but it makes the import step mandatory;
an import failure stops the apply rather than attempting an unowned write.

## Local Commands

Run commands from the repository root.

| Command | Purpose |
| --- | --- |
| `make help` | Show the supported repository interface |
| `make doctor` | Verify required local tools and artifact boundaries |
| `make test` | Run fast inventory, rendering, syntax, and family contracts |
| `make fmt` | Verify Terraform formatting without modifying source |
| `make lint` | Run contracts and Terraform initialization/validation |
| `make contract-tests` | Run network-free governance contracts used by standards CI |
| `make bijux-std-checks` | Verify managed content against the pinned `bijux-std` commit |
| `make ci` | Run the pull-request gate composition |
| `make live-audit` | Compare inventory with live GitHub settings and rulesets |

Generated providers, Python bytecode, reports, and other local output are
contained under `artifacts/`.
Local Terraform validation copies the governed module and committed provider
lock into `artifacts/terraform/module`. Initialization uses the lock read-only;
runtime state and plans stay in artifacts. Formatting checks the authored module.

## Prerequisites

Local validation requires:

- Python 3.11 or newer
- Bash
- Terraform 1.16.5
- GitHub CLI for live settings operations

The apply and live-audit paths require a GitHub token with repository
administration permission across the governed family. GitHub Actions reads it
from the `GOVERNANCE_TOKEN` secret in the `governance-apply` environment.
Configure that environment with a selected deployment branch rule matching only
`main`, and no tag rules. Keep administration credentials out of repository and
organization secrets available to this repository. In particular, move the
existing `GH_ADMIN_TOKEN` repository secret into the environment under the new
name and retire the repository copy after verifying the replacement. GitHub
cannot reveal an existing secret value; an administrator must enter its value
through GitHub settings or `gh secret set --env governance-apply`.

PR planning uses only the workflow's read-only GitHub token. Public metadata and
ruleset reads suffice for the read-only ruleset plan. The PR receipt explicitly
records settings withheld from readers; it cannot authorize application.
Privileged preflight requires a complete settings diff and repeats discovery with
administration visibility, including bypass actors. A missing bypass field is
an audit failure, not evidence that bypass is disabled.

The application receipt binds the accepted commit, input digests, tool versions,
settings before/after values, plan digest, and operation ledger. Binary Terraform
plans and full plan JSON can contain credentials and are never uploaded. The
saved plan remains on the same runner for apply; retries reconstruct live state
and create a new preflight. Partial failure is recorded and audited without
rollback. Do not place tokens in inventory, shell history, or committed artifacts.

## Failure Policy

Validation fails closed. The repository does not silently omit unknown family
members, missing required checks, unsupported delivery states, malformed
settings, generated-input drift, failed imports, or live audit differences.
Fix the declared source or the live control plane; do not weaken a check to
hide the mismatch.

## License

This repository is licensed under the MIT License. Copyright 2026 Bijan
Mousavi <bijan@bijux.io>. See [`LICENSE`](LICENSE).
