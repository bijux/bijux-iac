# Accepted repository publication

Canonical GitLab projects own review and validation. Their publication children
replicate accepted `main` commits to the matching GitHub and personal GitLab
mirrors. The fixed routes currently cover `bijux-std` and `bijux-iac`.

A completed validation report is the prerequisite. The parent bridge waits for
its child, while the child admits completed physical checks and their report;
it never waits on the parent pipeline's overall terminal status. Publication
receipts keep validation and destination outcomes separate.

## Access configuration

Repository and project settings belong to `bijux-iac`. Configure its declared
profiles and independently read them back before activation:

- Canonical protected `main`: ordinary pushes disabled, Maintainer merges,
  force pushes disabled, and the `publication` environment protected.
- GitHub mirrors: Actions disabled; a separate no-bypass immutable-history guard;
  admission updates restricted to the dedicated App; the factual
  `gitlab / validation` status bound to that App.
- Personal GitLab mirrors: CI and Auto DevOps disabled, shared/group runners
  disabled, and main pushes limited to the destination's write-enabled deploy
  key. Ordinary merges are disabled. Existing owner recovery remains available.

The private GitHub App has Contents, Pull requests, Commit statuses and
Workflows write access, Administration read access, and mandatory Metadata read.
It has no subscribed events or webhook. Installation must select only approved
publication destinations. Each operation mints and reads back an installation
token scoped to its single target repository. Administration read is required
to enforce Actions-disabled read-backs; settings mutation remains a separate
owner operation.

The personal mirror settings token is an existing-user fine-grained token with
only `read_project` on that one selected project. It can be created with the
GitLab own-user access-token API without adding a bot, membership or paid seat.
An ordinary CI job token exposes a public project projection without the
required execution fields and cannot replace this settings credential.

Set these variables in each canonical project with `protected: true`,
`raw: true` and environment scope `publication`:

| Variable | Type |
| --- | --- |
| `BIJUX_MIRROR_GITHUB_APP_ID` | Variable |
| `BIJUX_MIRROR_GITHUB_INSTALLATION_ID` | Variable |
| `BIJUX_MIRROR_GITHUB_APP_KEY` | File |
| `BIJUX_MIRROR_GITLAB_READ_TOKEN` | Variable, masked and hidden |
| `BIJUX_MIRROR_GITLAB_SSH_KEY` | File |

Multiline private-key File values cannot use GitLab's single-line masking
constraint. Keep them protected and environment-scoped; never print their
contents, enable debug traces or include their files in uploaded artifacts.
The publisher copies the SSH key into a private artifact-owned directory,
uses a source-pinned GitLab host key, and removes its private runtime files on
success or failure. Only public publication receipts are uploaded.

After focused tests, owner review, protected-main qualification and hosted
sandbox checks pass, set `BIJUX_MIRROR_PUBLICATION_READY=true` as a protected
variable with scope `*`, so the parent bridge can evaluate it. Set the
`accepted-mirror-publication` resource group to `oldest_first`. Git ancestry
checks and current-main admission independently prevent late jobs rewinding a
mirror; queue ordering alone is insufficient.

## Review and verification

Every production change uses its canonical MR and linked changelog entry.
Owner-authored requests retain explicit `owner-self-signoff`. Both the MR and
actual protected target must satisfy their applicable native review contracts.

Before a mirror advances, the child verifies immutable native evidence, exact
source, merged review, latest required successes, ordinary tracked inputs and
strict frontend timing. Std's report and the six physical unit receipts establish
complete successful case coverage. IaC's five-job topology and sanitized native
read-only plan remain separate from any infrastructure-application authority.

The GitHub publication branch and labeled PR identify the canonical MR and its
pipeline. Main advances through a fast-forward push, preserving the canonical
commit and author identities. GitHub must acknowledge that PR as indirectly
merged. Do not use squash/rebase/merge APIs to manufacture a second commit.
A factual external status links to native validation without executing Actions.

Use isolated verification repositories for failure injection. Prove exact-ref
publication, replay without duplicate PRs, divergence refusal, immutable tag
conflicts, partial destination failure and forward recovery, App-only writes,
and no mirror execution. Test secret absence with inert protected canaries.
Never read or transmit actual protected values from an untrusted test context.

## Operation and recovery

Receipts under `artifacts/publication/receipts/` retain exact source, validation
pipeline/report, canonical MR and independent destination acknowledgements.
GitLab retains them for one year; keep an owner-controlled backup with essential
acceptance evidence so ordinary artifact expiry is not the only surviving proof.

A failed or partial publication fails its child and leaves validation evidence
intact. Inspect `failed_stage` and acknowledged destinations. Repair the denied
route or credential, then retry the failed bridge/child against the same current
accepted main. Existing exact refs and the same deterministic PR are reused.
If main has advanced, validate and publish that accepted descendant instead of
rewinding a mirror. Unexpected divergence requires reconciliation through the
canonical repository, preserving all unique destination history.

Disable activation before credential rotation or unsafe-publisher repair. Rotate
App keys, replace the corresponding protected File variables, verify a freshly
minted selected-repository token, and remove superseded keys. Replace each
GitLab read token before its configured expiry and verify both selected-project
access and denial of an unselected private control. Rotate deploy keys with a
read-back of exact protected-branch grants before removing the superseded key.
Mirror outages never promote another development authority automatically.

Docs remain published through the retained Bijux documentation hub. Current std
and IaC profiles have no enabled product package/release publisher; an internal
CI runtime image is not a product release. A future package or tag publisher
requires its own versioned contract and verified single-publisher ownership.
