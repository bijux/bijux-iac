# Repository authority

`inventory/repositories.json` covers the fourteen governed capability profiles,
including Ontology and the existing RO-Crate Node workspace. Its required checks,
workflow execution and publication capabilities must match the exact accepted
Bijux Std manifest. A local checkout or an unaccepted standards candidate cannot
satisfy that dependency.

`inventory/repository-authority.json` records source ownership independently.
Std and IaC have canonical GitLab development authority; the other twelve
repositories retain GitHub development authority. The two hubs retain their
existing publication backend and have no mirror routes. Ten other products have
planned GitLab targets, which do not change their current development authority.

## Declared roles

| Field | Contract |
| --- | --- |
| `current` | Current canonical source identity and execution provider |
| `target` | Intended canonical host/path, stable ID where verified, and provider |
| `status` | `preparing` for std/iac publication, `planned` for ten product routes, `retained` for both hubs |
| `mirrors` | Intended publication destinations with execution disabled |
| `mirror_publication` | Disabled publication, approved main branch, immutable approved tags, protected publisher ownership |

Eight routes target `bijux-oss`: std, iac, core, atlas, canon, ontology,
RO-Crate Node and GNSS. Four target `bijux-edu`: pollenomics, genomics,
proteomics and phylogenetics. The documentation and Masterclass hubs retain
GitHub, their Actions provider, protections and publication backend.

The canonical GitLab IDs are `88948041` for std and `88949971` for iac.
Personal mirror IDs are `88949531` and `88950131`. Other undiscovered GitLab
IDs remain null. Unknown keys, duplicate or missing roles, executing mirrors,
changed hub routes, wildcard branches and activation claims fail validation.
A desired route never substitutes for live API readback or accepted source.

## Governance by role

The complete fourteen-member family remains available to capability and product
publication validation. The legacy GitHub development projection contains only
twelve repositories. Terraform rendering, ruleset discovery and imports,
repository settings plans, legacy audits and check-producer collection all use
that projection. Each plan rebuilds artifact-owned local Terraform state from
fresh discovery, so removing the two mirror addresses does not plan destruction
of their existing protections. No historical shared state is adopted.

Direct legacy settings and ruleset writers refuse std/iac. Saved Terraform plans
also refuse their resource addresses or repository values, even if a caller
supplies a permissive address allowlist. Privileged historical GitHub entrypoints
remain blocked for GitLab-owned std/iac regardless of future publication status.
An authority status edit cannot reactivate that path. Hub publication keeps its
existing independent admission boundary.

`inventory/authority-governance.json` owns the separate desired policy:

| Surface | Desired contract |
| --- | --- |
| Canonical GitLab `main` | No direct push, Maintainer merge level `40`, no force push |
| Canonical `publication` environment | Maintainer deployment level `40` |
| GitHub admission ruleset | Restrict updates, preserve pull-request policy, require `gitlab / validation` from App `5768636`, bypass only that App |
| GitHub history guard | Separate active deletion and non-fast-forward rules, no bypass actors |
| GitHub mirror execution | Actions disabled |
| Personal GitLab mirror | CI, shared/group runners and Auto DevOps disabled; only the exact declared deploy key may push `main`, no ordinary merge or force push |

The policy binds stable project, repository, ruleset, App and deploy-key IDs.
It declares `claim: desired` and publication disabled. Neither validation nor a
matching readback authorizes infrastructure application or mirror publication.
Plan input receipts bind the capability, authority and desired-policy digests.

## Read-only reconciliation

Retain provider responses under the active repository's `artifacts/` directory.
A snapshot contains `github.repository`, `github.actions`,
`github.history_guard`, `github.admission`, `canonical.project`,
`canonical.main`, `canonical.environment`, `personal.project` and
`personal.main`, using the corresponding GitHub and GitLab API response shapes.
Do not include credentials or CI variable responses.

```bash
python3 -B -m scripts.governance.reconciliation \
  --repository bijux-std \
  --snapshot artifacts/authority-governance/bijux-std-observations.json
```

The command writes a sanitized comparison to
`artifacts/authority-governance/bijux-std-reconciliation.json`. Missing
administrative fields, hidden bypass actors or anonymous GitLab projections are
`unavailable`, not proof of disabled CI or absent bypass. Observed contradictions
are `drift`; a complete matching observation is `matched`. All outcomes retain
`remote_writes: false` and `application_ready: false`. This command does not
fetch credentials, change settings or activate publication.

## Ontology ownership

Ontology is a Python library with adapters and reasoning code. Its profile uses
`common` and `python`, planned packages, no owned documentation publication,
and `python / 3.11` and `python / 3.13` product checks. It explicitly retains
`main_verification: existing-events`, as does Masterclass. No other repository
may claim that exception. Authored push, pull-request, merge-group and manual
verification remain intact.

Ontology owns any future product publication entrypoint; IaC owns the manual
controller. The current entrypoint map is empty and publication is disabled.
This declares ownership without inventing a release workflow or changing the
existing hub publisher.

Managed standards must be refreshed from the accepted immutable GitHub source,
with source receipts and both shared checksum manifests validated. Inventory,
generated Terraform inputs and repository contracts must then pass together.
Canonical read-only planning has separate native admission described in
[GitLab validation](gitlab-validation.md); historical GitHub application
admission cannot admit GitLab jobs.
