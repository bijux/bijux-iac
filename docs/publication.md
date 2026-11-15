# Manual publication control

The [native IaC controller](native-publication-control.md) is the manual entry
point for the family's applicable documentation deployments and releases. Select
its named typed inputs on protected current `main`; it defaults to `preflight`.
The former IaC GitHub Actions wrapper is not an operational entry point. Merging
to `main` never requests deployment through this manual controller.

This document describes publisher policy and consumer trust. The native guide
owns controller admission, protected credentials, request inputs and receipts.
Migrated Std and IaC sources require their native immutable evidence; retained
GitHub development authorities keep their applicable Actions and merge checks.
Masterclass retains its existing human workflow events.

The accepted `bijux-std` manifest owns which canonical publishers each repository
supports. Repositories with a documentation capability expose the same manual `deploy-docs` workflow,
immutable input and App admission. The manifest explicitly identifies each
documentation destination; missing policy is an inventory error. Std currently
routes to Hub's `/standards/` section and IaC to `/infrastructure/`. Each may
instead declare its own `/{repository}/` site when that surface is ready, using
the same workflow and controller. Genomics uses its own site destination.

A documentation request requires successful immutable source admission. Before
dispatch, verify that its destination has Pages configured with the workflow build
type. The publisher's `configure-pages` step checks Pages using its own scoped
`pages: write` permission; the dispatch App has no Pages permission. This allows
a planned site's first publication without falsely reporting published delivery.
Existing package publishers require published delivery state. npm first-release
admission instead requires explicit accepted enablement and an exact candidate
run; it does not change a planned package into a published one. A request selects a full
40-character current source `main` commit. Releases also require an existing
version tag resolving to exactly that commit. Documentation requests use no tag.

## Dedicated App and consumer trust

The controller uses the existing `bijux-publication` App, ID `5265926`, and bot
user `340710222`. Its permissions remain exactly **Actions: read and write**,
**Contents: read-only**, **Checks: read-only**, **Variables: read-only**, and
**Metadata: read-only**. Additional permissions or the separate mirror App
refuse admission. No new App or automation account is needed.

