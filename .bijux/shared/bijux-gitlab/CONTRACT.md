# Native GitLab standards execution

`pipeline.py` composes physical job contracts from the existing catalogue,
renderer and browser ownership registries. `execute.py --job '<exact name>'`
executes only a declared physical owner. It uses argument arrays and the
repository's existing Make targets and Python controllers. A failed command
fails its job and retains the actual exit code; no optional-success replacement
or shell command assembled from pipeline variables is supported.

Execution requires GitLab.com's canonical `bijux-oss/bijux-std` project ID
88948041, the actual positive pipeline/job identifiers, exact physical job name,
checkout SHA, checkout directory, event and ref/protection identity. The native
context comes from `tests/bijux-docs/execution/ci_context.py`. GitHub execution
variables are never fabricated. Only after this admission does the ephemeral CI
checkout's `origin` become the public canonical URL. Its previous URL, which may
contain runner credentials, is never read or logged by the harness. Ordinary
local execution without native context fails before changing a remote.

## Runtime and command identity

The standard and contract jobs use the exact Ruby 3.3.12 image declared by the
pipeline. The standard gate independently admits Ruby/Psych before its checksum,
action-reference, shared-standard and generated-pipeline checks. Frontend jobs,
including fixture production, run in the same pinned Playwright image.

Jobs requiring Node download exactly 24.21.0 from its fixed `nodejs.org` release
URL, verify the archive against that release's official HTTPS `SHASUMS256.txt`,
extract into `artifacts/gitlab/tools/node` and verify the executable's version.
Catalogue and contract jobs install exactly uv 0.11.17 into their artifact-owned
virtual environment, using an artifact-owned pip cache. No global pip
installation or unverified installer script is used. A shared bootstrap helper
runs the existing catalogue Make target and independently reopens the standalone
CPython 3.14.4 recipe observation. Catalogue behavior and dependency targets are
unchanged.

Contract tests use a separate environment under
`artifacts/gitlab/contracts/python`, installed through the existing hash-locked
catalogue dependency target. Its `bin` directory leads the contract child's
`PATH`. The child must report exact CPython 3.14.4, the safe tar data filter and
PyYAML imported from that owned environment. The runtime receipt records its
actual path, resolved executable hash and lock hash separately from the system
Python that launches the harness and from the standalone recipe. Safe archive
extraction filters remain enabled. All six contract jobs have a 30-minute
budget; frontend jobs retain the strict 180-second whole-job limit.

The tracked-entrypoint owner also installs the unchanged default renderer lock
through its existing catalogue target.

The pipeline images must provide Python with venv support, Git, Make, curl,
CA certificates, tar, `xz-utils`, Perl, jq and ShellCheck. Runtime tools, caches,
Python bytecode, temporary files and receipts remain under `artifacts/`.
Scratch directories are created before exporting `TMPDIR`. Browser binaries
are the preinstalled `/ms-playwright` image runtime.

Native Python children use unbuffered output so diagnostics emitted before a
timeout remain available in the provider trace.

Every argv execution emits paired source-owned GitLab trace sections and records
its command, real exit code and duration in
`artifacts/gitlab/jobs/$CI_JOB_ID/runtime.json`. Runtime versions, official Node
archive digest/URLs and installed tool executable digests are retained there.
These declarations supplement native job/trace evidence; they do not replace
provider admission or confer publication permission.

The contract-test subprocess receives its artifact paths and runtime tools, but
does not inherit `GITLAB_CI`, `CI_*`, `GITHUB_*` or provider read tokens. Contract
fixtures establish their own explicit provider identities. The containing job's
admission and runtime receipt retain its actual GitLab context. Frontend
qualification, source planning, policy, navigation and reporting retain their
native provider environment.

