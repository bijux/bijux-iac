output "legacy_protected_main_branches" {
  description = "Legacy branch protection resources enforced by Terraform"
  value       = { for repo, resource in github_branch_protection.main : repo => resource.id }
}

output "ruleset_protected_main_branches" {
  description = "Repository rulesets enforced by Terraform"
  value       = { for repo, resource in github_repository_ruleset.main : repo => resource.id }
}
