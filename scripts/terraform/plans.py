"""Keep saved ruleset plans inside the authored protection surface."""
from __future__ import annotations

OWNED_RULES = {"deletion", "non_fast_forward", "pull_request", "required_status_checks"}
OWNED_PARAMETERS = {
    "pull_request": {"allowed_merge_methods", "dismiss_stale_reviews_on_push", "require_code_owner_review",
                     "require_last_push_approval", "required_approving_review_count", "required_review_thread_resolution"},
    "required_status_checks": {"strict_required_status_checks_policy", "do_not_enforce_on_create", "required_check"},
}


def require_representable_rulesets(snapshots: dict, schema: dict) -> None:
    """Reject API protections that the actual locked provider cannot retain."""
    try:
        resource = schema["provider_schemas"]["registry.terraform.io/integrations/github"]["resource_schemas"]["github_repository_ruleset"]
        rules = resource["block"]["block_types"]["rules"]["block"]
        attributes, blocks = rules["attributes"], rules["block_types"]
        if not isinstance(attributes, dict) or not isinstance(blocks, dict):
            raise ValueError("malformed rule schema")
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("locked provider ruleset schema could not be verified") from error
    unsupported = []
    for name, detail in snapshots.items():
        if detail is None:
            continue
        for rule in detail["rules"]:
            if not isinstance(rule, dict) or not isinstance(rule.get("type"), str):
                raise ValueError("live ruleset has malformed protection identity")
            kind = rule["type"]
            if kind not in attributes and kind not in blocks:
                unsupported.append(f"{name}: {kind}")
                continue
            parameters = rule.get("parameters", {})
            if not isinstance(parameters, dict):
                raise ValueError("live ruleset has malformed protection parameters")
            block = blocks.get(kind, {}).get("block", {})
            represented = set(block.get("attributes", {})) | set(block.get("block_types", {}))
            if kind == "required_status_checks" and "required_check" in represented:
                represented.add("required_status_checks")
            if kind == "update" and "update_allows_fetch_and_merge" in attributes:
                represented.add("update_allows_fetch_and_merge")
            unsupported.extend(f"{name}: {kind}.{key}" for key in parameters if key not in represented)
    if unsupported:
        raise ValueError("locked provider cannot preserve API protections; review provider support before application: "
                         + "; ".join(unsupported))


def populated(values: dict, excluded: set[str]) -> dict:
    return {key: value for key, value in values.items() if key not in excluded
            and value is not None and value is not False and value != [] and value != {}}


def unowned_rules(values: dict | None) -> dict:
    blocks = (values or {}).get("rules", [])
    if not isinstance(blocks, list) or len(blocks) > 1 or any(not isinstance(block, dict) for block in blocks):
        raise ValueError("plan has malformed ruleset rule blocks")
    # Terraform represents absent optional protections as null, false or empty
    # blocks. Those representations all mean no additional active protection.
    result = {}
    for block in blocks:
        result.update(populated(block, OWNED_RULES))
        for rule, owned in OWNED_PARAMETERS.items():
            parameters = block.get(rule) or []
            if (not isinstance(parameters, list) or len(parameters) > 1
                    or any(not isinstance(parameter, dict) for parameter in parameters)):
                raise ValueError("plan has malformed protection parameters")
            unrelated = [populated(parameter, owned) for parameter in parameters]
            if any(unrelated):
                result[rule] = unrelated
    return result


def validate_ruleset_changes(changes: list, allowed: set[str]) -> None:
    if not isinstance(changes, list):
        raise ValueError("plan resource changes must be an array")
    seen = set()
    for resource in changes:
        if not isinstance(resource, dict) or resource.get("mode") not in {"managed", "data"}:
            raise ValueError("plan has malformed resource identity")
        if resource["mode"] == "data":
            continue
        address = resource.get("address")
        change = resource.get("change")
        if (address not in allowed or address in seen or not isinstance(change, dict)
                or change.get("actions") not in [["no-op"], ["create"], ["update"]]):
            raise ValueError("plan contains an unowned or destructive resource operation")
        seen.add(address)
        before, after = change.get("before"), change.get("after")
        if ((before is not None and not isinstance(before, dict)) or not isinstance(after, dict)
                or unowned_rules(before) != unowned_rules(after)):
            raise ValueError("plan changes rules outside the authored protection surface")
        unknown = change.get("after_unknown", {})
        if not isinstance(unknown, dict) or unowned_rules(unknown):
            raise ValueError("plan cannot prove preservation of unrelated rules")
