# GitLab validation

The canonical validation project is `bijux-oss/bijux-iac` on GitLab.com.
Its pipeline executes repository contracts, Terraform formatting, readonly
provider initialization and module validation, the pinned shared standards
integrity check, and an anonymous live governance plan. All generated outputs
stay under `artifacts/`; Terraform state, binary plans and full plan JSON are
never uploaded.

The pipeline accepts canonical branch pushes, merge requests, protected tags,
and protected default-branch web or scheduled execution. A branch push with an
open merge request is suppressed so that the merge-request pipeline owns that
validation. The project path and stable project ID guard reject publication
mirrors. Project-level CI disablement remains required for mirrors because an
older ref or a modified pipeline can omit the guard.

Every job first compares the checkout SHA with the GitLab commit identity and
records its project, pipeline, job, event, ref and protection state in
`artifacts/gitlab/context.json`. This is source identification for validation,
not acceptance evidence or permission to publish or apply infrastructure.
Validation jobs receive no repository administration or publisher credentials.
The Terraform installer downloads exactly 1.16.5 into `artifacts/tools` and
checks the archive against the vendor's HTTPS SHA256 manifest.

## Anonymous live governance planning

`governance-plan` runs the existing unprivileged Terraform planner after the
four validation gates. It uses public GitLab API reads to bind canonical project
88949971, pipeline source/SHA/ref, and its actual running job. Same-project open
merge requests must match their current head and target `main`; branch and tag
plans must match the current native commit and protection state. Web and
scheduled plans require the actual protected default branch. These identities
admit a read-only plan; they grant no application or publication authority.

The planner projects twelve GitHub development authorities from the fourteen
governed capability profiles. Std and IaC are canonical GitLab authorities, so
their mirror settings and obsolete Actions contexts cannot enter this Terraform
plan. The anonymous gateway also rejects reads outside that twelve-repository
projection. The planner compares public repository settings, discovers rulesets, imports
those rulesets into local state, and validates the resulting saved Terraform
plan with the existing address, action and unowned-rule checks. Reader-hidden
settings remain explicitly `unavailable_to_reader`; a successful read-only
plan cannot certify administrative settings or complete ruleset custody.

Python and the locked GitHub provider share an execution-scoped anonymous GET
gateway. Its only upstream is `https://api.github.com`: accepted repository
metadata, ruleset lists/direct details and the provider's owner lookup. It
rejects writes, credentials, redirects, other routes and unknown queries.
Identical reads share one snapshot, including concurrent requests, so repeated
provider imports do not spend the anonymous quota repeatedly. The snapshot
limits upstream requests to 45, responses to one MiB, retries to three attempts,
and its read window to 180 seconds. API denials, exhausted quotas, malformed
responses and incomplete plans fail the job; there is no authenticated fallback.

The child process receives an allowlisted environment with empty provider token,
a separate home and configuration directory, and no interactive CLI/session or
GitHub App credentials. It uses the pinned provider's anonymous client. Do not
copy local GitHub/GLab session tokens into CI or broaden the publication App.
No new GitLab credential variable is required for this public read-only gate.
A read-scoped credential is a possible separately reviewed quota remedy, not a
prerequisite established by the current public API contract.

The native wrapper verifies source cleanliness before and after planning,
rechecks the native source identity, and compares the planner's input digests
with the current inputs. Only sanitized receipts are uploaded under
`artifacts/gitlab/`: native context and CI configuration digest, the reviewable
plan receipt, and bounded anonymous request status/hash evidence. Local state,
import logs, binary plans and full plan JSON remain outside that upload path.

## Application and authority cutover

A successful plan has `privileged: false`, `remote_writes: false` and
`application_ready: false`. It evaluates only the twelve GitHub development authorities. Each run rebuilds
artifact-owned local state from their fresh imports. The two GitLab control
planes are absent from Terraform resources, imports, settings plans and allowed
resource changes. A saved resource also cannot hide a mirror repository under
an allowed address. No plan authorizes application or publication.

The existing privileged GitHub entry points retain their separate accepted-main
admission and unconditional GitLab-owned-mirror refusal. They also reject the anonymous
transport explicitly. The separately owned desired mirror policy and its read-only reconciliation
distinguish observed drift from reader-hidden settings. Ontology enrollment
requires the accepted fourteen-member standards manifest. Administrative
application and restricted mirror publication require separate reviewed native
admission and live evidence. This validation pipeline grants no infrastructure apply or publication.
