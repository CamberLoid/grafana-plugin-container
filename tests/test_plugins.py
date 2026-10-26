import io
import json
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prepare_plugins
from select_lists import select_lists


def plugin_zip(plugin_id="test-panel", prefix="release/", extra=()):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        files = [(prefix + "plugin.json", json.dumps({"id": plugin_id}), 0o644)]
        for name, content, mode in files + list(extra):
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(entry, content)
    return buffer.getvalue()


def plugin_tar(plugin_id="tar-panel", mode="w:gz", extra=()):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as archive:
        root = tarfile.TarInfo("./")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        files = [("./plugin.json", json.dumps({"id": plugin_id}).encode(), 0o644)]
        for name, content, permissions in files + list(extra):
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            entry.mode = permissions
            archive.addfile(entry, io.BytesIO(content))
    return buffer.getvalue()


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "plugins"
        self.output.mkdir()

    def extract(self, contents, expected_id=None):
        archive = self.root / "plugin.zip"
        archive.write_bytes(contents)
        return prepare_plugins.extract_plugin(archive, self.output, expected_id)

    def test_contents_signature_and_executable_permissions_survive(self):
        signature = b"signed contents\r\n"
        payload = plugin_zip(extra=[
            ("release/MANIFEST.txt", signature, 0o644),
            ("release/gpx_test_linux_amd64", b"binary fixture", 0o755),
        ])
        self.assertEqual(self.extract(payload), "test-panel")
        plugin = self.output / "test-panel"
        self.assertEqual((plugin / "MANIFEST.txt").read_bytes(), signature)
        self.assertEqual((plugin / "gpx_test_linux_amd64").stat().st_mode & 0o777, 0o755)

    def test_manifest_at_zip_root_and_nested_app_plugin(self):
        payload = plugin_zip("test-app", prefix="", extra=[
            ("panels/child/plugin.json", '{"id":"child-panel"}', 0o644),
        ])
        self.extract(payload)
        self.assertTrue((self.output / "test-app/panels/child/plugin.json").is_file())

    def test_duplicate_id_fails_instead_of_overlaying_files(self):
        payload = plugin_zip()
        self.extract(payload)
        with self.assertRaisesRegex(ValueError, "duplicate plugin id"):
            self.extract(payload)

    def test_catalog_id_must_match_download(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.extract(plugin_zip(), "different-panel")

    def test_multiple_top_level_plugins_fail(self):
        payload = plugin_zip(extra=[("other/plugin.json", '{"id":"other-panel"}', 0o644)])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.extract(payload)

    def test_zip_paths_cannot_escape_output(self):
        for name in ("../escaped", "/escaped", "release/../../escaped", "release\\escaped"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe ZIP path"):
                self.extract(plugin_zip(extra=[(name, b"bad", 0o644)]))
        self.assertFalse((self.root / "escaped").exists())

    def test_symlinks_and_special_files_fail(self):
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o644):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                entry = zipfile.ZipInfo("link")
                entry.external_attr = mode << 16
                archive.writestr(entry, "../outside")
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "special files"):
                self.extract(buffer.getvalue())

    def test_missing_manifest_and_unsafe_plugin_id_fail(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("README", "not a plugin")
        with self.assertRaisesRegex(ValueError, "does not contain plugin.json"):
            self.extract(buffer.getvalue())
        with self.assertRaisesRegex(ValueError, "valid plugin id"):
            self.extract(plugin_zip("../outside"))

    def test_mixed_list_resolves_catalog_without_grafana_and_keeps_bundles_isolated(self):
        direct = "https://example.invalid/download?version=1"
        catalog = "https://grafana.com/grafana/plugins/catalog-panel/"
        api = "https://grafana.com/api/plugins/catalog-panel"
        resolved = api + "/versions/1.2.3/download?os=linux&arch=amd64"
        responses = {
            direct: plugin_zip("direct-panel"),
            api: json.dumps({"links": [{"rel": "download", "href":
                "/plugins/catalog-panel/versions/1.2.3/download"}]}).encode(),
            resolved: plugin_zip("catalog-panel"),
        }
        source = self.root / "example.list"
        source.write_bytes(("\ufeff# comment\r\n\r\n " + direct + " \r\n" + catalog).encode())
        first = self.root / "first/plugins"
        second = self.root / "second/plugins"
        with patch.object(prepare_plugins, "download", side_effect=lambda url, path: path.write_bytes(responses[url])):
            prepare_plugins.prepare(source, first)
            source.write_text(catalog)
            prepare_plugins.prepare(source, second)
        self.assertEqual(sorted(p.name for p in first.iterdir()), ["catalog-panel", "direct-panel"])
        self.assertEqual([p.name for p in second.iterdir()], ["catalog-panel"])
        with self.assertRaises(FileExistsError):
            prepare_plugins.prepare(source, first)

    def test_empty_list_is_an_empty_bundle(self):
        source = self.root / "empty.list"
        source.write_text("# no plugins\n\n")
        output = self.root / "empty/plugins"
        prepare_plugins.prepare(source, output)
        self.assertEqual([p.name for p in output.iterdir()], [".empty-plugins"])

    def test_tar_and_tar_gz_keep_files_and_executable_permissions(self):
        for plugin_id, mode in (("plain-panel", "w"), ("gzip-panel", "w:gz")):
            with self.subTest(mode=mode):
                self.extract(plugin_tar(plugin_id, mode, extra=[
                    ("./backend", b"backend fixture", 0o755),
                    ("./MANIFEST.txt", b"signature fixture", 0o644),
                ]))
                folder = self.output / plugin_id
                self.assertEqual((folder / "backend").stat().st_mode & 0o777, 0o755)
                self.assertEqual((folder / "MANIFEST.txt").read_bytes(), b"signature fixture")

    def test_tar_paths_and_links_cannot_escape_output(self):
        for name in ("../escaped", "/escaped", "a/../../escaped", "a\\escaped"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe TAR path"):
                self.extract(plugin_tar(extra=[(name, b"bad", 0o644)]))
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
                entry = tarfile.TarInfo("link")
                entry.type = kind
                entry.linkname = "../outside"
                archive.addfile(entry)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "special files"):
                self.extract(buffer.getvalue())

    def test_id_and_pinned_version_choose_linux_amd64_over_any_or_arm64(self):
        for source, suffix in (("catalog-panel", ""), ("catalog-panel 2.9.4", "/versions/2.9.4")):
            metadata = {"packages": {
                "linux-arm64": {"downloadUrl": "/wrong-arm64.zip"},
                "any": {"downloadUrl": "/all-platforms.zip"},
                "linux-amd64": {"downloadUrl": "/correct-amd64.zip"},
            }}
            def fake_download(url, path):
                self.assertEqual(url, "https://grafana.com/api/plugins/catalog-panel" + suffix)
                path.write_text(json.dumps(metadata))
            with patch.object(prepare_plugins, "download", side_effect=fake_download):
                self.assertEqual(prepare_plugins.resolve_url(source, self.root),
                                 ("https://grafana.com/correct-amd64.zip", "catalog-panel"))

    def test_catalog_any_package_and_missing_amd64_package(self):
        for packages, expected in (({"any": {"downloadUrl": "/universal.zip"}}, "https://grafana.com/universal.zip"),
                                   ({"linux-arm64": {"downloadUrl": "/arm64.zip"}}, None)):
            with patch.object(prepare_plugins, "download", side_effect=lambda url, path: path.write_text(json.dumps({"packages": packages}))):
                if expected:
                    self.assertEqual(prepare_plugins.resolve_url("catalog-panel", self.root)[0], expected)
                else:
                    with self.assertRaisesRegex(ValueError, "no linux-amd64 package"):
                        prepare_plugins.resolve_url("catalog-panel", self.root)

    def test_direct_tar_url_is_not_reinterpreted_as_plugin_id(self):
        url = "https://plugins.example.invalid/panel.tar.gz"
        self.assertEqual(prepare_plugins.resolve_url(url, self.root), (url, None))
        with self.assertRaisesRegex(ValueError, "optional version"):
            prepare_plugins.resolve_url("catalog-panel 1.0 extra-field", self.root)

    def test_invalid_downloads_fail_with_list_line_number(self):
        source = self.root / "bad.list"
        source.write_text("# comment\nhttps://example.invalid/plugin.zip\n")
        for response in (ValueError("download failed"), b"this is HTML, not ZIP"):
            with self.subTest(response=response):
                destination = self.root / ("output-" + str(len(list(self.root.iterdir()))))
                def fake_download(url, path):
                    if isinstance(response, Exception):
                        raise response
                    path.write_bytes(response)
                with patch.object(prepare_plugins, "download", side_effect=fake_download):
                    with self.assertRaisesRegex(ValueError, r"bad\.list:2:"):
                        prepare_plugins.prepare(source, destination)

    def test_local_schemes_and_url_credentials_are_rejected_before_curl(self):
        for url in ("file:///etc/passwd", "https://user:secret@example.invalid/a.zip"):
            with patch.object(prepare_plugins.subprocess, "run") as run:
                with self.subTest(url=url), self.assertRaises(ValueError):
                    prepare_plugins.download(url, self.root / "unused")
                run.assert_not_called()


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        for name in ("a.list", "b.list"):
            (self.root / name).write_text("# initial\n")
        self.before = self.commit()

    def git(self, *args):
        # Fixture commits must not use the developer's signing keys or hooks.
        return subprocess.check_output([
            "git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
            "-C", str(self.root), *args,
        ], text=True).strip()

    def commit(self):
        self.git("add", ".")
        self.git("-c", "user.name=Tests", "-c", "user.email=tests@example.invalid", "commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def test_only_changed_root_lists_are_selected_across_multiple_commits(self):
        (self.root / "a.list").write_text("# changed\n")
        self.commit()
        (self.root / "nested").mkdir()
        (self.root / "nested/ignored.list").write_text("# ignored\n")
        self.commit()
        self.assertEqual(select_lists(self.root, self.before), ["a.list"])

    def test_renamed_and_deleted_lists(self):
        (self.root / "a.list").rename(self.root / "renamed.list")
        (self.root / "b.list").unlink()
        self.commit()
        self.assertEqual(select_lists(self.root, self.before), ["renamed.list"])

    def test_shared_build_changes_and_manual_dispatch_select_every_list(self):
        (self.root / "scripts").mkdir()
        (self.root / "scripts/prepare_plugins.py").write_text("# changed\n")
        self.commit()
        self.assertEqual(select_lists(self.root, self.before), ["a.list", "b.list"])
        self.assertEqual(select_lists(self.root, self.before, manual=True), ["a.list", "b.list"])

    def test_adding_or_removing_either_publish_switch_rebuilds_all_lists(self):
        for name in (".no-ghcr", ".no-release"):
            before = self.git("rev-parse", "HEAD")
            (self.root / name).touch()
            added = self.commit()
            self.assertEqual(select_lists(self.root, before), ["a.list", "b.list"])
            (self.root / name).unlink()
            self.commit()
            self.assertEqual(select_lists(self.root, added), ["a.list", "b.list"])

    def test_image_names_reject_trailing_or_repeated_dot_separators(self):
        for name in ("bad..name.list", "bad-.list", "bad_.list"):
            path = self.root / name
            path.touch()
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Docker image names"):
                select_lists(self.root, "", manual=True)
            path.unlink()

    def test_bootstrap_or_missing_before_commit_selects_every_list(self):
        for before in ("", "0" * 40, "f" * 40):
            with self.subTest(before=before):
                self.assertEqual(select_lists(self.root, before), ["a.list", "b.list"])

    def test_docs_only_changes_do_not_publish(self):
        (self.root / "README.md").write_text("docs\n")
        self.commit()
        self.assertEqual(select_lists(self.root, self.before), [])

    def test_invalid_names_and_list_symlinks_fail(self):
        (self.root / "Uppercase.list").write_text("# invalid name\n")
        with self.assertRaisesRegex(ValueError, "list names"):
            select_lists(self.root, "", manual=True)
        (self.root / "Uppercase.list").unlink()
        (self.root / "link.list").symlink_to(self.root / "a.list")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            select_lists(self.root, "", manual=True)


if __name__ == "__main__":
    unittest.main()
