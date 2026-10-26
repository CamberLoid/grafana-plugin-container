# Grafana Plugin Container

English | [简体中文](readme.zh-cn.md)

Package Grafana plugins defined in one or more root-level `xxx.list` files into BusyBox container images, then publish them to GHCR or as `tar.gz` assets in GitHub Releases. The entire process runs in GitHub Actions.

Each list produces a container image with plugins stored under `/opt/plugins`.

The default target platform is `linux-amd64`.

## Usage

1. Mark this repository as a **Template repository**, then select **Use this template** to create your own repository.
2. Copy or edit the root-level `example.list`, for example as `production.list`. Delete `example.list` if you do not need the example image.
3. Commit your changes to the default branch. Actions publishes images for the corresponding lists. To rebuild all lists manually, select **Actions → Build plugin bundles → Run workflow**.

To disable GHCR publishing, create an empty `.no-ghcr` file in the repository root. To disable Release publishing, create an empty `.no-release` file.

Changing the target architecture is not currently supported.

## Artifacts

- Container images: `<list-name>:YYYY-MM-DD` and `<list-name>:YYYY-MM-DD-<hash>`, published to GHCR or GitHub Enterprise Cloud Packages.
- Container image tarballs: `<list-name>-YYYY-MM-DD.tar.gz` and `<list-name>-YYYY-MM-DD-<hash>.tar.gz`, attached to Release `YYYY-MM-DD-<hash>`.

Dates use UTC. `<hash>` is the first seven characters of the source commit SHA. The full image name is `<registry>/<owner>/<repo>/<list-name>:<tag>`. GitHub.com uses `ghcr.io`; GitHub Enterprise Cloud instances with data residency and GHES use `containers.<instance-domain>`.

## List Format

- Comments beginning with `#`.
- Grafana plugin IDs: `grafana-github-datasource` or `grafana-github-datasource 2.9.4`.
- Grafana plugin page URLs: `https://grafana.com/grafana/plugins/grafana-github-datasource/`.
- HTTP(S) URLs pointing to plugin ZIP or TAR archives, including `.tar.gz` files.

See [example.list](example.list).

Plugin IDs and page URLs prefer the `linux-amd64` package.

## Notes

### Empty Lists

If a list contains no plugin entries, an `.empty-plugins` file is created under `/opt/plugins`.

### CI/CD Behavior

- Pushes to the default branch rebuild only changed root-level lists. Changes to the Dockerfile, scripts, workflow, or publishing switches rebuild all lists. Manual runs also rebuild all lists. Deleting a list does not delete historical artifacts.
- Both GHCR and Release publishing are enabled by default.
- All selected lists finish building locally before publishing starts. Each Release contains only the lists selected for that run; trigger a manual run for a complete bundle set. If GHCR publishing fails, the workflow still attempts to publish the built Release archives, while retaining its failed status.
- A new Release starts as a draft and is published only after all assets upload successfully. Failed runs can be retried, reusing the same Release and replacing assets with matching names.
- GitHub Enterprise Cloud uses hosted runners by default; GHES uses Linux self-hosted runners. Override this with the `RUNNER_LABELS` repository variable, specified as a JSON array. Runners need Git, Python 3, curl, Docker, gzip, and `gh` when Release publishing is enabled, plus network access to plugin sources and the BusyBox image registry. Publishing uses the current instance's `GITHUB_TOKEN`. GHES must have Container Registry enabled unless publishing only to Releases.

### Tests

The tests were generated entirely by an LLM and have not been reviewed.

## Disclaimer

This repository was generated using OpenAI Codex and reviewed by its maintainer.
