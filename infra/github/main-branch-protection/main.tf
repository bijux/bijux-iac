data "github_repository" "managed" {
  for_each = setunion(
    var.legacy_branch_protection_repositories,
    var.ruleset_repositories,
  )

  full_name = "${var.github_owner}/${each.value}"
}

resource "github_branch_protection" "main" {
  for_each = var.legacy_branch_protection_repositories

  repository_id = data.github_repository.managed[each.value].node_id
  pattern       = "main"

  enforce_admins                  = contains(var.legacy_enforce_admins_repositories, each.value)
  allows_force_pushes             = false
  allows_deletions                = false
  require_conversation_resolution = true
  required_linear_history         = false

  required_pull_request_reviews {
    dismiss_stale_reviews           = false
    require_code_owner_reviews      = false
    require_last_push_approval      = false
    required_approving_review_count = var.legacy_required_approving_review_count
  }
}

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
      allowed_merge_methods          = ["merge", "squash", "rebase"]
      dismiss_stale_reviews_on_push  = true
      require_code_owner_review      = false
      require_last_push_approval     = false
      required_approving_review_count = var.ruleset_required_approving_review_count
      required_review_thread_resolution = true
    }

    required_status_checks {
      strict_required_status_checks_policy = true
      do_not_enforce_on_create             = false

      dynamic "required_check" {
        for_each = toset(var.ruleset_required_status_checks[each.value])
        content {
          context = required_check.value
        }
      }
    }
  }
}
