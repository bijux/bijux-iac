# Accepted mirror publication

IaC's `publish / mirrors` job is a downstream pipeline bridge after the
successful `governance-plan` job. It runs only on the protected default branch
when the operator has set `BIJUX_MIRROR_PUBLICATION_READY=true`. Merge-request
validation and ordinary branch checks do not receive publication credentials.
The five physical validation jobs and their anonymous planning boundary remain
unchanged; GitLab lists the bridge separately from physical pipeline jobs.

The bridge includes
`.bijux/shared/bijux-gitlab/ci/publication.yml` and passes its actual
`CI_PIPELINE_ID` as `BIJUX_PARENT_PIPELINE_ID`. The shared child owns the single
physical `publication / mirrors` job and the protected `publication` environment.
Its admission verifies the actual native parent bridge and child identities,
current protected `main`, successful latest validation jobs, immutable plan
receipts and the actual merged canonical review. The supplied parent ID alone
cannot authorize publication.

## Standards ownership

IaC selects the `common` and `gitlab` shared capabilities. The publisher belongs
to Bijux Std; it must be installed by the standards generator from the exact
accepted GitHub commit recorded in `.github/standards/bijux-std.sha`.
Do not copy a local standards candidate or hand-edit the installed package.
The independent documentation pin remains separate.

The refresh must verify `.github/bijux-std-shared.sha256` and
`.bijux/shared/shared-dir-sha256.txt` together with source provenance. A bridge
change without the accepted shared child and publisher is incomplete; it must
not be activated merely because the local handwritten contracts pass.

## Activation and credentials

Keep readiness disabled until the canonical environment, scoped credentials and
both mirror protection profiles have been configured and read back. The shared
publisher uses these protected `publication`-scoped variables:

| Variable | Purpose |
| --- | --- |
| `BIJUX_MIRROR_GITHUB_APP_ID` | Dedicated publication App `5768636` |
| `BIJUX_MIRROR_GITHUB_INSTALLATION_ID` | Actual selected-repository installation |
| `BIJUX_MIRROR_GITHUB_APP_KEY` | File variable containing the App signing key |
| `BIJUX_MIRROR_GITLAB_SSH_KEY` | File variable containing the destination project deploy key |
| `BIJUX_MIRROR_GITLAB_READ_TOKEN` | Dedicated read-only identity for personal mirror settings |

The App mints a short-lived token for the exact GitHub repository and verifies
that scope through an independent readback. Git authentication uses isolated
configuration and the destination deploy key. Interactive owner credentials and
local sessions are not runtime substitutes. GitHub Actions and personal GitLab
CI/runners/Auto DevOps remain disabled on the mirrors.

The checked-in inventories declare `active` and enabled publication as the
desired target for both control planes. Operator readiness is configured only
after merge-request qualification and review; it permits the first child to run
after the accepted change reaches protected `main`. IaC's first automatic child
remains qualification pending until that job acknowledges both destinations.
The supported declaration states agree across both inventories:

| Authority status | `mirror_publication.enabled` | Desired governance `publication_enabled` |
| --- | --- | --- |
| `preparing` | `false` | `false` |
| `active` | `true` | `true` |

Only std and IaC may make that transition, independently. The ten future product
routes remain `planned` with publication disabled; the two hubs remain `retained`
with no mirror routes. Activation values must be literal booleans and the two
inventories must agree. These declarations describe the desired activation;
they do not configure service variables or grant infrastructure apply authority.

Std's publisher has actual protected-main evidence: parent pipeline
[3070347415](https://gitlab.com/bijux-oss/bijux-std/-/pipelines/3070347415) passed
all 83 validation jobs, followed by successful publication child
[3070359580](https://gitlab.com/bijux-oss/bijux-std/-/pipelines/3070359580).
The accepted GitHub `main` source is
`718205998095d71b8339e54fd7d0eb70e2cbd2dd`. These Std observations do not certify
that IaC's automatic child has executed.

The legacy GitHub governance guard continues to refuse both canonical GitLab
authorities by stable role and identity, including when publication is active.
Its twelve GitHub development resources and the hubs' existing publication
admission do not change with mirror readiness.

## Results and recovery

The shared publisher creates the deterministic GitHub publication branch and PR,
links canonical review and parent validation evidence, and writes the
App-authored `gitlab / validation` status. Default branches advance only through
fast-forward Git operations with independent readback. GitHub must acknowledge
the exact publication PR as indirectly merged before the personal GitLab mirror
is advanced. Automated tag publication is not enabled by this bridge.

Each destination keeps its own acknowledgement in
`artifacts/publication/receipts/`. A partial result records the completed
destination and failed surface; retrying never grants permission to rewind,
force-push or replace conflicting history. Only receipts are uploaded, not
credential files or Terraform state. A one-time owner publication has separate
operator evidence and does not establish that the automatic child has run.
