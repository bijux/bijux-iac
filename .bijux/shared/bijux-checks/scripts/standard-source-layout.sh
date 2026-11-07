#!/usr/bin/env bash
# Source ownership follows repository identity and authored layout, not its directory name.
is_standard_source_checkout() {
  local root="$1" remote
  [[ -f "${root}/shared/shared-dir-sha256.txt" && -d "${root}/shared/bijux-checks" ]] || return 1
  remote="$(git -C "${root}" remote get-url origin 2>/dev/null)" || return 1
  case "${remote}" in
    https://github.com/bijux/bijux-std|https://github.com/bijux/bijux-std.git|git@github.com:bijux/bijux-std|git@github.com:bijux/bijux-std.git) return 0 ;;
    *) return 1 ;;
  esac
}
