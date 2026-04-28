output "protected_main_branches" {
  description = "Main branch protection resources enforced by Terraform"
  value       = { for repo, resource in github_branch_protection.main : repo => resource.id }
}
