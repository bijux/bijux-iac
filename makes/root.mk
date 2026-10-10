ROOT_MAKEFILE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

include $(ROOT_MAKEFILE_DIR)/bijux-std.mk

TERRAFORM_ROOT := infra/github/main-branch-protection
TERRAFORM_DATA_DIR := $(CURDIR)/artifacts/terraform/data
TERRAFORM_WORK_DIR := $(CURDIR)/artifacts/terraform/module
PYTHON_CACHE_ROOT := $(CURDIR)/artifacts/python/pycache

BIJUX_FMT_TARGETS += terraform-format-check
BIJUX_LINT_TARGETS += contract-tests terraform-validate
BIJUX_TEST_TARGETS += contract-tests
BIJUX_DOCTOR_TARGETS += repository-tools
BIJUX_CI_PR_TARGETS += fmt lint test bijux-std-checks
BIJUX_HELP_TARGETS += live-audit
BIJUX_HELP_live-audit := Compare inventory with live GitHub governance

BIJUX_MAKE_COMPONENTS :=
include $(CURDIR)/.bijux/shared/bijux-makes/bijux.mk

.PHONY: \
	contract-tests \
	inventory-check \
	live-audit \
	python-syntax-check \
	repository-tools \
	shell-syntax-check \
	terraform-format-check \
	terraform-init \
	terraform-inputs \
	terraform-validate \
	tfvars-check

contract-tests: inventory-check tfvars-check python-syntax-check shell-syntax-check ## Verify repository governance contracts
	@PYTHONPYCACHEPREFIX="$(PYTHON_CACHE_ROOT)" \
		python3 -m unittest discover -s tests -t . -p 'test_*.py'

inventory-check: ## Validate the complete repository governance inventory
	@PYTHONPYCACHEPREFIX="$(PYTHON_CACHE_ROOT)" \
		python3 -m scripts.inventory.validate

tfvars-check: ## Verify committed Terraform inputs match the inventory
	@PYTHONPYCACHEPREFIX="$(PYTHON_CACHE_ROOT)" \
		python3 -m scripts.terraform.render --check

python-syntax-check: ## Compile repository-owned Python without source-tree caches
	@mkdir -p "$(PYTHON_CACHE_ROOT)"
	@PYTHONPYCACHEPREFIX="$(PYTHON_CACHE_ROOT)" \
		python3 -m compileall -q scripts

shell-syntax-check: ## Validate repository-owned shell scripts
	@bash -n "$(TERRAFORM_ROOT)/scripts/import_main_branch_protection.sh"

live-audit: ## Compare inventory with live GitHub governance
	@PYTHONPYCACHEPREFIX="$(PYTHON_CACHE_ROOT)" \
		python3 -m scripts.github.audit

terraform-format-check: ## Verify Terraform source formatting
	@terraform -chdir="$(TERRAFORM_ROOT)" fmt -check -recursive

terraform-inputs: ## Prepare an isolated copy of the governed Terraform inputs
	@mkdir -p "$(TERRAFORM_WORK_DIR)"
	@rm -f "$(TERRAFORM_WORK_DIR)"/*.tf "$(TERRAFORM_WORK_DIR)/terraform.auto.tfvars.json"
	@cp "$(TERRAFORM_ROOT)"/*.tf "$(TERRAFORM_ROOT)/terraform.auto.tfvars.json" "$(TERRAFORM_ROOT)/.terraform.lock.hcl" "$(TERRAFORM_WORK_DIR)/"

terraform-init: terraform-inputs ## Initialize Terraform providers and locks under artifacts
	@mkdir -p "$(TERRAFORM_DATA_DIR)"
	@TF_DATA_DIR="$(TERRAFORM_DATA_DIR)" \
		terraform -chdir="$(TERRAFORM_WORK_DIR)" init -backend=false -input=false -lockfile=readonly

terraform-validate: terraform-init ## Validate the managed GitHub Terraform module
	@TF_DATA_DIR="$(TERRAFORM_DATA_DIR)" \
		terraform -chdir="$(TERRAFORM_WORK_DIR)" validate

repository-tools: ## Verify required governance tools are installed
	@command -v python3 >/dev/null
	@command -v bash >/dev/null
	@command -v terraform >/dev/null
