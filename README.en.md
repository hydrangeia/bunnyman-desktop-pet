# DST Rabbit Desktop Pet

Keep a Don't Starve Together rabbit in the corner of your desktop. It notices taps, feeding, dragging, and nearby attention, and sometimes gets up to something on its own. There are no speech bubbles; its animations do the talking.

**Unzip → launch → leave it in a desktop corner → tap, feed, or drag → see how it reacts**

## Download and launch

For a first-time install, download the [Windows x64 full bundle for v0.1.3](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/latest/download/BunnymanDesktopPet-windows-x64.zip), extract the whole folder, and run `BunnymanDesktopPet.exe`. Python is not required; keep the `_internal` folder, `manifest.json`, and image folders beside the executable.

If you already have a complete v0.1.0, v0.1.1, or v0.1.2 installation, use the [standalone updater](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/download/v0.1.3/BunnymanDesktopPet-v0.1.x-to-v0.1.3-updater.exe): double-click it, select your original `BunnymanDesktopPet.exe`, then click “更新并重启” (Update and restart). It checks the installed resources and patch, closes the pet in that folder, backs up and replaces files, then restarts it. Failed file replacements restore the backup. The updater itself does not require Python.

If you previously ran a manual patch as a complete program and saw a missing `python313.dll` message, download the full bundle above. Older versions and manual overlays are on [GitHub Releases](https://github.com/hydrangeia/bunnyman-desktop-pet/releases).

The default look is a rabbit in a sleep cap, near the bottom of the screen, with its feet grounded to the actual body outline. The pet is a transparent, frameless window that stays above ordinary windows. It can snap to screen, taskbar, and regular window edges and follow a window as it moves. The right-click menu offers feeding, activity style and automatic activity, snapping, looks, size, and exit.

## Spend time with the rabbit

- Tap different parts or double-click to trigger different interactions; keep playing to find more little surprises.
- Press `F` or choose the carrot in the right-click menu to feed it. The first feed goes straight to eating. In Lively mode with automatic activity on, later feeds sometimes reveal a little Spin the Carrot moment: the rabbit sets the carrot by its feet, watches it spin, then eats it. Quiet company or automatic activity off keeps feeding direct. Feeding has a four-second cooldown; if the rabbit is busy, it finishes its current sequence, then carries out the latest queued action.
- Drag with the left mouse button and release for a drop reaction. Pause over the rabbit and it will notice you.
- The mouse wheel can trigger a freeze-and-thaw interaction.
- Turn automatic activity off in the right-click menu, or choose “Quiet company.” The default “Lively and friendly” style adds occasional idle actions and a short nap after a quiet spell. If you put it to sleep yourself, wake it manually.
- While the rabbit is idle, gently move the mouse nearby and it may silently look your way or rub an ear. In Lively mode, it may take a few short steps toward the mouse along a safe route, then stop happily or give up with an ear rub and rest for a while. It will not keep following a parked pointer. Quiet company gives only a small notice response; turning automatic activity off also disables proximity play, while explicit taps and hovering still work.
- These short moves stay horizontal along existing top or bottom supporting edges of windows or screens, or within the screen work area. The rabbit never hops across windows or screens. Proximity play waits while it sleeps, a menu is open, you drag it, or a manual action is already queued. Walking and running in Developer preview still play in place.
- Sleeping starts with lying down and ends with waking up; burrowing includes coming back up, and jumps finish with a landing.

To choose an action or facing directly, open “Developer preview” in the right-click menu for complete actions and raw clips. Most of the time, there is no need to open it.

<details>
<summary>Hidden interaction hints</summary>

Four taps within two seconds trigger hit sparks. Three downward wheel notches freeze the rabbit for four seconds before the ice shatters; scroll up to thaw it sooner. Shake it while dragging and releasing for a special reaction. Double-clicking starts with a dance, then leads to jumps, pillow play, and burrowing. The carrot starts spinning, turns, and comes to a stop before being eaten. Eating preserves the rabbit's original hand, mouth, and cheek motions, followed by a happy reaction. This is a small single-rabbit desktop adaptation; the party's hareball and red-pouch stages are not included. Automatic activity and proximity play run only while idle; they wait while the rabbit sleeps, while an action is playing, while you are dragging it, while a menu is open, or while a manual action is queued.

</details>

## Capture the rabbit in OBS or Bilibili Live Companion

Check “直播采集窗口” in the pet's right-click menu to open a normal Windows window titled “兔人桌宠 · 直播采集”. It always uses a fixed 620×616 canvas for the pet and its effects, independent of the main pet's size and screen position. Right-click the capture window, or use “采集背景” in the pet menu, to switch between green, blue, and magenta. Choose a color that does not blend into your scene, then key it out in your streaming software. You can place the capture window behind other windows, but keep it open and do not minimize it; minimizing may freeze or black out the capture.

### OBS

1. Open the capture window. Add a Window Capture source to your OBS scene and select “兔人桌宠 · 直播采集”. If the title bar appears, enable client-area-only capture or crop the borders in the source.
2. Open the source filters, add Chroma Key, and select the same color as the capture window. Adjust Similarity, Smoothness, and spill reduction until the background disappears while the rabbit's edges remain clean.

### Bilibili Live Companion

1. Add a window-capture source to the scene and select “兔人桌宠 · 直播采集”.
2. If your version offers a chroma-key or green-screen effect for that source, choose the capture window's color and check the preview. If there is no suitable filter, key and composite the scene in OBS, then stream to Bilibili from OBS.

Native Windows enumeration and client-area capture checks pass. End-to-end capture and keying in OBS and Live Companion still need testing in those applications. See the [OBS Window Capture guide](https://obsproject.com/kb/window-capture-sources), [OBS Chroma Key guide](https://obsproject.com/kb/chroma-key-filter), and [Bilibili's official streaming guide](https://live.bilibili.com/blackboard/era/u4EPvXpDYUMv7hYJ.html).

## Build from source

See the [updater developer guide](updater/README.md) to build and test the standalone update assistant.

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
