# Ruleset transport and preservation

The protected governance workflow defaults to a read-only preflight using
`github-api`. Its plan owns only additions to required check contexts, their
GitHub Actions App 15368 bindings, and the Pollenomics selector from explicit
`main` to the default branch. It refuses any existing unbound check, context
removal, missing managed ruleset, unrelated baseline protection drift, or
repository settings drift.

The API transport retains each complete ruleset response as a before-image.
It copies every rule and parameter into the request, including
`require_extra_approval_for_unattributed_changes`, `required_reviewers`, and
unrelated protections. It sends only `rules` and `conditions`; name,
enforcement, bypass actors, and other top-level fields stay unchanged. This
uses GitHub's [partial repository ruleset update](https://docs.github.com/en/rest/repos/rules#update-a-repository-ruleset)
contract, with an explicit API version. A JSON round trip must retain every
value before a plan can qualify.

The saved JSON plan and receipt bind accepted main, inventory and source input
digests, complete before-images, producer evidence, and the API version. A
changed source, saved plan, or live state requires a fresh preflight. Each
operation rereads its own complete before-image immediately before a write;
no-op operations never write. Readback must match every retained field except
the server-owned `updated_at` value. A failed write or readback keeps the
operation outstanding even when a general policy audit passes.

The explicit `terraform` choice retains the locked provider schema guard and
saved binary plan path. Provider 6.13.0 cannot represent every active API
parameter; that path refuses before import or planning instead of silently
removing protections. The API transport does not upgrade or reinterpret the
provider. Public pull-request Terraform plans remain read-only and cannot
authorize privileged application.

Application remains a separate explicit manual operation on protected accepted
main. A preflight is never an application receipt. GitHub operations are not
atomic: a failure retains completed and outstanding operations and the final
audit. Retrying requires rereading live state and creating a new plan; there
is no automatic rollback or transactional success claim.
