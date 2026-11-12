#!/usr/bin/env python3
"""Build a movable source or data-inclusive ZIP without local secrets or caches."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = "ocean-eddy-explorer"
EXCLUDED_DIRECTORIES = {
    ".git",
    ".venv",
    ".runtime",
    ".aws",
    ".codex",
    ".agents",
    "__pycache__",
    "staticfiles",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def distributable(path):
    if path.is_symlink() or not path.is_file():
        return False
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRECTORIES for part in relative.parts):
        return False
    if path.name.startswith(".env") and not path.name.endswith(".example"):
        return False
    return not (
        path.suffix in {".pyc", ".pyo", ".pickle"}
        or ".sqlite3" in path.name
        or path.name in {".DS_Store", "worker.log"}
    )


def package_files(data_mode):
    files = set()
    for name in (
        "README.md",
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        ".editorconfig",
        ".prettierrc.json",
        ".gitignore",
    ):
        path = ROOT / name
        if distributable(path):
            files.add(path)
    for name in ("method_website", "scripts", "docs", "tests"):
        files.update(
            path
            for path in (ROOT / name).rglob("*")
            if distributable(path)
            and not (ROOT / "method_website" / "data") in path.parents
            and path.suffix not in {".nc", ".tar", ".zip"}
            and not path.name.endswith(".nc.gz")
        )
    assignment = ROOT / "repossitory" / "project_assignment.md"
    if distributable(assignment):
        files.add(assignment)
    for name in (
        "osu_assignment_1993",
        "osu_assignment_1993_2012",
        "presentation_comparison",
    ):
        directory = ROOT / "artifacts" / name
        if directory.exists():
            files.update(path for path in directory.rglob("*") if distributable(path))
    if data_mode != "none":
        data = ROOT / "data"
        pattern = (
            "osu_daily_sla_geovel_1993_v2.nc"
            if data_mode == "demo"
            else "osu_daily_sla_geovel_*_v2.nc"
        )
        daily = sorted(data.glob(pattern))
        if not daily:
            raise ValueError(f"No daily NetCDF files available in {data}.")
        files.update(path for path in daily if distributable(path))
        reference = data / "mean_aviso_field_1993_2012_v2.nc"
        if distributable(reference):
            files.add(reference)
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", choices=("none", "demo", "all"), default="none")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "dist" / f"method-website-{args.data}.zip"
    files = [
        path for path in package_files(args.data) if path.resolve() != output.resolve()
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"format": 1, "data": args.data, "files": {}}
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        for path in files:
            name = path.relative_to(ROOT).as_posix()
            digest = hashlib.sha256()
            entry = zipfile.ZipInfo.from_file(path, arcname=f"{PACKAGE_ROOT}/{name}")
            entry.compress_type = zipfile.ZIP_DEFLATED
            with (
                path.open("rb") as source,
                archive.open(entry, "w") as target,
            ):
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    target.write(chunk)
            manifest["files"][name] = {
                "bytes": path.stat().st_size,
                "sha256": digest.hexdigest(),
            }
        archive.writestr(
            f"{PACKAGE_ROOT}/PACKAGE_MANIFEST.json",
            json.dumps(manifest, indent=2) + "\n",
        )
    digest = hashlib.sha256()
    with output.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{digest.hexdigest()}  {output.name}\n"
    )
    print(
        f"{output.resolve()} ({output.stat().st_size / 1024**2:.1f} MiB; {len(files)} files)"
    )


if __name__ == "__main__":
    main()
