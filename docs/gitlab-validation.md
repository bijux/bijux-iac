# GitLab validation

The canonical validation project is `bijux-oss/bijux-iac` on GitLab.com.
Its pipeline executes repository contracts, Terraform formatting, readonly
provider initialization and module validation, and the pinned shared standards
integrity check. All generated outputs stay under `artifacts/`; Terraform state,
binary plans and full plan JSON are never uploaded.

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

## Live governance planning remains blocked

The protected default-branch pipeline exposes `governance-plan` as a blocking
manual job in the `governance-plan` environment, serialized by a resource group.
Configure that environment as protected in GitLab before any credential is
placed there. The current job writes an explicit blocked receipt and fails;
it performs no live API reads, plan, infrastructure apply or publication.
A green set of automatic validation jobs is not a completed live plan.

The existing governance application path admits GitHub manual dispatch on the
current accepted `bijux/bijux-iac` main commit. GitLab must obtain its own reviewed
project/job/protected-ref admission and a dedicated repository-scoped read-only
GitHub credential before the live plan can be enabled. Do not populate GitHub
context variables to bypass that admission or copy an interactive GitHub/GLab
session token into CI. Protected administration and apply require a separate
review of exact inputs, settings discovery, provider representation, state
imports, locks and saved-plan review.

The historical GitHub workflows and GitHub ruleset resources are retained.
This pipeline does not establish GitLab policy/approval equivalence, dispatch
consumer publication, change mirror settings or prove a production cutover.
Those surfaces require their own accepted standards and live governance evidence.
