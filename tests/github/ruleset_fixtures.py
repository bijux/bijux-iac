"""Complete GitHub ruleset fixtures shared by audit and transport controls."""

def healthy_ruleset():
    from scripts.github.audit import STATUS_APP_ID
    return {
        "name": "main-branch-protection", "target": "branch", "enforcement": "active",
        "bypass_actors": [], "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                  {"type": "pull_request", "parameters": {
                      "allowed_merge_methods": ["merge"], "required_approving_review_count": 0,
                      "dismiss_stale_reviews_on_push": True, "required_review_thread_resolution": True,
                      "require_code_owner_review": False, "require_last_push_approval": False,
                  }}, {"type": "required_status_checks", "parameters": {
                      "strict_required_status_checks_policy": True, "do_not_enforce_on_create": False,
                      "required_status_checks": [{"context": "example", "integration_id": STATUS_APP_ID}],
                  }}],
    }
