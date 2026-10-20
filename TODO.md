# Roadmap

## In place

- Three looks: normal, sleep cap, and sleep cap with pillow.
- Action controller for complete sleep, burrow, jump, walk/run, and recovery flows.
- Silent lively and quiet interaction schedules, visible carrot feeding, hover, body taps, double-clicks, dragging, and discoverable wheel/shake reactions.
- Carrot feeding discovery: the first feed is direct; later feeds sometimes reveal a ground-carrot spin in Lively mode with automatic activity on. Quiet mode and auto-off keep feeding direct; the short sequence keeps the game's bite timing and happy ending as a single-rabbit desktop adaptation.
- Cursor play: gentle nearby mouse movement can draw a quiet look or ear rub, with occasional short safe walks toward the pointer in Lively mode; Quiet mode gives only a small notice response, and a parked pointer is not followed.
- Screen/taskbar/ordinary-window edge docking, following moving windows, and sleep support based on the visible body outline.
- Pillow release transitions and independent hit, thaw, and pillow-petal effects.
- Manifest-driven frame loading and a bounded animation cache.
- 210 regression tests pass locally, including native carrot consumption/spin sequencing, feed discovery/queue priority, floor support, cursor gesture/cooldown, safe movement and snap continuity, native Windows capture, updater rollback, path isolation, process closing, restart, and GUI lifecycle checks. Tests do not require game files; the native capture probe is opt-in.
- Windows x64 portable ZIP built in a clean project-local environment, with the manifest-referenced image assets and dependency license texts.
- Packaged executable smoke checks pass in the bundle folder, after ZIP extraction into a Chinese/space-containing path, and after applying the update over v0.1.0: 103 clips, 59 clip names, 31 complete actions, with referenced assets, capture-view synchronization, and lifecycle checks passing.
- Separate capture window with a fixed 620×616 canvas, synchronized pet/effect frames, and selectable green/blue/magenta backgrounds for streaming software.
- Bilingual build/download guides and a public source repository.

## Release

- [v0.1.3](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/tag/v0.1.3) restores native eating with a ground carrot and adds an occasional finite Spin the Carrot discovery. The standalone updater supports complete v0.1.0, v0.1.1, and v0.1.2 installations.
- [v0.1.2](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/tag/v0.1.2) adds silent cursor play and short horizontal chasing, with a full portable bundle and one standalone updater for complete v0.1.0 and v0.1.1 installations.
- [v0.1.1](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/tag/v0.1.1) includes the independent capture window, full bundle, and manual overlay ZIP. A standalone 4.97 MB update assistant is verified against a running real v0.1.0 copy in a Chinese/space-containing path: stop, backup, replace, and restart as v0.1.1 all pass.
- Published [v0.1.0](https://github.com/hydrangeia/bunnyman-desktop-pet/releases/tag/v0.1.0) with the portable ZIP and its SHA-256 checksum; GitHub's asset digest matches the tested local ZIP.

- The preferred upgrade is the standalone updater. The original ZIP remains available for manual overlay and cannot run independently.

## Later

- Test window capture and chroma key end-to-end in OBS and Bilibili Live Companion on Windows.
- Try more window arrangements and mixed-DPI monitors during everyday use.
- Refine pillow motion and the timing of discoveries from play feedback.
- Explore a small nest, gradual friendship, and short action stories as later additions.
