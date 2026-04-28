resource "github_branch_protection" "main" {
  for_each = var.protected_repositories

  repository_id = each.value
  pattern       = "main"

  enforce_admins                  = var.enforce_admins
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
