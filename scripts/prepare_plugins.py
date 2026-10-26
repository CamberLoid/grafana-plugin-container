#!/usr/bin/env python3
"""Prepare linux-amd64 plugins from IDs, catalog pages, ZIPs or TAR archives."""

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from urllib.parse import urljoin, urlsplit
import zipfile


PLUGIN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
CATALOG_PATH = re.compile(r"/grafana/plugins/([a-z0-9][a-z0-9-]*)/?")
PLUGIN_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")


def download(url, destination):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("expected an HTTP(S) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("credentials in URLs are not supported")
    # Use the runner's curl and CA trust; no dependency on Grafana or Python TLS setup.
    result = subprocess.run(
        [
            "curl", "--fail", "--location", "--silent", "--show-error",
            "--globoff", "--retry", "3", "--connect-timeout", "15",
            "--max-time", "300", "--proto", "=http,https",
            "--proto-redir", "=http,https", "--output", str(destination),
            "--url", url,
        ],
        capture_output=True,
    )
    if result.returncode:
        raise ValueError("download failed (curl exit code {})".format(result.returncode))


def resolve_url(source, workdir):
    fields = source.split()
    parsed = urlsplit(source)
    match = CATALOG_PATH.fullmatch(parsed.path)
    version = None
    if fields and PLUGIN_ID.fullmatch(fields[0]):
        if len(fields) > 2 or (len(fields) == 2 and not PLUGIN_VERSION.fullmatch(fields[1])):
            raise ValueError("expected a plugin id with an optional version")
        plugin_id = fields[0]
        version = fields[1] if len(fields) == 2 else None
    elif parsed.hostname in ("grafana.com", "www.grafana.com") and match:
        if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None:
            raise ValueError("Grafana plugin pages must use HTTPS without credentials")
        plugin_id = match.group(1)
    else:
        return source, None
    api_url = "https://grafana.com/api/plugins/" + plugin_id
    if version:
        api_url += "/versions/" + version
    metadata_path = workdir / "metadata.json"
    download(api_url, metadata_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    packages = metadata.get("packages", {})
    if packages:
        package = packages.get("linux-amd64") or packages.get("any")
        if not package or not package.get("downloadUrl"):
            raise ValueError("plugin has no linux-amd64 package")
        href = package["downloadUrl"]
    else:
        href = next((link.get("href") for link in metadata.get("links", [])
                     if link.get("rel") == "download" and link.get("href")), None)
        if not href:
            raise ValueError("Grafana catalog did not provide a download link")
        href += ("&" if "?" in href else "?") + "os=linux&arch=amd64"
    # Some metadata links are relative to /api rather than the site root.
    if href.startswith("/plugins/"):
        href = "/api" + href
    return urljoin("https://grafana.com/", href), plugin_id


def extract_plugin(archive_path, output, expected_id=None):
    if zipfile.is_zipfile(archive_path):
        with zipfile.ZipFile(archive_path) as archive:
            members = []
            for entry in archive.infolist():
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise ValueError("ZIP links and special files are not supported")
                members.append((entry.filename, entry.is_dir(), mode & 0o777, entry))
            return extract_members(members, archive.open, output, expected_id, "ZIP")
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            members = []
            for entry in archive.getmembers():
                if not (entry.isfile() or entry.isdir()):
                    raise ValueError("TAR links and special files are not supported")
                members.append((entry.name, entry.isdir(), entry.mode & 0o777, entry))
            return extract_members(members, archive.extractfile, output, expected_id, "TAR")
    except tarfile.ReadError as error:
        raise ValueError("expected a plugin ZIP or TAR archive") from error


def extract_members(members, open_member, output, expected_id, archive_type):
    entries = {}
    for name, is_dir, mode, member in members:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or (not path.parts and not is_dir):
            raise ValueError("unsafe {} path: {!r}".format(archive_type, name))
        if not path.parts:  # tar -C plugin -czf plugin.tar.gz . includes a ./ directory.
            continue
        if path in entries:
            raise ValueError("duplicate {} path: {!r}".format(archive_type, name))
        entries[path] = (is_dir, mode, member)
    manifests = [p for p, (is_dir, _, _) in entries.items() if p.name == "plugin.json" and not is_dir]
    if not manifests:
        raise ValueError(archive_type + " does not contain plugin.json")
    # App plugins can contain nested plugins. Only the outermost manifest is the bundle root.
    depth = min(len(p.parts) for p in manifests)
    roots = [p for p in manifests if len(p.parts) == depth]
    if len(roots) != 1:
        raise ValueError(archive_type + " must contain exactly one top-level plugin")
    manifest = roots[0]
    with open_member(entries[manifest][2]) as source:
        metadata = json.load(source)
    plugin_id = metadata.get("id") if isinstance(metadata, dict) else None
    if not isinstance(plugin_id, str) or not PLUGIN_ID.fullmatch(plugin_id):
        raise ValueError("plugin.json must contain a valid plugin id")
    if expected_id is not None and plugin_id != expected_id:
        raise ValueError("downloaded plugin id does not match the Grafana page")
    destination = output / plugin_id
    if destination.exists():
        raise ValueError("duplicate plugin id: " + plugin_id)
    destination.mkdir()
    for path, (is_dir, mode, member) in entries.items():
        try:
            relative = path.relative_to(manifest.parent)
        except ValueError:
            continue
        target = destination.joinpath(*relative.parts)
        if is_dir:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open_member(member) as source, target.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            # Standard extractors can drop executable bits; retain ordinary Unix modes.
            target.chmod(mode or 0o644)
    return plugin_id


def prepare(list_path, output):
    # A fresh output directory prevents removed plugins surviving a later build.
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="grafana-plugin-download-") as directory:
        workdir = Path(directory)
        for number, line in enumerate(list_path.read_text(encoding="utf-8-sig").splitlines(), 1):
            url = line.strip()
            if not url or url.startswith("#"):
                continue
            try:
                archive_url, expected_id = resolve_url(url, workdir)
                archive_path = workdir / "plugin.archive"
                download(archive_url, archive_path)
                plugin_id = extract_plugin(archive_path, output, expected_id)
            except (ValueError, OSError, zipfile.BadZipFile, tarfile.TarError) as error:
                raise ValueError("{}:{}: {}".format(list_path.name, number, error)) from error
            print("Prepared " + plugin_id)
    if not any(output.iterdir()):
        (output / ".empty-plugins").touch()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("list", type=Path, help="plugin list to package")
    parser.add_argument("output", type=Path, help="fresh output plugins directory")
    args = parser.parse_args()
    try:
        prepare(args.list, args.output)
    except (ValueError, OSError, zipfile.BadZipFile, tarfile.TarError) as error:
        parser.exit(1, "error: {}\n".format(error))


if __name__ == "__main__":
    main()
