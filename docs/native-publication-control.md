# Native manual publication control

The native IaC controller restores the existing manual family operations after
IaC GitHub Actions disablement. It defaults to `preflight`. Capability and
publisher policy still come from the accepted standards manifest and the existing
IaC inventory; this controller does not enable a release, change App permissions,
or change the two retained GitHub hubs' deployment backend.

The package entrypoint is `python3 -B -m scripts.publication`. It accepts
`--operation verify-credential`, `--operation preflight` or the explicitly
selected `--operation dispatch`. Without the argument it reads
`PUBLICATION_OPERATION`, defaulting to `preflight` when absent. Empty or unknown
operations refuse. A local CLI session cannot substitute for native admission.

## Native admission

The physical `publication / control` job must belong to a real running child of
canonical `bijux-oss/bijux-iac`, project `88949971`, on its current protected
`main`. The actual `publish / request` bridge owns that child; actual parent,
child, job, source SHA and owner review are read independently. Only manual
`web` or explicitly selected `api` parents are admitted. All five immutable IaC
validation jobs and the read-only governance plan archive must qualify at the
controller SHA. The native ownership check repeats after credential work and
before dispatch.

Std and IaC target requests additionally name an exact source pipeline. Native
source admission checks canonical and GitHub current refs, source-owned physical
jobs, merged owner review and immutable artifacts. Std requires its complete
acceptance evidence and contract coverage; IaC requires its five-job plan.
GitHub mirror status cannot substitute for either source's native verification.
Other family sources retain existing GitHub Actions publisher admission.

Foundation documentation continues to route to Hub: `/standards/` for Std and
`/infrastructure/` for IaC. The controller selects and binds the Hub destination
commit separately from the requested foundation commit. Hub's unchanged
exact-commit, App actor, Actions verification and protected Pages admission still
run before its own build and deployment. A reachable existing site is not proof
of a new deployment.

## Request inputs

The root pipeline exposes these named string inputs. The child maps them to the
same environment-variable names for the controller.

| Typed pipeline input | Contract |
| --- | --- |
| `PUBLICATION_OPERATION` | `preflight` by default; `verify-credential` and explicit `dispatch` are supported |
| `PUBLICATION_TARGET_REPOSITORY` | One applicable governed family repository |
| `PUBLICATION_TARGET_WORKFLOW` | Existing applicable manual publisher, including `deploy-docs` and existing release families |
| `PUBLICATION_TARGET_COMMIT` | Exact current accepted source SHA |
| `PUBLICATION_TARGET_TAG` | Required admitted version tag for releases; empty for docs |
| `PUBLICATION_TARGET_CANDIDATE_RUN` | Existing npm candidate run identity when that capability is enabled; otherwise empty |
| `PUBLICATION_TARGET_PIPELINE_ID` | Required positive native source pipeline ID for Std/IaC; empty for legacy sources |

Planned npm capability remains disabled until its existing accepted enablement
contract permits it. Credential verification retains existing delivery-state
exceptions but does not prove dispatch write permission. Preflight qualifies the
request and performs no workflow dispatch.

## Credential contract

Only the existing `bijux-publication` App is admitted. The mirror App and ambient
CLI/session tokens cannot supply publication authentication.

| Protected GitLab variable | Type | Value or meaning |
| --- | --- | --- |
| `BIJUX_PUBLICATION_APP_ID` | Environment variable | `5265926` |
| `BIJUX_PUBLICATION_INSTALLATION_ID` | Environment variable | Verified existing selected installation; must match App readback |
| `BIJUX_PUBLICATION_ACTOR_ID` | Environment variable | `340710222` |
| `BIJUX_PUBLICATION_APP_PRIVATE_KEY` | File variable | Existing App PEM; never emitted into logs, receipts or artifacts |

These variables are protected, raw, scoped to `publication-control`. The File
variable is not masked because it contains a multiline PEM. The protected
environment retains Maintainer deployment role `40`. The controller refuses
debug tracing. Existing App permissions remain exactly Actions write, contents
read, checks read, Actions variables read and metadata read. A short-lived token
is minted for only the actual selected destination and independently read back
to confirm its one repository and expiry.

## Native CI integration contract

The root pipeline retains its five validation jobs and exposes
`BIJUX_PUBLICATION_REQUEST`, a string input restricted to `"0"` or `"1"` and
defaulting to `"0"`. Selecting `"1"` on a protected current-main web or API
pipeline requests the manual controller. Operation defaults independently to
`preflight`. API-source validation additionally verifies the actual protected
current default branch; ordinary API pipelines are refused. A manual request
excludes the automatic mirror bridge on both web and API pipelines.

The `publish / request` bridge supplies only the seven named typed request inputs
to `.gitlab/publication-control.yml`. It disables inherited variables and sets
its separate reserved `BIJUX_PARENT_PIPELINE_ID` from native `CI_PIPELINE_ID`,
outside the request schema. `forward.yaml_variables: true` carries that fixed
parent binding, while `forward.pipeline_variables: false` prevents arbitrary
caller pipeline variables from entering the child. Typed input defaults preserve
`preflight`; empty or unknown operation strings are rejected before execution.

The child owns one `publication / control` job, protected `publication-control`
environment, non-cancelling publication concurrency and only
`artifacts/publication/control/` receipts. It consumes current native identity;
it does not synthesize any GitHub execution context. Its script invokes the
package entrypoint `python3 -B -m scripts.publication`, using Python 3.13 with git,
OpenSSL and Ruby available for signing and the existing structural policy parser.

## Receipts and outcomes

Receipts identify the native controller, requested source, destination,
operation, evidence and dispatch acknowledgement without credentials. They are
written before credentials, before a dispatch attempt, and after its outcome.
An ambiguous dispatch failure remains `remote_writes: null` and is not retried.
A positive dispatch acknowledgement followed by receipt I/O failure retains
`remote_writes: true`, the acknowledged workflow run ID, and
`status: dispatch-receipt-failed`. Failure-stage and storage-failure diagnostics
contain no exception messages or credentials. Best-effort failure writes never
replace the known or unknown dispatch outcome, and the CLI still emits that
sanitized outcome if fallback storage also fails.
A successful dispatch acknowledgement does not claim a completed deployment or
release; the actual downstream publisher owns that outcome.

Hosted verification binds a controller result to its actual source, native
parent, child, physical caller and retained receipt. Local contract tests use
controlled transport fixtures and perform no real publication or deployment.
