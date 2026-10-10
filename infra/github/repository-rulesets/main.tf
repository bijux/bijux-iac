resource "github_repository_ruleset" "main" {
  for_each = var.ruleset_repositories

  name        = "main-branch-protection"
  repository  = each.value
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true

    pull_request {
      allowed_merge_methods             = ["merge"]
      dismiss_stale_reviews_on_push     = true
      require_code_owner_review         = false
      require_last_push_approval        = false
      required_approving_review_count   = var.ruleset_required_approving_review_count
      required_review_thread_resolution = true
    }

    required_status_checks {
      strict_required_status_checks_policy = true
      do_not_enforce_on_create             = false

      dynamic "required_check" {
        for_each = toset(var.ruleset_required_status_checks[each.value])
        content {
          context        = required_check.value
          integration_id = 15368
        }
      }
    }
  }
}
