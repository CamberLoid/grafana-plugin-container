"""Exercise the actual delivery phases with local Docker/gh stand-ins; no publication."""

import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile


SOURCE = Path(__file__).resolve().parents[1]


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copytree(SOURCE / "scripts", self.root / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copyfile(SOURCE / "Dockerfile", self.root / "Dockerfile")
        (self.root / "bundle.list").write_text("https://example.invalid/plugin.zip\n")
        (self.root / "empty.list").write_text("# intentionally empty\n")
        (self.root / "bin").mkdir()
        (self.root / "runner").mkdir()
        with zipfile.ZipFile(self.root / "fixture.zip", "w") as archive:
            archive.writestr("fixture/plugin.json", '{"id":"fixture-panel"}')
        self.tool("date", "print('2026-10-26')")
        self.tool("curl", """
import shutil
a = sys.argv[1:]
shutil.copyfile('fixture.zip', a[a.index('--output') + 1])
""")
        self.tool("docker", """
import io, tarfile
a = sys.argv[1:]
record = {'tool': 'docker', 'args': a}
if a[0] == 'login':
    assert sys.stdin.read() == 'synthetic-fixture'
    config = Path(os.environ['DOCKER_CONFIG'])
    (config / 'config.json').write_text('{}')
    record['config'] = str(config)
elif a[0] == 'build':
    assert 'GH_TOKEN' not in os.environ
    assert a[a.index('--platform') + 1] == 'linux/amd64'
    context = Path(a[-1])
    assert sorted(p.name for p in context.iterdir()) == ['Dockerfile', 'plugins']
    record['files'] = sorted(str(p.relative_to(context)) for p in context.rglob('*') if p.is_file())
elif a[0] == 'save':
    manifest = json.dumps([{'RepoTags': a[1:]}]).encode()
    with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
        entry = tarfile.TarInfo('manifest.json')
        entry.size = len(manifest)
        archive.addfile(entry, io.BytesIO(manifest))
elif a[:2] == ['image', 'inspect']:
    print(a[-1].rsplit(':', 1)[0] + '@sha256:' + '1' * 64)
elif a[0] not in ('push', 'info'):
    raise AssertionError(a)
with open('calls.jsonl', 'a') as log:
    print(json.dumps(record), file=log)
if a[0] == 'push' and os.environ.get('FAIL_PUSH'):
    sys.exit(1)
""")
        self.tool("gh", """
a = sys.argv[1:]
record = {'tool': 'gh', 'args': a, 'host': os.environ['GH_HOST'],
          'enterprise_auth': bool(os.environ.get('GH_ENTERPRISE_TOKEN'))}
assert os.environ['GH_TOKEN'] == 'synthetic-fixture'
state_path = Path('release-state.json')
state = json.loads(state_path.read_text()) if state_path.exists() else {'exists': False, 'draft': True, 'assets': []}
command = a[1]
status = 0
if command == 'view':
    status = 0 if state['exists'] else 1
elif command == 'create':
    assert '--draft' in a and a[a.index('--target') + 1] == os.environ['GITHUB_SHA']
    assert not state['exists']
    state['exists'] = True
elif command == 'upload':
    assert '--clobber' in a
    if os.environ.get('FAIL_UPLOAD'):
        status = 1
    else:
        state['assets'] = sorted(Path(p).name for p in a[3:a.index('--repo')])
elif command == 'edit':
    assert '--draft=false' in a
    state['draft'] = False
else:
    raise AssertionError(a)
state_path.write_text(json.dumps(state))
with open('calls.jsonl', 'a') as log:
    print(json.dumps(record), file=log)
sys.exit(status)
""")
        self.env = dict(os.environ)
        for key in ("GH_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
            self.env.pop(key, None)
        self.env.update({
            "PATH": str(self.root / "bin") + os.pathsep + os.environ["PATH"],
            "RUNNER_TEMP": str(self.root / "runner"),
            "GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "Acme/Plugins",
            "GITHUB_SHA": "abcdef0123456789abcdef0123456789abcdef01",
            "GITHUB_ACTOR": "fixture", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_OUTPUT": str(self.root / "outputs"), "GITHUB_ENV": str(self.root / "env"),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
            "LISTS_FILE": str(self.root / "lists"),
        })

    def tool(self, name, body):
        path = self.root / "bin" / name
        path.write_text("#!/usr/bin/env python3\nimport json, os, sys\nfrom pathlib import Path\n" + body)
        path.chmod(0o755)

    def select(self, ghcr=True, release=True):
        for name, enabled in ((".no-ghcr", ghcr), (".no-release", release)):
            path = self.root / name
            if enabled:
                path.unlink(missing_ok=True)
            else:
                path.touch()
        subprocess.run(["python3", "scripts/select_lists.py"], cwd=self.root, env=self.env, check=True, capture_output=True)
        outputs = dict(line.split("=", 1) for line in (self.root / "outputs").read_text().splitlines())
        self.assertEqual(outputs["ghcr"], str(ghcr).lower())
        self.assertEqual(outputs["release"], str(release).lower())
        self.env["RELEASE_ENABLED"] = outputs["release"]
        return ghcr or release

    def phase(self, name, check=True):
        env = dict(self.env)
        if name != "build":
            env["GH_TOKEN"] = "synthetic-fixture"
        result = subprocess.run(["bash", "scripts/{}.sh".format(name)], cwd=self.root,
                                env=env, capture_output=True, text=True)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if name == "build" and result.returncode == 0:
            self.env.update(line.split("=", 1) for line in (self.root / "env").read_text().splitlines())
        return result

    def calls(self, tool):
        path = self.root / "calls.jsonl"
        return [r for r in (json.loads(line) for line in path.read_text().splitlines()) if r["tool"] == tool] if path.exists() else []

    def test_default_builds_amd64_and_publishes_two_tags_and_four_archives(self):
        self.select()
        self.phase("build")
        self.phase("ghcr")
        self.phase("release")
        artifacts = Path(self.env["BUNDLE_BUILD_ROOT"]) / "artifacts"
        self.assertEqual(sorted(p.name for p in artifacts.iterdir()), [
            "bundle-2026-10-26-abcdef0.tar.gz", "bundle-2026-10-26.tar.gz",
            "empty-2026-10-26-abcdef0.tar.gz", "empty-2026-10-26.tar.gz",
        ])
        first = artifacts / "bundle-2026-10-26-abcdef0.tar.gz"
        self.assertEqual(first.read_bytes(), (artifacts / "bundle-2026-10-26.tar.gz").read_bytes())
        with gzip.open(first, "rb") as compressed, tarfile.open(fileobj=compressed) as archive:
            tags = json.load(archive.extractfile("manifest.json"))[0]["RepoTags"]
        self.assertEqual(tags, ["ghcr.io/acme/plugins/bundle:2026-10-26", "ghcr.io/acme/plugins/bundle:2026-10-26-abcdef0"])
        builds = [r for r in self.calls("docker") if r["args"][0] == "build"]
        self.assertIn("plugins/.empty-plugins", builds[1]["files"])
        login = next(r for r in self.calls("docker") if r["args"][0] == "login")
        self.assertFalse(Path(login["config"]).exists())
        self.assertFalse(json.loads((self.root / "release-state.json").read_text())["draft"])

    def test_ghcr_only_does_not_save_or_create_release(self):
        self.select(release=False)
        self.phase("build")
        self.phase("ghcr")
        self.assertFalse(any(r["args"][0] == "save" for r in self.calls("docker")))
        self.assertEqual(self.calls("gh"), [])

    def test_release_only_does_not_login_or_push(self):
        self.select(ghcr=False)
        self.phase("build")
        self.phase("release")
        self.assertFalse(any(r["args"][0] in ("login", "push") for r in self.calls("docker")))

    def test_both_disabled_selects_no_delivery(self):
        self.assertFalse(self.select(ghcr=False, release=False))
        self.assertEqual(self.calls("docker"), [])
        self.assertEqual(self.calls("gh"), [])

    def test_ghes_and_cloud_data_residency_use_the_current_host(self):
        for host, enterprise_auth in (("git.example.invalid", True), ("acme.ghe.com", False)):
            with self.subTest(host=host):
                self.env["GITHUB_SERVER_URL"] = "https://" + host
                self.select()
                self.phase("build")
                self.phase("ghcr")
                self.phase("release")
                self.assertEqual(self.env["BUNDLE_IMAGE_PREFIX"], "containers." + host + "/acme/plugins")
                last = self.calls("gh")[-1]
                self.assertEqual(last["host"], host)
                self.assertEqual(last["enterprise_auth"], enterprise_auth)

    def test_failed_ghcr_can_still_deliver_release_and_cleans_auth(self):
        self.select()
        self.phase("build")
        self.env["FAIL_PUSH"] = "1"
        self.assertNotEqual(self.phase("ghcr", check=False).returncode, 0)
        self.phase("release")
        login = next(r for r in self.calls("docker") if r["args"][0] == "login")
        self.assertFalse(Path(login["config"]).exists())
        self.assertFalse(json.loads((self.root / "release-state.json").read_text())["draft"])

    def test_failed_upload_stays_draft_and_rerun_resumes_same_release(self):
        self.select(ghcr=False)
        self.phase("build")
        self.env["FAIL_UPLOAD"] = "1"
        self.assertNotEqual(self.phase("release", check=False).returncode, 0)
        self.assertTrue(json.loads((self.root / "release-state.json").read_text())["draft"])
        self.env.pop("FAIL_UPLOAD")
        self.phase("release")
        self.phase("release")
        state = json.loads((self.root / "release-state.json").read_text())
        self.assertFalse(state["draft"])
        self.assertEqual(len(state["assets"]), 4)
        self.assertEqual(sum(r["args"][1] == "create" for r in self.calls("gh")), 1)


if __name__ == "__main__":
    unittest.main()