The [native credential contract](native-publication-control.md#credential-contract)
specifies protected GitLab `publication-control` variables and the File key.
Never put the key in source, a receipt, an artifact, a pull request or chat.
The selected installation must include the actual publication destination; a
Hub-routed foundation needs only Hub. Each minted token is explicitly restricted
to that single destination and independently read back before use.

Each applicable consumer must first accept the exact shared standards projection
with manual dispatch, immutable inputs, and its credential-free admission job.
Then configure the repository variable `BIJUX_PUBLICATION_ACTOR_ID` to the same
bot user ID. Accepting source code and setting trust configuration are distinct
operations; an absent variable intentionally rejects publication.

The App needs Actions write to dispatch, Contents and Checks read to inspect the
accepted target and its checks, and Variables read to inspect consumer trust.
Foundation native source evidence uses unsigned public reads; the App token
remains scoped to Hub. Legacy publisher-admission reads include full check and
pull-request pagination and use the supported `2022-11-28` REST contract because exact
merge admission requires `merge_commit_sha`. The newer API removes that field;
changing this contract requires qualifying a replacement merge proof. See
[GitHub API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions)
and [breaking changes](https://docs.github.com/en/rest/about-the-rest-api/breaking-changes?apiVersion=2026-03-10).
It does not receive repository administration, package publication, release,
or consumer deployment credentials. Publication jobs retain their own existing
credentials, after admission succeeds.

## Verify before a request

Use a read credential with Contents and Variables access and the Ruby structural
workflow parser available to audit all governed repositories:

```bash
python3 -B -m scripts.github.publication --actor-id BOT_USER_ID
```

The command checks applicable canonical entry points, automatic or renamed
publishing callers, admission dependencies, and consumer trust. It reports all
repository mismatches before failing and retains
`artifacts/publication/audit.json`. It performs no dispatch or remote write.

Select `BIJUX_PUBLICATION_REQUEST="1"` on the native protected-main pipeline and
supply the named `PUBLICATION_*` inputs documented in the native guide. Std and
IaC requests additionally require their actual native source pipeline ID; legacy
sources require that input empty. Choose `verify-credential` to test the selected
installation, App identity, current target commit, and required Contents, Checks,
Actions and Variables reads.

Installation tokens are opaque credentials. Do not infer authority from their
length, parse their JWT payload, or truncate them in variables or Authorization
headers. GitHub's stateless token rollout is complete; newly minted tokens are
about 520 characters and retain the `ghs_` prefix. The
[GitHub rollout notice](https://github.blog/changelog/2026-10-02-stateless-github-app-installation-tokens-rolled-out/)
sets November 30, 2026 as the retirement date for the temporary format override
header. Production token creation follows GitHub's normal rollout behavior.
The controller validates explicit token presence, safe transport representation,
expiry, exact permissions and single-destination access. It never prints token
bytes or decoded payloads. Token format or prefix does not establish authority.

This operation tests key/token creation and read access, including the selected
destination's existing bot trust variable. It does not test a write API or
establish complete publisher admission.
The execution job records immutable inputs before creating the token, so a
missing installation or invalid key still retains an incomplete-operation
receipt without implying credential verification or publication succeeded.

The default `preflight` operation verifies the complete publication request and
retains an admission receipt without dispatching. Only the explicit `dispatch`
operation sends a publication request. All operations use accepted main and
the selected-repository token boundary. Credential verification covers the
selected installation; it does not establish access to other repositories.
Credential verification can inspect an applicable planned publisher's
installation. It does not establish source or Pages readiness. Package preflight and dispatch require their applicable accepted enablement;
credential verification does not grant publication permission.

The five physical validations and read-only plan precede the child. The child
independently admits its actual protected current-main controller and request
before reading protected credentials. It then verifies App identity and exact
permissions, consumer admission, current accepted target and tag resolution.
Std and IaC use native exact-SHA source qualification; legacy sources and the
retained Hub destination use their effective GitHub Actions checks.
For accepted-PR execution, those checks and owner approval belong to the exact
human PR head bound to the current normal main merge. Existing-event repositories
retain their current-main check admission. A dependency notice cannot establish
publication readiness. For existing-event repositories, PR-only approval is
verified during merge rather than required to reappear on the merge commit.

The consumer repeats exact-commit and authenticated bot admission before any
publisher job can expose publication credentials. A retry repeats admission and
must retain the requested commit; the controller never silently selects a newer
source commit. For a Hub-routed request, the controller selects Hub's immutable
accepted main before creating its Hub-scoped token, admits both source revisions,
and rechecks both at dispatch. A changed destination refuses the request. The
receipt records the requested foundation revision separately from Hub's rendering
revision and the public section route; it does not claim that Hub renders the
foundation repository's source tree. Native receipts under
`artifacts/publication/control/` record the controller, source, target, tag,
evidence, identity and dispatch outcome. A successful
dispatch receipt proves request acceptance, not successful publication; inspect
the consumer workflow's final result separately.


## npm candidate admission

A `release-npm` request requires `candidate_run_id` in addition to accepted main
and an existing release tag. The candidate must be a successful manual
`package-candidate.yml` run in the same repository at that exact main commit.
A fork, PR run, other workflow, failed result or mismatched revision refuses
preflight. The admitted run identity is retained and forwarded to the consumer.

The canonical standards declaration must explicitly enable npm publication.
The RO-Crate declaration starts disabled. Its package delivery remains `planned`
until actual publication is observed; readiness never fabricates prior success.
The consumer repeats admission and checks the inspected archive cohort before
its own protected OIDC publisher can write to npm. No controller token receives
registry credentials, and the App's existing exact permissions remain unchanged.
An npm-only repository uses its own publication trust variable and does not
acquire a documentation route. `verify-credential` remains read-only; preflight
and dispatch retain their distinct authorization boundaries.
