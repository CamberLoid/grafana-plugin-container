#!/usr/bin/env bash
set -euo pipefail

# Auth is only available to this phase and never enters a build context.
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d "$RUNNER_TEMP/plugin-registry-auth.XXXXXX")
trap 'rm -rf -- "$DOCKER_CONFIG"' EXIT
registry="${BUNDLE_IMAGE_PREFIX%%/*}"
printf '%s' "$GH_TOKEN" | docker login "$registry" --username "$GITHUB_ACTOR" --password-stdin
unset GH_TOKEN
while IFS= read -r list; do
  image="$BUNDLE_IMAGE_PREFIX/${list%.list}"
  docker push "$image:$BUNDLE_VERSION"
  docker push "$image:$BUNDLE_DATE"
  digest=$(docker image inspect --format '{{index .RepoDigests 0}}' "$image:$BUNDLE_VERSION")
  printf '\nGHCR: `%s`\n' "$digest" >> "$GITHUB_STEP_SUMMARY"
done < "$BUNDLE_BUILD_ROOT/lists.txt"
