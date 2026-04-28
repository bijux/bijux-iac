ROOT_MAKEFILE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

include $(ROOT_MAKEFILE_DIR)/bijux-std.mk

.PHONY: help

##@ Repository
help: ## Show available repository commands
	@awk 'BEGIN {FS = ":.*## "}; /^[a-zA-Z0-9_.-]+:.*## / {printf "%-22s %s\n", $$1, $$2}' \
	  "$(ROOT_MAKEFILE_DIR)/bijux-std.mk" "$(CURDIR)/Makefile"
