# Build the offline update assistant

The assistant embeds a patch and its manifest in a Windows x64 .NET Framework executable. Users do not need Python or a separate patch ZIP. The builder uses Python and the Windows Framework C# compiler, normally found under `%WINDIR%/Microsoft.NET/Framework64/v4.0.30319`.

From the project folder, with complete old/new portable folders available:

```powershell
.\.build-venv\Scripts\python.exe build_updater.py --base dist\BunnymanDesktopPet --updated .build\v0.1.1\BunnymanDesktopPet --output .build\v0.1.1\BunnymanDesktopPet-v0.1.0-to-v0.1.1-updater.exe
.\.build-venv\Scripts\python.exe -m pytest -q test_updater.py --basetemp .build\updater-tests
```

`--dry-run` prepares the payload without compiling. The output includes a SHA-256 sidecar. No game files are needed for the tests: they compile small fixtures and use synthetic resource manifests.

The embedded `UpdateManifest.json` contains the target version, supported old/new executable hashes, required runtime filenames, and each replacement file's relative path and SHA-256. `UpdatePayload.zip` contains only changed/new files. Production manifests disable failure injection.

Before changing files, the assistant verifies the installation and all animation/prop/effect references, stages and verifies the payload, then requests a normal exit only from processes running the selected executable path. It posts both window-close and GUI-thread-quit messages to support older Qt tool windows that leave their message loop running after closing. It waits for exit rather than terminating processes.

Replaced files are backed up in a unique `.bunnyman-update-backup-*` folder inside the installation. Failed replacements restore old files and remove files newly added by that attempt. Other user files stay in place. If restarting fails after a successful replacement, the update remains installed and the assistant reports the launch error.

For scripted validation, `--target <folder-or-exe> --silent --report <json>` runs the same update operation. Add `--no-launch` to keep the updated pet closed. Test-only failure injection requires both an embedded `test_mode: true` and `--no-launch`. The GUI checks that closing its window cannot interrupt an active replacement.
