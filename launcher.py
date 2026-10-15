"""Entry point for source runs and the portable Windows release bundle."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence


APP_NAME = "BunnymanDesktopPet"


def app_directory() -> Path:
    """Return the folder containing the executable or this source file."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_report_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME / "smoke-test-report.json"
    return Path(tempfile.gettempdir()) / APP_NAME / "smoke-test-report.json"


def _write_report(path: Path, report: dict[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bunnyman desktop pet")
    parser.add_argument("--manifest", type=Path, help="manifest.json beside the portable bundle")
    parser.add_argument("--smoke-test", action="store_true", help="validate bundled assets and interaction flows, then exit")
    parser.add_argument("--test-report", type=Path, help="write smoke-test output and status to a JSON file")
    args = parser.parse_args(argv)

    manifest = (args.manifest or (app_directory() / "manifest.json")).expanduser().resolve()
    from desktop_pet import main as pet_main

    pet_args = ["--manifest", str(manifest)]
    if args.smoke_test:
        pet_args.append("--smoke-test")
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                return_code = int(pet_main(pet_args))
        except BaseException as exc:
            # Keep a machine-readable report even if startup failed before Qt returned.
            return_code = 1
            stderr.write(f"{type(exc).__name__}: {exc}\n")
        report = {
            "application": APP_NAME,
            "test": "smoke",
            "ok": return_code == 0,
            "returncode": return_code,
            "manifest": manifest.name,
            "stdout": stdout.getvalue(),
            "stderr": stderr.getvalue(),
        }
        try:
            _write_report(args.test_report or default_report_path(), report)
        except OSError as exc:
            report["ok"] = False
            report["returncode"] = 1
            report["stderr"] = str(report["stderr"]) + f"Could not write test report: {exc}\n"
            if sys.stderr:
                print(report["stderr"], file=sys.stderr, end="")
            return 1
        if sys.stdout:
            print(f"Smoke test {'passed' if return_code == 0 else 'failed'}; report: {args.test_report or default_report_path()}")
        return return_code

    return int(pet_main(pet_args))


if __name__ == "__main__":
    raise SystemExit(main())
