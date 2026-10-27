#!/usr/bin/env bash
set -euo pipefail

USE_XZ="${USE_XZ:-true}"
USE_GZ="${USE_GZ:-false}"
docker info >/dev/null
if [[ "$RELEASE_ENABLED" == true ]]; then
  command -v gh >/dev/null
  if [[ "$USE_XZ" == true ]]; then
    command -v xz >/dev/null
  fi
  if [[ "$USE_GZ" == true ]]; then
    command -v gzip >/dev/null
  fi
fi
BUNDLE_BUILD_ROOT=$(mktemp -d "$RUNNER_TEMP/plugin-bundles.XXXXXX")
printf 'root=%s\n' "$BUNDLE_BUILD_ROOT" >> "$GITHUB_OUTPUT"
BUNDLE_DATE=$(date -u +%F)
BUNDLE_VERSION="$BUNDLE_DATE-${GITHUB_SHA:0:7}"
server_host="${GITHUB_SERVER_URL#*://}"
server_host="${server_host%/}"
registry=ghcr.io
if [[ "$server_host" != github.com ]]; then
  registry="containers.$server_host"
fi
repository=$(printf '%s' "$GITHUB_REPOSITORY" | tr '[:upper:]' '[:lower:]')
BUNDLE_IMAGE_PREFIX="$registry/$repository"
{
  printf 'BUNDLE_BUILD_ROOT=%s\n' "$BUNDLE_BUILD_ROOT"
  printf 'BUNDLE_DATE=%s\n' "$BUNDLE_DATE"
  printf 'BUNDLE_VERSION=%s\n' "$BUNDLE_VERSION"
  printf 'BUNDLE_IMAGE_PREFIX=%s\n' "$BUNDLE_IMAGE_PREFIX"
} >> "$GITHUB_ENV"
cp "$LISTS_FILE" "$BUNDLE_BUILD_ROOT/lists.txt"
mkdir -p "$BUNDLE_BUILD_ROOT/artifacts"
printf '| List | Image (linux/amd64) |\n| --- | --- |\n' >> "$GITHUB_STEP_SUMMARY"
while IFS= read -r list; do
  name="${list%.list}"
  context="$BUNDLE_BUILD_ROOT/contexts/$name"
  python3 scripts/prepare_plugins.py "$list" "$context/plugins"
  cp Dockerfile "$context/Dockerfile"
  image="$BUNDLE_IMAGE_PREFIX/$name"
  docker build --platform linux/amd64 \
    --label "org.opencontainers.image.source=$GITHUB_SERVER_URL/$GITHUB_REPOSITORY" \
    --label "org.opencontainers.image.revision=$GITHUB_SHA" \
    --tag "$image:$BUNDLE_DATE" --tag "$image:$BUNDLE_VERSION" "$context"
  if [[ "$RELEASE_ENABLED" == true ]]; then
    # Export once, then compress the same image archive into each selected format.
    archive="$BUNDLE_BUILD_ROOT/artifacts/$name-$BUNDLE_VERSION.tar"
    docker save "$image:$BUNDLE_DATE" "$image:$BUNDLE_VERSION" > "$archive"
    if [[ "$USE_XZ" == true ]]; then
      xz -9 -c "$archive" > "$archive.xz"
      cp "$archive.xz" "$BUNDLE_BUILD_ROOT/artifacts/$name-$BUNDLE_DATE.tar.xz"
    fi
    if [[ "$USE_GZ" == true ]]; then
      gzip -9 -n -c "$archive" > "$archive.gz"
      cp "$archive.gz" "$BUNDLE_BUILD_ROOT/artifacts/$name-$BUNDLE_DATE.tar.gz"
    fi
    if [[ "$USE_XZ" == true || "$USE_GZ" == true ]]; then
      rm -- "$archive"
    else
      cp "$archive" "$BUNDLE_BUILD_ROOT/artifacts/$name-$BUNDLE_DATE.tar"
    fi
  fi
  printf '| `%s` | `%s` |\n' "$list" "$image:$BUNDLE_VERSION" >> "$GITHUB_STEP_SUMMARY"
done < "$BUNDLE_BUILD_ROOT/lists.txt"
