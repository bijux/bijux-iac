ROOT_MAKEFILE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

include $(ROOT_MAKEFILE_DIR)/bijux-std.mk

TERRAFORM_ROOT := infra/github/main-branch-protection
TERRAFORM_DATA_DIR := $(CURDIR)/artifacts/terraform/data
PYTHON_CACHE_ROOT := $(CURDIR)/artifacts/python/pycache

BIJUX_FMT_TARGETS += terraform-format-check
BIJUX_LINT_TARGETS += contract-tests terraform-validate
BIJUX_TEST_TARGETS += contract-tests
BIJUX_DOCTOR_TARGETS += repository-tools
BIJUX_CI_PR_TARGETS += fmt lint test bijux-std-checks

BIJUX_MAKE_COMPONENTS :=
include $(CURDIR)/.bijux/shared/bijux-makes/bijux.mk

.PHONY: \
	contract-tests \
	inventory-check \
	python-syntax-check \
	repository-tools \
	shell-syntax-check \
	terraform-format-check \
	terraform-init \
	terraform-validate \
	tfvars-check

contract-tests: inventory-check tfvars-check python-syntax-check shell-syntax-check ## Verify repository governance contracts
	@PYTHONPYCACHEPREFIX="$(PYTHON_CACHE_ROOT)" \
		python3 -m unittest discover -s tests -p 'test_*.py'

inventory-check: ## Validate the complete repository governance inventory
	@python3 scripts/validate_repo_inventory.py

tfvars-check: ## Verify committed Terraform inputs match the inventory
	@python3 scripts/render_main_branch_protection_tfvars.py --check

python-syntax-check: ## Compile repository-owned Python without source-tree caches
	@mkdir -p "$(PYTHON_CACHE_ROOT)"
	@PYTHONPYCACHEPREFIX="$(PYTHON_CACHE_ROOT)" \
		python3 -m py_compile scripts/*.py

shell-syntax-check: ## Validate repository-owned shell scripts
	@bash -n "$(TERRAFORM_ROOT)/scripts/import_main_branch_protection.sh"

terraform-format-check: ## Verify Terraform source formatting
	@terraform -chdir="$(TERRAFORM_ROOT)" fmt -check -recursive

terraform-init: ## Initialize Terraform providers under artifacts
	@mkdir -p "$(TERRAFORM_DATA_DIR)"
	@TF_DATA_DIR="$(TERRAFORM_DATA_DIR)" \
		terraform -chdir="$(TERRAFORM_ROOT)" init -backend=false -input=false

terraform-validate: terraform-init ## Validate the managed GitHub Terraform module
	@TF_DATA_DIR="$(TERRAFORM_DATA_DIR)" \
		terraform -chdir="$(TERRAFORM_ROOT)" validate

repository-tools: ## Verify required governance tools are installed
	@command -v python3 >/dev/null
	@command -v bash >/dev/null
	@command -v terraform >/dev/null
