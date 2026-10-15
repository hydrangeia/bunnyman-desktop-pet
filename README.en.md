# DST Rabbit Desktop Pet

Keep a Don't Starve Together rabbit in the corner of your desktop. It notices taps, feeding, dragging, and nearby attention, and sometimes gets up to something on its own. There are no speech bubbles; its animations do the talking.

**Unzip → launch → leave it in a desktop corner → tap, feed, or drag → see how it reacts**

## Download and launch

Download the [Windows x64 portable bundle](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/latest/download/BunnymanDesktopPet-windows-x64.zip), extract the whole folder, and run `BunnymanDesktopPet.exe`. Python is not required. Keep the `_internal` folder, `manifest.json`, and image folders beside the executable. Older versions are on [GitHub Releases](https://github.com/hydrangeia/bunnyman-desktop-pet/releases).

The default look is a rabbit in a sleep cap, near the bottom of the screen, with its feet grounded to the actual body outline. The pet is a transparent, frameless window that stays above ordinary windows. It can snap to screen, taskbar, and regular window edges and follow a window as it moves. The right-click menu offers feeding, activity style and automatic activity, snapping, looks, size, and exit.

## Spend time with the rabbit

- Tap different parts or double-click to trigger different interactions; keep playing to find more little surprises.
- Press `F` or choose the carrot in the right-click menu to feed it. It visibly eats the carrot. Feeding has a cooldown; if it is busy, it finishes its current action before eating.
- Drag with the left mouse button and release for a drop reaction. Pause over the rabbit and it will notice you.
- The mouse wheel can trigger a freeze-and-thaw interaction.
- Turn automatic activity off in the right-click menu, or choose “Quiet company.” The default “Lively and friendly” style adds occasional idle actions and a short nap after a quiet spell. If you put it to sleep yourself, wake it manually.
- Sleeping starts with lying down and ends with waking up; burrowing includes coming back up, and jumps finish with a landing. Walking and running currently play in place.

To choose an action or facing directly, open “Developer preview” in the right-click menu for complete actions and raw clips. Most of the time, there is no need to open it.

<details>
<summary>Hidden interaction hints</summary>

Four taps within two seconds trigger hit sparks. Three downward wheel notches freeze the rabbit for four seconds before the ice shatters; scroll up to thaw it sooner. Shake it while dragging and releasing for a special reaction. Double-clicking starts with a dance, then leads to jumps, pillow play, and burrowing. Automatic activity runs only while idle and waits while an action is playing, while you are dragging, or while a menu is open.

</details>

## Build from source

The repository contains the pet code and build scripts, but not game-derived images, rendered frames, or the local `manifest.json`. If you already have a matching v2 manifest and rendered frames, you can skip exporting. `build_release.py` copies only PNG/WebP frames, props, and effects referenced by the manifest and removes local game directories and absolute paths from the release copy. It does not package game animation ZIPs. The portable bundle also keeps third-party license texts for Qt/Python and the other runtime dependencies.

On Windows x64 with Python 3.13:

```powershell
py -3.13 -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.build-venv\Scripts\python.exe export_pet.py --game "C:\Program Files (x86)\Steam\steamapps\common\Don't Starve Together"
.\.build-venv\Scripts\python.exe -m pytest -q
.\.build-venv\Scripts\python.exe build_release.py --dry-run
.\.build-venv\Scripts\python.exe build_release.py
```

The build writes `dist\BunnymanDesktopPet` and `dist\BunnymanDesktopPet-windows-x64.zip`. After extracting it, check the assets and action flows with this command. The windowed build writes a JSON report, so it does not need a console:

```powershell
.\dist\BunnymanDesktopPet\BunnymanDesktopPet.exe --smoke-test --test-report .\smoke-report.json
```

## License and game material

This is a free, non-commercial fan desktop app. It is not affiliated with, made by, or endorsed by Klei Entertainment. The rabbit character, game artwork, animation frames, and other Don't Starve Together material remain Klei's property. The MIT license in this repository covers only code written for this project; it does not license game material. See [Klei's Player Creation Guidelines](https://support.klei.com/hc/en-us/articles/360029880791-Player-Creation-Guidelines) and [third-party notices](THIRD_PARTY_NOTICES.md).
