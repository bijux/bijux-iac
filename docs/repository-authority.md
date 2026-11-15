# Repository authority

`inventory/repository-authority.json` records exactly fourteen repository roles.
`inventory/repositories.json` separately retains the thirteen live-governance
entries supported by the currently accepted standards manifest. Both inventories
are checked by `make inventory-check`; neither can bypass the live inventory's
exact accepted-capability, required-check or publisher validation.

Ontology is registered in the authority inventory as a planned Python repository
route. Its live-governance enrollment is blocked until the accepted standards
manifest includes its capabilities and truthful authored-verification policy.
RO-Crate Node remains registered in both inventories as the existing Node
workspace. Recording a planned route cannot create a Terraform resource or
invent an accepted product publisher.

## Declared roles

Each authority entry separates the current source from target routing:

| Field | Contract |
| --- | --- |
| `current` | Current GitHub source path, stable repository ID and execution provider |
| `target` | Intended canonical host/path, stable ID where verified and execution provider |
| `status` | `preparing` for std/iac, `planned` for the other ten GitLab routes, `retained` for both hubs |
| `mirrors` | Both intended publication destinations with execution disabled |
| `mirror_publication` | Disabled publication, approved main branch, immutable approved tags and protected publisher ownership |

Eight routes target `bijux-oss`: std, iac, core, atlas, canon, ontology,
RO-Crate Node and GNSS. Four target `bijux-edu`: pollenomics, genomics,
proteomics and phylogenetics. The documentation and Masterclass hubs retain
GitHub, their existing Actions provider, protections and publication backend.

The verified canonical GitLab IDs are 88948041 for std and 88949971 for iac.
The personal mirror IDs are 88949531 for std and 88950131 for iac. Other
undiscovered GitLab IDs remain null. GitHub Actions execution is disabled for
std/iac during preparation; other repositories retain their existing provider.
Declared roles do not replace live API read-back receipts or claim an applied
production cutover.

Unknown keys, duplicate/missing roles, two canonical targets, executing mirrors,
changed hub authority, wildcard refs, unknown destination identities and
activation claims fail closed. Missing destination IDs cannot enable
publication. Routes carry no credentials and never authorize infrastructure
apply, releases, paid memberships, project creation or remote pushes.

## Live-governance admission

GitHub settings and Terraform rendering consume only the accepted live inventory.
All existing GitHub resources, required contexts, imports and protections remain
unchanged. Privileged GitHub governance entrypoints reject the preparing std/iac
roles before GitHub admission or writes, preventing reconciliation from restoring
obsolete GitHub check contexts. The hub publisher keeps its existing admission
boundary. Governance receipts bind both inventory digests.

This preparation model does not claim GitLab provider/API administration,
publication-identity bypass or final mirror-protection reconciliation. Target
cutover requires a reviewed extension backed by exact accepted commit and live
settings evidence. A route edit cannot silently mark the cutover applied.

Ontology promotion requires an accepted immutable standards revision declaring
its Python capabilities, `python / 3.11` and `python / 3.13` checks, explicit
publisher capability and accurate `existing-events` verification ownership.
Its authored push, pull-request, merge-group and manual verification must remain
intact. Refresh the managed standards through their generator, validate both
shared checksum manifests, then add its live settings/ruleset entry and render
Terraform inputs. Full contracts and Terraform checks must pass before reviewing
that change. Promotion does not authorize an infrastructure apply or release.

Canonical GitLab read-only planning uses public anonymous reads and native
pipeline admission, as described in [GitLab validation](gitlab-validation.md).
Privileged application and target-protection reconciliation require their own
reviewed admission and credentials. Historical GitHub application admission
cannot admit GitLab jobs.
