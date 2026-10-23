"""Black-box source delivery checks; no installed package is required."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_release.py"


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.write("pyproject.toml", '[project]\nname="fixture"\nversion="1.2.3"\n')
        for name in ("README.md", "Design.md", ".gitignore", "src/pkg/__init__.py",
                     "tests/test_sample.py", "examples/demo.py", "docs/guide.md",
                     "config.example.toml", "scripts/build_release.py"):
            self.write(name, "# sample\n")
        self.output = self.root / "dist" / "SE_02-source.zip"

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def build(self):
        return subprocess.run([sys.executable, str(SCRIPT), "--project-root", str(self.root),
                               "--output", str(self.output)], capture_output=True, text=True)

    def test_whitelist_manifest_checksum_and_repeatability(self):
        for name in ("unknown.py", "src/pkg/unknown.exe", "docs/.env.production",
                     "docs/settings.env", "docs/private/notes.md", "runs/result.py",
                     "src/pkg/__pycache__/cache.py", "docs/old.zip", "docs/secret.md"):
            self.write(name, "do not distribute")
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        first = self.output.read_bytes()
        with zipfile.ZipFile(self.output) as archive:
            names = set(archive.namelist())
            expected = {"pyproject.toml", "README.md", "Design.md", ".gitignore",
                        "src/pkg/__init__.py", "tests/test_sample.py", "examples/demo.py",
                        "docs/guide.md", "config.example.toml", "scripts/build_release.py"}
            self.assertEqual(names, expected | {"MANIFEST.json"})
            manifest = json.loads(archive.read("MANIFEST.json"))
            self.assertEqual(manifest["version"], "1.2.3")
            self.assertEqual(set(manifest["files"]), expected)
            for name, entry in manifest["files"].items():
                data = archive.read(name)
                self.assertEqual(entry, {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        checksum = self.output.with_suffix(".zip.sha256").read_text().split()[0]
        self.assertEqual(checksum, hashlib.sha256(first).hexdigest())
        self.assertLess(len(first), 200 * 1024 * 1024)
        self.assertEqual(self.build().returncode, 0)
        self.assertEqual(first, self.output.read_bytes())

    def test_rejects_external_symlink(self):
        outside = Path(self.temp.name) / "outside.py"
        outside.write_text("private", encoding="utf-8")
        try:
            (self.root / "src" / "linked.py").symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"Symlink permission unavailable: {exc}")
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_rejects_key_material_in_allowed_file(self):
        self.write("docs/guide.md", "credential = sk-" + "x" * 32)
        self.assertNotEqual(self.build().returncode, 0)
        self.assertFalse(self.output.exists())

    def test_only_documentation_screenshots_are_included(self):
        self.write('docs/screenshots/runtime.png', 'screenshot-fixture')
        self.write('examples/private-image.png', 'not part of source delivery')
        self.assertEqual(self.build().returncode, 0)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIn('docs/screenshots/runtime.png', archive.namelist())
            self.assertNotIn('examples/private-image.png', archive.namelist())

    def test_web_assets_only_from_package_static_directory(self):
        for path in ('src/se02/web/static/index.html', 'src/se02/web/static/styles.css', 'src/se02/web/static/app.js'):
            self.write(path, 'web fixture')
        self.write('docs/unrelated.html', 'not a package resource')
        self.write('examples/unrelated.js', 'not a package resource')
        self.assertEqual(self.build().returncode, 0)
        with zipfile.ZipFile(self.output) as archive:
            self.assertIn('src/se02/web/static/index.html', archive.namelist())
            self.assertIn('src/se02/web/static/styles.css', archive.namelist())
            self.assertIn('src/se02/web/static/app.js', archive.namelist())
            self.assertNotIn('docs/unrelated.html', archive.namelist())
            self.assertNotIn('examples/unrelated.js', archive.namelist())

    @unittest.skipUnless(os.name == "nt", "Windows junction boundary")
    def test_rejects_external_directory_junction(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "leak.py").write_text("private", encoding="utf-8")
        link = self.root / "src" / "linked"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            self.assertNotEqual(self.build().returncode, 0)
            self.assertFalse(self.output.exists())
        finally:
            link.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows junction boundary")
    def test_rejects_external_junction_without_python312_path_api(self):
        outside = Path(self.temp.name) / "outside311"
        outside.mkdir()
        (outside / "leak.py").write_text("private", encoding="utf-8")
        link = self.root / "src" / "linked311"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        wrapper = (
            "import pathlib,runpy,sys; "
            "[delattr(cls,'is_junction') for cls in pathlib.Path.__mro__ "
            "if 'is_junction' in cls.__dict__]; "
            "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
        )
        try:
            result = subprocess.run([sys.executable, "-c", wrapper, str(SCRIPT),
                                     "--project-root", str(self.root), "--output", str(self.output)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("outside the project root", result.stderr)
            self.assertFalse(self.output.exists())
        finally:
            link.rmdir()


if __name__ == "__main__":
    unittest.main()
