# Third-party notices

## Don't Starve Together material

The rabbit character, game artwork, animation frames, and other Don't Starve
Together material remain the property of Klei Entertainment. The MIT license
in this repository applies only to code written for this desktop pet; it does
not license Klei's game material. This is an unofficial fan-made desktop app,
is not made, endorsed, or supported by Klei, and must remain free and
non-commercial. See Klei's [Player Creation Guidelines](https://support.klei.com/hc/en-us/articles/360029880791-Player-Creation-Guidelines)
and the [Don't Starve Together Steam page](https://store.steampowered.com/app/322330/Don't_Starve_Together/).

The source repository excludes the local manifest, rendered frames, and game
archives. A separately distributed fan-app ZIP may include the rendered frames
and a manifest that references them, under the conditions in Klei's guidelines.
The repository's `app.ico` is also derived from the rabbit artwork and remains
Klei material; it is not covered by this project's MIT license.

## Runtime and build dependencies

The portable Windows bundle is built with Python, PySide6/Qt for Python,
NumPy, Pillow, PyInstaller, and PyInstaller hooks. Each component keeps its own
license and notices; none of those dependency terms are replaced by the MIT
license for this project's code. The bundle includes license texts from the
installed packages and Python runtime in `THIRD_PARTY_LICENSES/`, along with
the LGPLv3, GPLv2, and GPLv3 texts offered by the Qt for Python/Shiboken
community packages. It uses PyInstaller's onedir layout, keeping Qt runtime
DLLs in a separate directory beside the executable. Consult the included
license and notice files for the exact terms that apply to each version.

- [Qt for Python licensing](https://doc.qt.io/qtforpython-6/licenses.html)
- [Python license information](https://www.python.org/psf/about/legal/)
- [NumPy license](https://numpy.org/doc/stable/license.html)
- [Pillow license](https://pillow.readthedocs.io/en/stable/about.html#license)
- [PyInstaller documentation](https://pyinstaller.org/en/stable/)