Unit discovery runs in six mandatory physical jobs. `std / contracts` owns
partition index zero and runs the complete `contract-tests` target, including
shared shell/Python/JSON validation and theme checks. The five additional
`std / contracts / partition` jobs run `contract-unit-tests` for their declared
indices. Every partition discovers the full unittest inventory from the clean
checkout, assigns cases deterministically through `contracts.py`, and preserves
discovery order for module and class fixtures. Failed, errored, skipped or
unexecuted cases prevent coverage qualification.

The source-owned Make command selects `CONTRACT_UNIT_PARTITION` and
`CONTRACT_UNIT_PARTITION_COUNT=6`. Its `CONTRACT_ARTIFACT_ROOT` is
`artifacts/gitlab/jobs/<actual native job ID>/contracts`; temporary files,
bytecode cache and `unit-results.json` belong to that owner. Partitioned runs do
not accept ad hoc unit filters. Leaving the partition variable unset preserves
the existing full unittest discovery command for local and GitHub consumers.
All six jobs use the same admitted CPython 3.14.4 environment, retain actual
failure tracebacks, and have a 30-minute limit. The 73 frontend jobs retain
their separate strict 180-second whole-job limit; the pipeline has 83 jobs.

## Fresh qualification and acceptance

All executions select full fresh verification. Retained proof, affected-input
omissions, observation modes, package release and publication operations are
unsupported and fail explicitly. Fixture production invokes native
`browser_gate.py prepare` directly inside the pinned image. It retains the
existing physical runtime, source and archive proof without Docker-in-Docker.

Navigation and report first call the source-owned native evidence collector.
Navigation excludes the still-unfinished navigation/report owners; report
excludes only itself. The collector requires completed successful prerequisite
jobs at the exact project/pipeline/commit, native lifecycle traces and complete
owned artifact bodies before materializing them. Job identity comes from complete
public pipeline-job API snapshots with retried jobs included. Immutable job-ID
lookups use the latest completed snapshot; the final inventory refresh rejects
newer or changed executions. Restricted single-job and API trace endpoints are
not required.

Public project metadata must bind the numeric project ID to its expected namespace
path before the collector reads `/<namespace>/<project>/-/jobs/<job-id>/raw`.
These public raw traces require no token. Plaintext bodies are bounded; HTML,
sign-in pages and unowned job/project identities fail closed. Approved GitLab
storage redirects carry no credentials and signed query URLs are never retained.
Both classic ANSI section markers and timestamped native log records retain their
original byte hashes and offsets. A complete native `step_script` section remains
mandatory for every frontend job. Missing public evidence blocks qualification;
ambient interactive/session tokens are never a fallback.

Only admitted actual jobs derive result flags. The existing fresh fault/browser
aggregates, renderer-control verification and input planner's plain `verify`
operation then recheck materialized evidence. Report also runs the existing
required check registry through `run-bijux-check-suite.sh`, preserving the
consumer declaration and `artifacts/bijux-checks` reports before acceptance. A collector failure prevents those
controller commands from running. The publisher never waits on its own containing
pipeline; this package does not implement a publisher.

Before running report controllers, the harness reads all six unit receipts from
the actual selected native owner directories. Each physical file must match the
hash admitted from that exact job's artifact archive. `verify_coverage` requires
one receipt per source-declared partition, matching checkout and full discovery
inventory, and an exact disjoint union of executed passing cases. Green native
job status cannot replace missing or incomplete case evidence. Unit receipts
contain no fabricated provider context; the report separately binds their
partition indices, native job IDs, paths and physical file hashes.

The report retains this coverage under its own job artifacts and rechecks it
before acceptance. Successful acceptance also retains `contract-coverage.json`
and embeds the same native ownership proof in `validation.contract_coverage`.

Report emits `artifacts/gitlab/acceptance/acceptance.json` only after successful
native prerequisite admission and fresh verification. Schema version 1 records
server URL, integer project/pipeline IDs, project path, source commit, pipeline
event, ref and boolean protection state, actual prerequisite job records and
separate `validation.status: passed` and `publication.status: pending`. The
running report job is never represented as an already successful prerequisite.
No infrastructure apply, release, GitHub mutation or mirror write occurs.

