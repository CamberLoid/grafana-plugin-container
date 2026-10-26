#!/usr/bin/env bash
set -euo pipefail

export GH_HOST="${GITHUB_SERVER_URL#*://}"
GH_HOST="${GH_HOST%/}"
if [[ "$GH_HOST" != github.com && "$GH_HOST" != *.ghe.com ]]; then
  export GH_ENTERPRISE_TOKEN="$GH_TOKEN"
fi
repo="$GH_HOST/$GITHUB_REPOSITORY"
# Publish a new release only after all assets upload; reruns resume by tag.
if ! gh release view "$BUNDLE_VERSION" --repo "$repo" >/dev/null 2>&1; then
  gh release create "$BUNDLE_VERSION" --repo "$repo" --target "$GITHUB_SHA" \
    --title "$BUNDLE_VERSION" --draft \
    --notes "linux/amd64 plugin container images. Source: $GITHUB_SHA. Import tar.gz assets with docker load."
fi
gh release upload "$BUNDLE_VERSION" "$BUNDLE_BUILD_ROOT"/artifacts/*.tar.gz \
  --repo "$repo" --clobber
gh release edit "$BUNDLE_VERSION" --repo "$repo" --draft=false
printf '\nRelease: %s/%s/releases/tag/%s\n' \
  "$GITHUB_SERVER_URL" "$GITHUB_REPOSITORY" "$BUNDLE_VERSION" >> "$GITHUB_STEP_SUMMARY"
