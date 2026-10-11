# Workflow execution and dependency review

The inventory defines a shared execution policy for all twelve repositories.
`workflow_execution_defaults` requires dependency notifications, verification on
human pull requests, and dependency changes consolidated by repository owners.
Each repository exposes the same `governance.workflow_execution` override object.
Masterclass retains `main_verification: existing-events` because its existing
human verification and documentation deployment are managed separately.

| Event | Execution | Acceptance evidence |
| --- | --- | --- |
| Dependabot pull request | A bounded notification without checkout, installation, or product verification | Owner review is pending; the notification does not satisfy required checks |
| Human pull request | Existing verification and owner approval | Successful required checks on the exact pull request head |
| Accepted merge to main | No duplicate product verification for repositories using `accepted-pull-request` | The verified human pull request bound to the current normal merge |
| Manual documentation or publication dispatch | Explicit workflow admission and its existing execution gates | Separate publication authorization and immutable source evidence |

The dependency classifier uses the original PR author. It includes Dependabot
and the `github-actions[bot]` author only on the exact
`automation/dependency-lock-refresh` proposal branch. An owner's review does not
turn a bot proposal into human verification. Unrelated automation PRs retain
their existing admission behavior.

Dependency proposals remain visible as pull requests. Owners review complete
changes, consolidate accepted proposals into a verified human pull request, and
close superseded proposals after their complete changes are covered by the
accepted revision. Dependency proposals are never automatically merged.

Skipped dependency jobs use distinct `unverified dependency / …` names. GitHub
can accept a skipped required check, so retaining human verification names on
skipped bot jobs would incorrectly allow a notification to establish acceptance.
The notification is a receipt, not verification or approval.

## Evidence for accepted source

IaC binds current main to exactly one closed, merged human pull request. The main
commit must be a normal two-parent merge, its merge SHA must match the pull
request, and its second parent must be that pull request's exact head. Direct
commits, squash commits, unrelated earlier pull requests, ambiguous associations,
and dependency notifications cannot borrow earlier successful verification.

Before using pull request evidence, IaC reads the consumer's canonical workflow
policy at the immutable main commit and requires its adopted policy to match the
inventory. Required check runs must belong to GitHub Actions, match the exact
head, and have a latest completed successful result. Failed, pending, skipped,
foreign-head, and foreign-application results do not establish verification.
Masterclass retains its existing main verification selection; a failed main
check cannot borrow a successful pull request result.

GitHub updates its native dependency graph when supported dependency manifests
change on the default branch. This does not require repeating the product test
suite. See [dependency graph data](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-graph-data)
for the supported collection mechanisms. Explicit dependency submission, where
present, is separate from product verification.

## Ownership and enforcement

Bijux Std owns canonical event projection, dependency notifications, bot guards,
job names, and workflow conformance. Repository-owned workflows follow that
contract while retaining their human verification steps. IaC owns typed family
defaults, the Masterclass exception, consumer adoption checks, and evidence used
by governance and publication preflight.

Generated content is refreshed from an exact accepted Bijux Std GitHub source.
Local inventory and producer contracts validate the resulting policy before a
governance plan is reviewed. Live governance application and actual publication
remain separate operations; accepting this policy does not dispatch either.