## Canonical review

`policy.py` reads bounded public native GitLab metadata without session or job
tokens. Feature-branch pushes establish branch validation only, with no review
or publication authorization claim. Merge-request jobs must match the actual
native MR head, target the canonical main branch and be non-draft. Owner `bijux`
requires `owner-self-signoff`; another author requires an actual current native
approval by `bijux`. The MR is read again to reject a racing head/state change.

Protected main must bind exactly one actual merged native MR whose merge commit
is the validated checkout. Imported historical GitHub review records, an
unrelated MR, missing approval, direct main push, squash/rebase substitution or
mismatched head cannot establish this admission. Tag/release authorization and
unsupported manual/scheduled review contexts fail explicitly. Every successful
policy receipt still records `publication_authorization: false`.


## Internal CI runtime construction

Push and web pipelines on `ci/gitlab-runtime` select `ci/runtime.yml`; all
merge requests, including those from that branch, retain the full standards
include. Other refs retain the standards include. Only canonical project 88948041 push or explicit web
pipelines on that exact branch may build the project-internal `ci-runtime`
image. Merge requests, publication mirrors and other destinations are refused.

The Dockerfile inherits the existing immutable Playwright image and installs
only the system packages already required by the native pipeline. No tests,
source checkout, locks, credentials or product outputs are copied into it.
The builder follows [GitLab's rootless BuildKit workflow](https://docs.gitlab.com/ci/docker/using_buildkit/),
using an immutable official `moby/buildkit` digest, no Docker service and no
local or separately registered runner. Registry authentication uses only the
ephemeral native job token. Its private config stays under artifacts, is removed
by the exit trap, and is excluded from artifact uploads.

Each build pushes a unique `job-<native job ID>` tag under the canonical
project's `ci-runtime` repository and retains the actual image digest, builder
identity, exact source SHA and Dockerfile/script hashes. Consumers must pin the
verified immutable digest after an independent registry read-back. Building
this image does not change frontend parallelism, timing limits, profile
approvals or validation evidence, and is not a product release.

`runtime/image.lock.json` binds the verified image digest to its Dockerfile,
build script and canonical native builder. The composer checks those source
hashes and uses the prepared image for frontend jobs, which begin without
repeating system-package installation. Node, Python environments and fixture
archives retain their job-owned installation or provenance checks.

## Accepted-reference publication

`publish / mirrors` is a bridge after the successful `std / report`, enabled
only on protected default-branch execution with the protected activation flag.
It starts the separate source-owned publication child. The native physical-job
API excludes bridges, preserving the complete 83-owner validation contract.
The child requires actual successful prerequisite jobs and the completed report;
it does not wait for its containing parent pipeline to finish while that parent
is waiting for the publication child.

The child independently admits canonical project, source, protected main,
current running physical job, native parent/bridge relationship, latest required
attempts, actual merged owner-reviewed MR and the report artifact. Its source
contract requalifies unit coverage before any mirror mutation. The accepted
pipeline URL and immutable acceptance artifact URL are recorded separately.

Only the child has the `publication` environment. Its protected file variables
contain the dedicated GitHub App key and destination-specific GitLab SSH key;
ordinary validation jobs have no matching environment scope. GitHub installation
tokens expose one fixed repository and expire within one hour. The GitLab
settings token has only selected-project `read_project` permission. Interactive
credential helpers, user SSH configuration, agents and redirects are excluded.

The publisher checks both identities and disabled execution before writing,
previews both Git histories, creates the GitHub publication record before
advancing main, and independently reads back exact commit identities and native
indirect-merge acknowledgement. It never force-updates or deletes a ref. A
partial result retains destination acknowledgements and fails publication; retry
reuses the same branch and PR and advances only missing accepted work.

Historical tags remain intact. Automatic publication is currently allowlisted
to `main`; a product release/tag contract requires a separately reviewed explicit
allowlist. The [runbook](publication/README.md) covers credentials, operation,
mirror lag, rotation and forward recovery.
