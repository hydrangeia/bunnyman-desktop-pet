"""Build a portable Windows onedir bundle from a local manifest and its assets.

This script intentionally packages only files referenced by the manifest. It
does not extract game archives or infer assets from the contents of ``frames``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from importlib import metadata
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
APP_NAME = "BunnymanDesktopPet"
IMAGE_SUFFIXES = {".png", ".webp"}
HIDDEN_IMPORTS = (
    "action_controller",
    "interaction_policy",
    "snap_geometry",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
)
DROP_KEYS = {"game_directory", "game_dir"}
ABSOLUTE_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+[\\/])")


class BuildError(RuntimeError):
    """A user-actionable build or manifest validation error."""


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _strings(child)


def _walk_named_values(value: Any, names: set[str]) -> Iterable[Any]:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in names:
                yield child
            else:
                yield from _walk_named_values(child, names)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_named_values(child, names)


def manifest_media_references(manifest: dict[str, Any]) -> list[str]:
    """Collect frame and prop paths, without treating source archive names as assets."""
    candidates: list[str] = []
    for section in (manifest.get("animations", {}), manifest.get("effects", {})):
        for frames in _walk_named_values(section, {"frames"}):
            candidates.extend(_strings(frames))
    for path_value in _walk_named_values(manifest.get("props", {}), {"path"}):
        candidates.extend(_strings(path_value))
    for path_value in _walk_named_values(manifest.get("effects", {}), {"path"}):
        candidates.extend(_strings(path_value))

    refs: dict[str, str] = {}
    for raw in candidates:
        suffix = PurePosixPath(raw.replace("\\", "/")).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise BuildError(f"Unsupported referenced image type: {raw}")
        normalized = _normalize_relative_reference(raw)
        refs.setdefault(normalized.casefold(), normalized)
    return sorted(refs.values(), key=str.casefold)


def _normalize_relative_reference(raw: str) -> str:
    windows = PureWindowsPath(raw)
    posix = PurePosixPath(raw.replace("\\", "/"))
    if windows.is_absolute() or posix.is_absolute() or windows.drive:
        raise BuildError(f"Asset references must be relative to the manifest: {raw}")
    if any(part in {"..", ""} for part in posix.parts):
        raise BuildError(f"Unsafe asset reference: {raw}")
    if not posix.parts:
        raise BuildError("Empty asset reference in manifest")
    return posix.as_posix()


def _is_machine_path(value: str) -> bool:
    return bool(ABSOLUTE_PATH_PATTERN.search(value)) or Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


_DROP = object()


def sanitize_manifest(value: Any) -> Any:
    """Remove local machine paths while preserving relative source metadata."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            if str(key).lower() in DROP_KEYS:
                continue
            safe_child = sanitize_manifest(child)
            if safe_child is not _DROP:
                cleaned[str(key)] = safe_child
        return cleaned
    if isinstance(value, list):
        return [safe for child in value if (safe := sanitize_manifest(child)) is not _DROP]
    if isinstance(value, str) and _is_machine_path(value):
        return _DROP
    return value


