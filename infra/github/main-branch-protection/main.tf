data "github_repository" "managed" {
  for_each = var.protected_repositories

  full_name = "${var.github_owner}/${each.value}"
}

resource "github_branch_protection" "main" {
  for_each = var.protected_repositories

  repository_id = data.github_repository.managed[each.value].node_id
  pattern       = "main"

  enforce_admins                  = contains(var.enforce_admins_repositories, each.value)
  allows_force_pushes             = false
  allows_deletions                = false
  require_conversation_resolution = true
  required_linear_history         = false

  required_pull_request_reviews {
    dismiss_stale_reviews           = false
    require_code_owner_reviews      = false
    require_last_push_approval      = false
    required_approving_review_count = var.required_approving_review_count
  }
}
