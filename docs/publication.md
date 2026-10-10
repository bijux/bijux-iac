# Manual publication control

The `publication-control` workflow in `bijux-iac` is the manual entry point for
the family's applicable documentation deployments and releases. Merging to
`main` never requests publication. Build, test, and CI artifact workflows remain
automatic.

The accepted `bijux-std` manifest owns which canonical publishers each repository
supports. Every family member must declare its publication capability, including
explicit empty capabilities for the two publisher-free foundations. Missing
policy is an inventory error, never permission to publish. IaC uses that
declaration together with inventory delivery state; planned or inapplicable
surfaces cannot be dispatched. A request selects a full
40-character current target `main` commit. Releases also require an existing
version tag resolving to exactly that commit. Documentation requests use no tag.

## Configure the dedicated GitHub App

This is an automation identity, not another repository. Sign in to the personal
`bijux` account, then open **Settings → Developer settings → GitHub Apps → New
GitHub App** at <https://github.com/settings/apps/new>:

1. Name: **bijux-publication**. Homepage: `https://github.com/bijux/bijux-iac`.
2. Disable **Active** under Webhook. No webhook URL or subscribed events are
   needed. Keep user authorization and OAuth callbacks disabled.
3. Set repository permissions to exactly **Actions: read and write**,
   **Contents: read-only**, **Checks: read-only**, **Variables: read-only**, and
   **Metadata: read-only**. Leave other repository and organization permissions
   unset. No organization permissions are needed. The controller rejects
   additional permissions.
4. Permit installation only on the owning account. Create the App, record its
   numeric **App ID**, and generate a private key. Never commit the key or put it
   in a pull request, receipt, or chat.
5. Install it only on the governed repositories with applicable publishers.
   Foundations need no installation. The token action further restricts each
   installation token to the one selected repository. Genomics cannot be
   dispatched while its delivery remains planned.
6. Find the bot's numeric identity with
   `gh api 'users/bijux-publication[bot]' --jq .id`. This is the **bot user ID**,
   not the App ID or installation ID.

In `bijux-iac`, create the **publication-control** environment:

- Select deployment branches/tags; add only the branch `main`, with no tags.
- Disable administrator bypass of protection rules. Keep the existing owner
  review model; this configuration adds no additional reviewer requirement.
- Add environment variables `BIJUX_PUBLICATION_APP_ID` (App ID),
  `BIJUX_PUBLICATION_ACTOR` (`bijux-publication[bot]`), and
  `BIJUX_PUBLICATION_ACTOR_ID` (bot user ID).
- Add the environment secret `BIJUX_PUBLICATION_APP_PRIVATE_KEY` using the
  downloaded key. Keep this key out of repository and organization secrets.

Each applicable consumer must first accept the exact shared standards projection
with manual dispatch, immutable inputs, and its credential-free admission job.
Then configure the repository variable `BIJUX_PUBLICATION_ACTOR_ID` to the same
bot user ID. Accepting source code and setting trust configuration are distinct
operations; an absent variable intentionally rejects publication.

The App needs Actions write to dispatch, Contents and Checks read to inspect the
accepted target and its checks, and Variables read to inspect consumer trust.
It does not receive repository administration, package publication, release,
or consumer deployment credentials. Publication jobs retain their own existing
credentials, after admission succeeds.

## Verify before a request

Use a read credential with Contents and Variables access and the Ruby structural
workflow parser available to audit all twelve repositories:

```bash
python3 -B -m scripts.github.publication --actor-id BOT_USER_ID
```

The command checks applicable canonical entry points, automatic or renamed
publishing callers, admission dependencies, and consumer trust. It reports all
repository mismatches before failing and retains
`artifacts/publication/audit.json`. It performs no dispatch or remote write.

Only dispatch the accepted `publication-control.yml` on IaC `main`, specifying
`repository`, `workflow`, `commit`, and the release tag when applicable. Choose
`verify-credential` to test the selected installation, App identity, current
target commit, and required Contents, Checks, Actions, and Variables reads.

Installation tokens are opaque credentials. Do not validate their length, parse
their JWT payload, or truncate them in environment variables or Authorization
headers. GitHub's stateless token rollout is complete; newly minted tokens are
about 520 characters and retain the `ghs_` prefix. The
[GitHub rollout notice](https://github.blog/changelog/2026-10-02-stateless-github-app-installation-tokens-rolled-out/)
sets November 30, 2026 as the retirement date for the temporary format override
header. Production token creation follows GitHub's normal rollout behavior.
Credential verification records only token character count and an observed
format label after successful API reads. That diagnostic never controls admission
and includes no credential bytes or decoded payload. Offline fixtures cover
classic, stateless, longer, and unclassified opaque tokens without publication.

This operation tests key/token creation and read access; it does not test a
write API or require consumer trust to have been configured yet.
The execution job records immutable inputs before creating the token, so a
missing installation or invalid key still retains an incomplete-operation
receipt without implying credential verification or publication succeeded.

The default `preflight` operation verifies the complete publication request and
retains an admission receipt without dispatching. Only the explicit `dispatch`
operation sends a publication request. All operations use accepted main and
the selected-repository token boundary. Credential verification covers the
selected installation; it does not establish access to other repositories.
Credential verification can inspect an applicable planned publisher's
installation. Preflight and dispatch still require published delivery state;
verifying access never enables a planned publication capability.

The unprivileged admission job rejects a feature ref or invalid capability before
entering the credential environment. The controller then verifies the App's
identity and exact permissions, consumer admission, current accepted target,
tag resolution, and all effective required commit checks from GitHub Actions.
The PR-only approval check is verified during merge rather than required to
reappear on the merge commit.

The consumer repeats exact-commit and authenticated bot admission before any
publisher job can expose publication credentials. A retry repeats admission and
must retain the requested commit; the controller never silently selects a newer
commit. `artifacts/publication/request.json` records the controller run and
commit, target, tag, required checks, identity, and dispatch outcome. A successful
dispatch receipt proves request acceptance, not successful publication; inspect
the consumer workflow's final result separately.
