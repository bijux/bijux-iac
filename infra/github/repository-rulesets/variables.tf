variable "github_owner" {
  description = "GitHub repository owner name"
  type        = string
  default     = "bijux"
  validation {
    condition     = var.github_owner == "bijux"
    error_message = "Governance is restricted to the bijux owner."
  }
}

variable "github_token" {
  description = "GitHub token used by Terraform provider"
  type        = string
  sensitive   = true
}

variable "ruleset_repositories" {
  description = "Repository names that must enforce main-branch policy with repository rulesets"
  type        = set(string)
}

variable "ruleset_required_approving_review_count" {
  description = "Number of approving reviews required before merge for ruleset-managed repositories"
  type        = number
  default     = 0
}

variable "ruleset_required_status_checks" {
  description = "Required status check contexts for each ruleset-managed repository"
  type        = map(list(string))
}