def read_and_validate_manifest(manifest_path: Path) -> tuple[dict[str, Any], list[tuple[str, Path]]]:
    manifest_path = manifest_path.expanduser().resolve()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"Could not read manifest {manifest_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BuildError("manifest.json must contain a JSON object")

    references = manifest_media_references(raw)
    assets: list[tuple[str, Path]] = []
    root = manifest_path.parent.resolve()
    for relative in references:
        path = (root / Path(*PurePosixPath(relative).parts)).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise BuildError(f"Asset resolves outside the manifest folder: {relative}") from exc
        if not path.is_file():
            raise BuildError(f"Manifest asset is missing: {relative}")
        assets.append((relative, path))

    cleaned = sanitize_manifest(raw)
    if not isinstance(cleaned, dict):
        raise BuildError("Sanitized manifest is not a JSON object")
    return cleaned, assets


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_remove(path: Path, allowed_parent: Path) -> None:
    path = path.resolve()
    allowed_parent = allowed_parent.resolve()
    if path == allowed_parent or not _inside(path, allowed_parent):
        raise BuildError(f"Refusing to remove a directory outside build output: {path}")
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _copy_release_data(app_dir: Path, manifest: dict[str, Any], assets: list[tuple[str, Path]]) -> None:
    (app_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for relative, source in assets:
        target = app_dir.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for filename in ("README.md", "README.en.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "app.ico"):
        source = ROOT / filename
        if source.is_file():
            shutil.copy2(source, app_dir / filename)
    _copy_third_party_licenses(app_dir)


def _conda_runtime_binaries(base_prefix: Path | None = None) -> list[Path]:
    """Return Conda's libffi DLL when the active Python build requires it."""
    prefix = Path(base_prefix or sys.base_prefix)
    candidate = prefix / "Library" / "bin" / "ffi.dll"
    return [candidate] if candidate.is_file() else []


def _is_license_text_path(package_path: str) -> bool:
    path = PurePosixPath(package_path.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return False
    name = path.name.casefold()
    suffix = PurePosixPath(name).suffix
    text_suffixes = {"", ".txt", ".md", ".rst", ".license"}
    if suffix not in text_suffixes:
        return False
    has_license_dir = any(part.casefold() in {"license", "licenses"} for part in path.parts[:-1])
    named_license = re.match(r"^(license|licence|copying|copyright|notice|lgpl|gpl)(?:$|[._ -])", name)
    return bool(named_license or has_license_dir)


def _copy_third_party_licenses(app_dir: Path) -> None:
    """Keep dependency-provided license texts and Python's license in the bundle."""
    destination_root = app_dir / "THIRD_PARTY_LICENSES"

    # Qt's Python wheels expose the license expression in metadata but only ship
    # the commercial-license reference text. Include the corresponding common
    # LGPL/GPL texts as static files from the GNU licenses, kept in the source.
    static_licenses = ROOT / "THIRD_PARTY_LICENSES"
    if static_licenses.is_dir():
        for source in static_licenses.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(static_licenses)
            if not _is_license_text_path(relative.as_posix()):
                continue
            target = destination_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    package_names = (
        "PySide6-Essentials",
        "shiboken6",
        "numpy",
        "Pillow",
        "PyInstaller",
        "pyinstaller-hooks-contrib",
    )
    for package_name in package_names:
        try:
            distribution = metadata.distribution(package_name)
        except metadata.PackageNotFoundError:
            raise BuildError(f"Required build package has no installed license metadata: {package_name}")
        distribution_name = str(distribution.metadata.get("Name", package_name))
        safe_distribution_name = re.sub(r"[^A-Za-z0-9.-]+", "-", distribution_name.replace("_", "-"))
        for package_file in distribution.files or ():
            package_relative = PurePosixPath(str(package_file).replace("\\", "/"))
            if not _is_license_text_path(package_relative.as_posix()):
                continue
            source = Path(distribution.locate_file(package_file))
            if not source.is_file():
                continue
            short_parts = tuple(
                part for part in package_relative.parts
                if not part.casefold().endswith(".dist-info") and part.casefold() != "licenses"
            )
            target = destination_root / safe_distribution_name / Path(*short_parts)
            source_bytes = source.read_bytes()
            if target.exists() and target.read_bytes() != source_bytes:
                # Preserve distinct texts with the shortest useful parent name.
                parent_name = next(
                    (part for part in reversed(package_relative.parts[:-1])
                     if not part.casefold().endswith(".dist-info") and part.casefold() != "licenses"),
                    "license",
                )
                target = target.with_name(f"{parent_name}-{target.name}")
                if target.exists() and target.read_bytes() != source_bytes:
                    target = target.with_name(f"{target.stem}-{hashlib.sha256(source_bytes).hexdigest()[:8]}{target.suffix}")
            if target.is_file() and target.read_bytes() == source_bytes:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    python_prefix = Path(sys.base_prefix)
    python_license = next(
        (python_prefix / name for name in ("LICENSE.txt", "LICENSE_PYTHON.txt", "LICENSE_PSF.txt")
         if (python_prefix / name).is_file()),
        None,
    )
    if python_license is not None:
        target = destination_root / "Python" / python_license.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(python_license, target)


def _zip_bundle(source_dir: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, Path(source_dir.name) / path.relative_to(source_dir))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a portable Windows onedir ZIP from local rendered assets")
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.json", help="local manifest.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist", help="folder for the bundle and ZIP")
    parser.add_argument("--name", default=APP_NAME, help="release folder and executable name")
    parser.add_argument("--console", action="store_true", help="build a console-enabled diagnostic executable")
    parser.add_argument("--dry-run", action="store_true", help="validate manifest assets without building")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.name):
            raise BuildError("Bundle name may contain only letters, numbers, dots, underscores, and hyphens")
        manifest, assets = read_and_validate_manifest(args.manifest)
        total_bytes = sum(path.stat().st_size for _, path in assets)
        if args.dry_run:
            print(json.dumps({"valid": True, "assets": len(assets), "asset_bytes": total_bytes}, indent=2))
            return 0

        output_dir = args.output_dir.expanduser().resolve()
        if output_dir == ROOT or _inside(ROOT, output_dir):
            raise BuildError("Output folder must not contain the source project")
        build_root = ROOT / ".build"
        pyinstaller_dist = build_root / "pyinstaller-dist"
        work_path = build_root / "work"
        spec_path = build_root / "spec"
        build_tmp = build_root / "tmp"
        pyinstaller_config = build_root / "pyi-cache"
        temp_app = pyinstaller_dist / args.name
        final_app = output_dir / args.name
        archive_path = output_dir / f"{args.name}-windows-x64.zip"

        if not _inside(build_root, ROOT):
            raise BuildError("Build cache must stay inside the source project folder")
        build_root.mkdir(parents=True, exist_ok=True)
        for path in (pyinstaller_dist, work_path, spec_path):
            if path.exists():
                _safe_remove(path, build_root)
        for path in (pyinstaller_dist, work_path, spec_path, build_tmp, pyinstaller_config):
            path.mkdir(parents=True, exist_ok=True)

        command = [
            sys.executable,
            "-m",
            "PyInstaller",
            str(ROOT / "launcher.py"),
            "--onedir",
            "--name",
            args.name,
            "--noconfirm",
            "--clean",
            "--distpath",
            str(pyinstaller_dist),
            "--workpath",
            str(work_path),
            "--specpath",
            str(spec_path),
        ]
        command.append("--console" if args.console else "--windowed")
        icon_path = ROOT / "app.ico"
        if icon_path.is_file():
            command.extend(("--icon", str(icon_path)))
        for module in HIDDEN_IMPORTS:
            command.extend(("--hidden-import", module))
        for runtime_binary in _conda_runtime_binaries():
            # Keep Conda's _ctypes dependency in the standard onedir runtime
            # folder; PyInstaller cannot always resolve this DLL from Library/bin.
            command.extend(("--add-binary", f"{runtime_binary};."))
        build_env = os.environ.copy()
        build_env["TEMP"] = str(build_tmp)
        build_env["TMP"] = str(build_tmp)
        build_env["PYINSTALLER_CONFIG_DIR"] = str(pyinstaller_config)
        subprocess.run(command, cwd=ROOT, check=True, env=build_env)
        if not (temp_app / f"{args.name}.exe").is_file():
            raise BuildError(f"PyInstaller did not create {temp_app / (args.name + '.exe')}")
        _copy_release_data(temp_app, manifest, assets)

        output_dir.mkdir(parents=True, exist_ok=True)
        if final_app.exists():
            _safe_remove(final_app, output_dir)
        if archive_path.exists():
            _safe_remove(archive_path, output_dir)
        shutil.copytree(temp_app, final_app)
        _zip_bundle(final_app, archive_path)
        digest = sha256_file(archive_path)
        checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
        checksum_path.write_text(f"{digest}  {archive_path.name}\n", encoding="ascii")
        print(f"Created {final_app}")
        print(f"Created {archive_path} ({total_bytes:,} bytes of referenced media)")
        print(f"SHA-256 {digest} ({checksum_path.name})")
        print("Run BunnymanDesktopPet.exe --smoke-test --test-report smoke-test.json to validate this bundle.")
        return 0
    except (BuildError, subprocess.CalledProcessError, OSError) as exc:
        print(f"Release build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
