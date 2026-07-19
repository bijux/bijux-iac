# Shared Bijux standard source-of-truth checks and updates.

BIJUX_STD_CHECK_SCRIPT ?= .bijux/shared/bijux-checks/check-bijux-std.sh
BIJUX_STD_UPDATE_SCRIPT ?= .bijux/shared/bijux-checks/update-bijux-std.sh
BIJUX_STD_PIN_FILE ?= .github/standards/bijux-std.sha
BIJUX_STD_REF ?= $(strip $(shell cat "$(BIJUX_STD_PIN_FILE)"))
BIJUX_STD_CAPABILITIES ?= common
BIJUX_STD_REMOTE ?= https://raw.githubusercontent.com/bijux/bijux-std
BIJUX_STD_GIT_URL ?= https://github.com/bijux/bijux-std.git
BIJUX_STD_UPDATE_CHANNEL ?= branch
BIJUX_STD_TAG_PATTERN ?= v*
BIJUX_STD_REQUIRE_REMOTE_MATCH ?= 1
BIJUX_STD_STRICT_REMOTE ?= 1

BIJUX_HELP_TARGETS += bijux-std bijux-std-checks bijux-std-update
BIJUX_HELP_bijux-std := Verify synchronized standards
BIJUX_HELP_bijux-std-checks := Verify managed content against the pinned standard
BIJUX_HELP_bijux-std-update := Refresh managed content from the selected standard

.PHONY: bijux-std-checks bijux-std-update bijux-std

bijux-std-checks: ## Verify shared directories match the pinned bijux-std commit
	@BIJUX_STD_REF="$(BIJUX_STD_REF)" \
		BIJUX_STD_CAPABILITIES="$(BIJUX_STD_CAPABILITIES)" \
		BIJUX_STD_REMOTE="$(BIJUX_STD_REMOTE)" \
		BIJUX_STD_GIT_URL="$(BIJUX_STD_GIT_URL)" \
		BIJUX_STD_REQUIRE_REMOTE_MATCH="$(BIJUX_STD_REQUIRE_REMOTE_MATCH)" \
		BIJUX_STD_STRICT_REMOTE="$(BIJUX_STD_STRICT_REMOTE)" \
		bash "$(BIJUX_STD_CHECK_SCRIPT)"

bijux-std-update: ## Refresh shared directories from the selected bijux-std commit
	@BIJUX_STD_REF="$(BIJUX_STD_REF)" \
		BIJUX_STD_CAPABILITIES="$(BIJUX_STD_CAPABILITIES)" \
		BIJUX_STD_GIT_URL="$(BIJUX_STD_GIT_URL)" \
		BIJUX_STD_UPDATE_CHANNEL="$(BIJUX_STD_UPDATE_CHANNEL)" \
		BIJUX_STD_TAG_PATTERN="$(BIJUX_STD_TAG_PATTERN)" \
		bash "$(BIJUX_STD_UPDATE_SCRIPT)"

bijux-std: bijux-std-checks ## Verify synchronized standards
