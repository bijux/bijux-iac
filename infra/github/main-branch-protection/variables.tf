variable "github_owner" {
  description = "GitHub organization owner name"
  type        = string
  default     = "bijux"
}

variable "github_token" {
  description = "GitHub token used by Terraform provider"
  type        = string
  sensitive   = true
}

variable "legacy_branch_protection_repositories" {
  description = "Repository names that continue to use legacy branch protection"
  type        = set(string)
}

variable "legacy_required_approving_review_count" {
  description = "Number of approving reviews required before merge for legacy branch protection"
  type        = number
  default     = 1
}

variable "legacy_enforce_admins_repositories" {
  description = "Repository names whose legacy branch protection also applies to repository admins"
  type        = set(string)
  default     = []
}

variable "ruleset_repositories" {
  description = "Repository names that must enforce main-branch policy with repository rulesets"
  type        = set(string)
  default     = []
}

variable "ruleset_required_approving_review_count" {
  description = "Number of approving reviews required before merge for ruleset-managed repositories"
  type        = number
  default     = 0
}

variable "ruleset_required_status_checks" {
  description = "Required status check contexts for each ruleset-managed repository"
  type        = map(list(string))
  default     = {}
}
