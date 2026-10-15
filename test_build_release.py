"""Regression tests for portable bundle preparation, independent of Qt/PyInstaller."""

from __future__ import annotations

import json
import hashlib
import zipfile
from pathlib import Path

import pytest

import build_release
import launcher


def test_manifest_walk_collects_only_declared_animation_effect_and_prop_images():
    manifest = {
        "animations": {"idle": {"frames": {"cozy": ["frames/cozy/idle.png"]}}},
        "effects": {
            "hit": {"frames": ["effects/hit/000.png"]},
            "thaw": {"frames": ["effects/thaw/000.webp"]},
        },
        "props": {"carrot": {"path": "props/carrot.png"}},
        "statistics": {"preview": "contact_sheet.png"},
    }

    assert build_release.manifest_media_references(manifest) == [
        "effects/hit/000.png",
        "effects/thaw/000.webp",
        "frames/cozy/idle.png",
        "props/carrot.png",
    ]


def test_manifest_sanitizing_removes_machine_paths_but_keeps_relative_metadata():
    source = {
        "game_directory": r"F:\steam\steamapps\common\Don't Starve Together",
        "source": "anim/manrabbit_basic.zip",
        "source_path": r"C:\Users\pet-owner\Desktop\anim.zip",
        "source_scripts": ["scripts/stategraphs/SGrabbit.lua", r"D:\private\SGrabbit.lua"],
        "animations": {
            "idle": {
                "frames": {"cozy": ["frames/cozy/idle.png"]},
                "source_directory": r"C:\Users\pet-owner\Desktop\raw-game-files",
            }
        },
    }

    cleaned = build_release.sanitize_manifest(source)
    serialized = json.dumps(cleaned, ensure_ascii=False)

    assert "game_directory" not in cleaned
    assert cleaned["source"] == "anim/manrabbit_basic.zip"
    assert cleaned["source_scripts"] == ["scripts/stategraphs/SGrabbit.lua"]
    assert cleaned["animations"]["idle"]["frames"]["cozy"] == ["frames/cozy/idle.png"]
    assert "C:\\Users" not in serialized
    assert "D:\\private" not in serialized
    assert "F:\\steam" not in serialized


@pytest.mark.parametrize("reference", ["../outside.png", "frames/../../outside.png", r"C:\\local\\frame.png", r"\\server\share\frame.png"])
def test_manifest_asset_references_reject_absolute_paths_and_parent_escape(reference):
    with pytest.raises(build_release.BuildError):
        build_release.manifest_media_references(
            {"animations": {"idle": {"frames": {"cozy": [reference]}}}}
        )


def test_validation_returns_only_existing_declared_files(tmp_path):
    (tmp_path / "frames" / "cozy").mkdir(parents=True)
    (tmp_path / "props").mkdir()
    (tmp_path / "frames" / "cozy" / "idle.png").write_bytes(b"frame")
    (tmp_path / "props" / "carrot.png").write_bytes(b"carrot")
    (tmp_path / "frames" / "orphan.png").write_bytes(b"unused")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "game_directory": r"F:\private\dst",
                "animations": {"idle": {"frames": {"cozy": ["frames/cozy/idle.png"]}}},
                "props": {"carrot": {"path": "props/carrot.png"}},
            }
        ),
        encoding="utf-8",
    )

    cleaned, assets = build_release.read_and_validate_manifest(manifest_path)

    assert set(relative for relative, _ in assets) == {"frames/cozy/idle.png", "props/carrot.png"}
    assert all(path.is_file() for _, path in assets)
    assert "game_directory" not in cleaned


def test_safe_remove_refuses_to_delete_outside_its_build_root(tmp_path):
    allowed = tmp_path / "build"
    outside = tmp_path / "keep-me"
    allowed.mkdir()
    outside.mkdir()
    marker = outside / "data.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(build_release.BuildError):
        build_release._safe_remove(outside, allowed)

    assert marker.read_text(encoding="utf-8") == "keep"


