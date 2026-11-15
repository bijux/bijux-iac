#!/bin/sh
# Build only the canonical project's internal CI runtime with its ephemeral job token.
set +x
set -eu

fail() { printf '%s\n' "$1" >&2; exit 1; }
[ "${GITLAB_CI:-}" = true ] || fail 'Native GitLab execution is required'
[ "${CI_SERVER_URL:-}" = https://gitlab.com ] || fail 'Canonical GitLab server is required'
[ "${CI_PROJECT_ID:-}" = 88948041 ] || fail 'Canonical project ID is required'
[ "${CI_PROJECT_PATH:-}" = bijux-oss/bijux-std ] || fail 'Canonical project path is required'
[ "${CI_COMMIT_BRANCH:-}" = ci/gitlab-runtime ] || fail 'Only the owned runtime branch may build'
[ "${CI_COMMIT_REF_NAME:-}" = ci/gitlab-runtime ] || fail 'Actual runtime branch identity is required'
[ -z "${CI_MERGE_REQUEST_IID:-}" ] || fail 'Merge requests cannot publish a CI runtime'
case "${CI_PIPELINE_SOURCE:-}" in push|web) ;; *) fail 'Only branch push or explicit web execution may build' ;; esac
[ "${CI_DEBUG_TRACE:-false}" != true ] || fail 'Registry authentication cannot run with debug tracing'
[ "${CI_REGISTRY:-}" = registry.gitlab.com ] || fail 'Canonical project registry is required'
[ "${CI_REGISTRY_IMAGE:-}" = registry.gitlab.com/bijux-oss/bijux-std ] || fail 'Unapproved image destination'
builder_image='moby/buildkit@sha256:ef70e34495a1730a7c8e20e98fedd9fab328efd6ecfb37365ac464aa0627eb58'
[ "${CI_JOB_IMAGE:-}" = "$builder_image" ] || fail 'Exact rootless builder image is required'
for identifier in "${CI_JOB_ID:-}" "${CI_PIPELINE_ID:-}"; do
    case "$identifier" in ''|*[!0-9]*) fail 'Actual positive native execution IDs are required' ;; esac
    [ "$identifier" -gt 0 ] || fail 'Actual positive native execution IDs are required'
done
printf '%s\n' "${CI_COMMIT_SHA:-}" | grep -Eq '^[a-f0-9]{40}$' || fail 'Actual immutable checkout identity is required'
[ "$(pwd -P)" = "${CI_PROJECT_DIR:-}" ] || fail 'The native checkout directory must own this build'
[ "$(git -c "safe.directory=$CI_PROJECT_DIR" rev-parse HEAD)" = "$CI_COMMIT_SHA" ] || fail 'Checkout differs from the native source commit'
git -c "safe.directory=$CI_PROJECT_DIR" diff --quiet HEAD -- shared/bijux-gitlab/runtime/Dockerfile shared/bijux-gitlab/runtime/build.sh \
    || fail 'Runtime source differs from the checked-out commit'
[ -n "${CI_JOB_TOKEN:-}" ] || fail 'Native ephemeral registry authentication is unavailable'

root=$CI_PROJECT_DIR
output="$root/artifacts/runtime-build"
context="$root/shared/bijux-gitlab/runtime"
image_tag="registry.gitlab.com/bijux-oss/bijux-std/ci-runtime:job-$CI_JOB_ID"
umask 077
mkdir -p "$output/auth" "$output/tmp" "$output/run"
export DOCKER_CONFIG="$output/auth"
export TMPDIR="$output/tmp"
export XDG_RUNTIME_DIR="$output/run"
export BUILDKITD_FLAGS="--oci-worker-no-process-sandbox --root $output/state"
dockerfile_sha256=$(sha256sum "$context/Dockerfile" | cut -d ' ' -f 1)
script_sha256=$(sha256sum "$context/build.sh" | cut -d ' ' -f 1)
write_receipt() {
    printf '{"schema_version":1,"purpose":"ci-runtime","status":"%s","server_url":"https://gitlab.com","project_id":88948041,"project_path":"bijux-oss/bijux-std","pipeline_id":%s,"job_id":%s,"commit_sha":"%s","ref":"ci/gitlab-runtime","builder_image":"%s","image_tag":"%s","dockerfile_sha256":"%s","build_script_sha256":"%s","product_release":false%s}\n' \
        "$1" "$CI_PIPELINE_ID" "$CI_JOB_ID" "$CI_COMMIT_SHA" "$builder_image" "$image_tag" \
        "$dockerfile_sha256" "$script_sha256" "${2:-}" > "$output/receipt.json"
}
cleanup() {
    build_status=$?
    if [ -n "${progress_pid:-}" ]; then kill "$progress_pid" 2>/dev/null || true; fi
    rm -f "$output/progress.fifo" "$DOCKER_CONFIG/config.json"
    rmdir "$DOCKER_CONFIG" 2>/dev/null || true
    if [ "$build_status" -ne 0 ]; then write_receipt failed; fi
}
trap cleanup 0
trap 'exit 1' HUP INT TERM
write_receipt building
registry_auth=$(printf 'gitlab-ci-token:%s' "$CI_JOB_TOKEN" | base64 | tr -d '\n')
printf '{"auths":{"registry.gitlab.com":{"auth":"%s"}}}\n' "$registry_auth" > "$DOCKER_CONFIG/config.json"
unset registry_auth
progress_pipe="$output/progress.fifo"
mkfifo "$progress_pipe"
# Registry redirects can contain signed query strings. Keep them out of job logs.
sed -E 's#https?://[^[:space:]]+#<registry-url>#g' < "$progress_pipe" &
progress_pid=$!
if buildctl-daemonless.sh build \
    --frontend dockerfile.v0 \
    --local "context=$context" \
    --local "dockerfile=$context" \
    --opt platform=linux/amd64 \
    --output "type=image,name=$image_tag,push=true,oci-mediatypes=true" \
    --metadata-file "$output/buildkit.json" > "$progress_pipe" 2>&1; then
    build_status=0
else
    build_status=$?
fi
progress_status=0
wait "$progress_pid" || progress_status=$?
progress_pid=''
rm -f "$progress_pipe"
[ "$build_status" -eq 0 ] || exit "$build_status"
[ "$progress_status" -eq 0 ] || exit "$progress_status"
image_digest=$(sed -n 's/.*"containerimage.digest"[[:space:]]*:[[:space:]]*"\(sha256:[a-f0-9]*\)".*/\1/p' "$output/buildkit.json")
printf '%s\n' "$image_digest" | grep -Eq '^sha256:[a-f0-9]{64}$' || fail 'Actual pushed image digest is unavailable'
write_receipt built ",\"image_digest\":\"$image_digest\""
printf 'Built internal CI runtime %s@%s\n' "${image_tag%:*}" "$image_digest"
