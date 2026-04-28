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

variable "protected_repositories" {
  description = "Repository names that must enforce PR-only main branch policy"
  type        = set(string)
}

variable "required_approving_review_count" {
  description = "Number of approving reviews required before merge"
  type        = number
  default     = 1
}

variable "enforce_admins" {
  description = "Whether branch protection is enforced for repository admins"
  type        = bool
  default     = false
}
