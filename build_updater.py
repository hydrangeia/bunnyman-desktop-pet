"""Build a standalone Windows update assistant with an embedded offline patch."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
APP_EXE = "BunnymanDesktopPet.exe"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def bundle_files(root: Path) -> dict[str, Path]:
    root = root.resolve(strict=True)
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"Bundle must not contain links: {path}")
        if path.is_file():
            path.resolve().relative_to(root)
            result[path.relative_to(root).as_posix()] = path
    for required in (APP_EXE, "_internal/python313.dll", "manifest.json"):
        if required not in result:
            raise ValueError(f"Not a complete portable bundle: missing {required}")
    if not any(name.startswith("frames/") for name in result):
        raise ValueError("Not a complete portable bundle: missing frames")
    return result


def prepare_payload(base: Path, updated: Path, work: Path, version: str) -> dict:
    before, after = bundle_files(base), bundle_files(updated)
    changes = []
    for relative, source in sorted(after.items()):
        digest = sha256(source)
        if relative not in before or sha256(before[relative]) != digest:
            changes.append({"path": relative, "sha256": digest})
    if not changes:
        raise ValueError("The two bundles are identical")
    config = {
        "version": version,
        "app_exe": APP_EXE,
        "full_download_url": "https://github.com/hydrangeia/bunnyman-desktop-pet/releases/download/v0.1.1/BunnymanDesktopPet-windows-x64.zip",
        "allowed_base_exe_sha256": list(dict.fromkeys([
            sha256(before[APP_EXE]), sha256(after[APP_EXE]),
        ])),
        "required_runtime_files": sorted(name for name in before if name.startswith("_internal/")),
        "test_mode": False,
        "files": changes,
    }
    work.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(work / "payload.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for item in changes:
            archive.write(after[item["path"]], item["path"])
    (work / "manifest.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def compiler_path() -> Path:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for framework in ("Framework64", "Framework"):
        path = windows / "Microsoft.NET" / framework / "v4.0.30319" / "csc.exe"
        if path.is_file():
            return path
    raise ValueError("Windows .NET Framework C# compiler was not found")


def compile_updater(work: Path, output: Path, compiler: Path | None = None) -> None:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(compiler or compiler_path()), "/nologo", "/target:winexe", "/platform:x64",
        "/optimize+", "/codepage:65001", "/utf8output", f"/out:{output}",
        "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll",
        "/reference:System.Web.Extensions.dll", "/reference:System.IO.Compression.dll",
        "/reference:System.IO.Compression.FileSystem.dll",
        f"/resource:{work.resolve() / 'payload.zip'},UpdatePayload.zip",
        f"/resource:{work.resolve() / 'manifest.json'},UpdateManifest.json",
        str(ROOT / "updater" / "Updater.cs"),
    ]
    subprocess.run(command, check=True, cwd=ROOT)
    output.with_suffix(output.suffix + ".sha256").write_text(
        f"{sha256(output)}  {output.name}\n", encoding="ascii"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="complete old portable program folder")
    parser.add_argument("--updated", type=Path, required=True, help="complete new portable program folder")
    parser.add_argument("--output", type=Path, required=True, help="standalone update assistant .exe")
    parser.add_argument("--version", default="0.1.1")
    parser.add_argument("--compiler", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="prepare and validate the patch without compiling")
    args = parser.parse_args(argv)
    try:
        output = args.output.resolve()
        for source in (args.base.resolve(), args.updated.resolve()):
            if output.is_relative_to(source):
                raise ValueError("Updater output must be outside both portable folders")
        work = ROOT / ".build" / "updater" / uuid.uuid4().hex[:8]
        config = prepare_payload(args.base, args.updated, work, args.version)
        if not args.dry_run:
            compile_updater(work, output, args.compiler)
        print(json.dumps({"files": len(config["files"]), "payload_bytes": (work / "payload.zip").stat().st_size,
                          "output": str(output), "compiled": not args.dry_run}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Updater build failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