def test_runtime_license_texts_are_staged_beside_the_portable_app(tmp_path):
    app_dir = tmp_path / "bundle"
    app_dir.mkdir()

    build_release._copy_third_party_licenses(app_dir)
    license_root = app_dir / "THIRD_PARTY_LICENSES"

    for name in ("LGPL-3.0-only.txt", "GPL-2.0-only.txt", "GPL-3.0-only.txt"):
        text = (license_root / "Qt" / name).read_text(encoding="utf-8")
        assert "GNU " in text[:160]
    assert list((license_root / "PySide6-Essentials").rglob("LicenseRef-Qt-Commercial.txt"))
    assert list((license_root / "shiboken6").rglob("LicenseRef-Qt-Commercial.txt"))
    assert list((license_root / "numpy").rglob("LICENSE.txt"))
    assert list((license_root / "Pillow").rglob("LICENSE"))
    pyinstaller_copying = list((license_root / "PyInstaller").rglob("COPYING.txt"))
    assert pyinstaller_copying
    assert "bootloader" in pyinstaller_copying[0].read_text(encoding="utf-8").lower()


def test_conda_libffi_is_detected_for_packaging_but_not_required_elsewhere(tmp_path):
    library_bin = tmp_path / "Library" / "bin"
    library_bin.mkdir(parents=True)

    assert build_release._conda_runtime_binaries(tmp_path) == []
    ffi = library_bin / "ffi.dll"
    ffi.write_bytes(b"libffi")
    assert build_release._conda_runtime_binaries(tmp_path) == [ffi]


def test_build_refuses_output_folder_that_contains_the_source_project(tmp_path):
    media = tmp_path / "frames" / "idle.png"
    media.parent.mkdir()
    media.write_bytes(b"frame")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"animations": {"idle": {"frames": ["frames/idle.png"]}}}),
        encoding="utf-8",
    )

    result = build_release.main(
        ["--manifest", str(manifest), "--output-dir", str(build_release.ROOT.parent)]
    )

    assert result == 1


def test_packaged_entry_and_asset_paths_survive_zip_extraction_to_unicode_folder(tmp_path, monkeypatch):
    source = tmp_path / "bundle-source" / "BunnymanDesktopPet"
    (source / "frames" / "cozy").mkdir(parents=True)
    exe = source / "BunnymanDesktopPet.exe"
    exe.write_bytes(b"portable executable")
    (source / "frames" / "cozy" / "idle.png").write_bytes(b"frame")
    (source / "manifest.json").write_text(
        json.dumps({"animations": {"idle": {"frames": {"cozy": ["frames/cozy/idle.png"]}}}}),
        encoding="utf-8",
    )
    archive = tmp_path / "BunnymanDesktopPet-windows-x64.zip"
    build_release._zip_bundle(source, archive)

    extract_root = tmp_path / "兔人 桌宠 release"
    with zipfile.ZipFile(archive) as zip_file:
        zip_file.extractall(extract_root)
    extracted = extract_root / source.name
    extracted_exe = extracted / "BunnymanDesktopPet.exe"
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "executable", str(extracted_exe))

    assert extracted_exe.is_file()
    assert (extracted / "frames" / "cozy" / "idle.png").is_file()
    assert launcher.app_directory() == extracted
    assert build_release.sha256_file(archive) == hashlib.sha256(archive.read_bytes()).hexdigest()


def test_smoke_test_writes_success_report_without_qt(tmp_path, monkeypatch):
    import desktop_pet

    def fake_pet_main(args):
        assert args[0] == "--manifest"
        assert args[2] == "--smoke-test"
        print("bundle OK")
        return 0

    monkeypatch.setattr(desktop_pet, "main", fake_pet_main)
    report_path = tmp_path / "报表" / "smoke-report.json"

    result = launcher.main(["--smoke-test", "--manifest", str(tmp_path / "manifest.json"), "--test-report", str(report_path)])

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 0
    assert report["ok"] is True
    assert report["returncode"] == 0
    assert report["stdout"].strip() == "bundle OK"
    assert report["manifest"] == "manifest.json"


def test_smoke_test_preserves_failure_output_and_return_code(tmp_path, monkeypatch):
    import desktop_pet

    def fake_pet_main(_args):
        print("missing frame", file=__import__("sys").stderr)
        return 1

    monkeypatch.setattr(desktop_pet, "main", fake_pet_main)
    report_path = tmp_path / "failure.json"

    result = launcher.main(["--smoke-test", "--test-report", str(report_path)])

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result == 1
    assert report["ok"] is False
    assert report["returncode"] == 1
    assert "missing frame" in report["stderr"]
