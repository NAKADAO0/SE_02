"""Build a reproducible, explicitly allowlisted source archive (standard library only)."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import stat
import sys
import tomllib
import zipfile


MAX_BYTES = 200 * 1024 * 1024
ROOT_FILES = {"README.md", "Design.md", "pyproject.toml", ".gitignore", "config.example.toml"}
TREES = {"src", "tests", "examples", "docs", "release"}
EXTENSIONS = {".py", ".md", ".toml", ".json", ".txt"}
BLOCKED = {"private", "runs", ".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "build"}
SECRET_NAME = re.compile(r"(?:^|[_.-])(?:secrets?|credentials?|tokens?|passwords?|api[_-]?keys?)(?:$|[_.-])", re.I)
KEY_MATERIAL = re.compile(rb"(?:sk-[A-Za-z0-9_-]{20,}|-----BEGIN (?:[A-Z ]*PRIVATE KEY)-----|AKIA[A-Z0-9]{16})")


def allowed(relative: Path) -> bool:
    parts = relative.parts
    if any(part.lower() in BLOCKED or part.lower().endswith(".egg-info") for part in parts):
        return False
    if any(".env" in part.lower() or SECRET_NAME.search(part) for part in parts):
        return False
    return (relative.as_posix() in ROOT_FILES
            or relative.as_posix() == "scripts/build_release.py"
            or (len(parts) >= 3 and parts[:2] == ("docs", "screenshots") and relative.suffix.lower() == ".png")
            or (len(parts) >= 5 and parts[:4] == ("src", "se02", "web", "static")
                and relative.suffix.lower() in {".html", ".css", ".js"})
            or (len(parts) > 1 and parts[0] in TREES and relative.suffix.lower() in EXTENSIONS))


def build(project_root: Path, output: Path) -> Path:
    root = project_root.resolve(strict=True)
    files: dict[str, bytes] = {}
    # Do not follow directory links or junctions, even when their targets are internal.
    def visit(directory: Path):
        for path in sorted(directory.iterdir()):
            relative = path.relative_to(root)
            # Resolve every entry before traversal/read: Path.is_junction only
            # exists in 3.12+, but resolve and lstat work on Windows 3.11 too.
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError("Refusing a link outside the project root")
            attributes = getattr(path.lstat(), "st_file_attributes", 0)
            if path.is_symlink() or attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                continue
            if path.is_dir():
                if (relative.parts[0] in TREES | {"scripts"}
                        and not any(p.lower() in BLOCKED or ".env" in p.lower()
                                    or SECRET_NAME.search(p) or p.lower().endswith(".egg-info")
                                    for p in relative.parts)):
                    visit(path)
            elif path.is_file() and allowed(relative) and path.resolve() != output.resolve():
                data = path.read_bytes()
                if KEY_MATERIAL.search(data):
                    raise ValueError(f"Possible key material in {relative.as_posix()}")
                files[relative.as_posix()] = data
    visit(root)
    metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    manifest = {"format_version": 1, "version": metadata["project"]["version"],
                "files": {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                          for name, data in sorted(files.items())}}
    files["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    if sum(map(len, files.values())) >= MAX_BYTES:
        raise ValueError("Source payload must be smaller than 200 MiB")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    payload = buffer.getvalue()
    if len(payload) >= MAX_BYTES:
        raise ValueError("Archive must be smaller than 200 MiB")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}  {output.name}\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output if args.output is not None else args.project_root / "dist" / "SE_02-source.zip"
    try:
        result = build(args.project_root, output)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    print(f"Built {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
