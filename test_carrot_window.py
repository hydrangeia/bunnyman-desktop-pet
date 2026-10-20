"""Synthetic offscreen integration checks for the carrot feeding sequence."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from desktop_pet import Clip, PetManifest, make_window
from interaction_policy import Reaction
from snap_geometry import Anchor, Rect, Surface


CANVAS = 64
CARROT_RECT = QRect(28, 52, 4, 3)
CARROT_COLOR = QColor("#ffe000")
CLIP_FRAME_COUNTS = {
    "idle_loop": 2,
    "idle_happy": 2,
    "pig_take": 2,
    "pig_pickup": 2,
    "eat": 2,
    "eat_carrot": 6,
    "eat_carrot_spun": 6,
    "carrot_offer": 2,
    "carrot_place": 2,
    "carrot_spin": 3,
    "sleep_pre": 2,
    "sleep_loop": 2,
    "sleep_pst": 2,
}
GROUND_CARROT_CLIPS = {"carrot_place", "carrot_spin"}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def synthetic_assets():
    with TemporaryDirectory(prefix=".carrot-window-test-", dir=Path(__file__).parent) as directory:
        yield Path(directory)


def _write_frame(path: Path, color: QColor, *, carrot: bool) -> None:
    image = QImage(CANVAS, CANVAS, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.fillRect(QRect(15, 8, 34, 45), color)
    if carrot:
        painter.fillRect(CARROT_RECT, CARROT_COLOR)
    painter.end()
    assert image.save(str(path))


def _manifest(directory: Path, *, legacy=False) -> PetManifest:
    if legacy:
        clip_names = {"idle_loop": 2, "eat": 2}
        skins = {"normal": "Normal"}
    else:
        clip_names = CLIP_FRAME_COUNTS
        skins = {"normal": "Normal", "alt": "Alternate"}

    clips = {}
    for clip_index, (name, frame_count) in enumerate(clip_names.items()):
        frames = {}
        for skin_index, skin in enumerate(skins):
            paths = []
            for frame_index in range(frame_count):
                path = directory / f"{skin}-{name}-{frame_index}.png"
                color = QColor.fromHsv(
                    (clip_index * 31 + frame_index * 19 + skin_index * 83) % 360,
                    220,
                    220,
                )
                has_carrot = (
                    not legacy
                    and (
                        name in GROUND_CARROT_CLIPS
                        or (name in {"eat_carrot", "eat_carrot_spun"} and frame_index < 4)
                    )
                )
                _write_frame(path, color, carrot=has_carrot)
                paths.append(path)
            clip_id = f"{name}-255"
            clips[clip_id] = Clip(
                clip_id=clip_id,
                name=name,
                label=name,
                group="synthetic",
                facing="255",
                fps=12,
                frames=frames,
            )
            frames[skin] = tuple(paths)

    return PetManifest(
        path=directory / "manifest.json",
        skins=skins,
        default_skin="normal",
        default_animation="idle_loop",
        clips=clips,
        canvas=(CANVAS, CANVAS),
        origin=None,
        props={},
        effects={},
    )


@pytest.fixture
def pet(app, synthetic_assets):
    window = make_window(_manifest(synthetic_assets))
    window.snap_enabled = False
    window.show()
    app.processEvents()
    _stop_timers(window)
    yield window
    window.close()
    app.processEvents()


def _stop_timers(window):
    for timer in (
        window.timer,
        window.effect_timer,
        window.single_click_timer,
        window.hover_timer,
        window.policy_timer,
        window.cursor_timer,
        window.snap_timer,
    ):
        timer.stop()


def _advance(window):
    window.timer.stop()
    window.advance_frame()
    window.timer.stop()


def _advance_until(window, *, name=None, active_action=None, limit=80):
    for _ in range(limit):
        if ((name is None or window.current_name == name)
                and (active_action is None or window.controller.active_action == active_action)):
            return
        _advance(window)
    raise AssertionError(
        f"did not reach name={name!r}, action={active_action!r}; "
        f"at {window.current_name!r}/{window.controller.active_action!r}"
    )


def _carrot_point(window):
    scale = window.display_size / CANVAS
    return QPoint(round((CARROT_RECT.x() + CARROT_RECT.width() / 2) * scale),
                  round((CARROT_RECT.y() + CARROT_RECT.height() / 2) * scale))


def _assert_visible_carrot_and_sync(window):
    point = _carrot_point(window)
    pixmap = window.image_label.pixmap()
    assert pixmap is not None
    assert pixmap.toImage().pixelColor(point) == CARROT_COLOR
    assert window.current_body_region.contains(point)
    expected_path = window.current_clip.frames[window.current_skin][window.current_index]
    assert window.capture_window.frame_paths == (expected_path, None, window.current_mirror)


def _assert_no_carrot(window):
    point = _carrot_point(window)
    pixmap = window.image_label.pixmap()
    assert pixmap is not None
    assert pixmap.toImage().pixelColor(point) != CARROT_COLOR
    assert not window.current_body_region.contains(point)


def _open_capture(window):
    window.toggle_capture_window(True)
    assert window.capture_window is not None and window.capture_window.isVisible()


def test_spin_carrot_dispatch_advances_composite_frames_and_clears_after_idle(pet):
    _open_capture(pet)
    pet._dispatch_reaction(Reaction("spin_carrot"))
    assert pet.controller.active_action == "spin_carrot"
    assert pet.current_name == "carrot_offer"
    assert not pet.current_mirror

    _advance_until(pet, name="carrot_place")
    _assert_visible_carrot_and_sync(pet)
    _advance_until(pet, name="carrot_spin")
    _assert_visible_carrot_and_sync(pet)
    _advance_until(pet, name="eat_carrot_spun")

    # The synthetic native bite happens at frame four; its ground-carrot pixels
    # disappear from both the body mask and the source frame at that point.
    assert pet.current_index == 0
    _assert_visible_carrot_and_sync(pet)
    for expected_index in (1, 2, 3):
        _advance(pet)
        assert pet.current_name == "eat_carrot_spun"
        assert pet.current_index == expected_index
        _assert_visible_carrot_and_sync(pet)
    _advance(pet)
    assert pet.current_name == "eat_carrot_spun"
    assert pet.current_index == 4
    _assert_no_carrot(pet)
    _assert_visible_capture_source_only(pet)

    _advance_until(pet, active_action="idle")
    assert pet.current_name == "idle_loop"
    _assert_no_carrot(pet)
    _assert_visible_capture_source_only(pet)


def _assert_visible_capture_source_only(window):
    expected_path = window.current_clip.frames[window.current_skin][window.current_index]
    assert window.capture_window.frame_paths == (expected_path, None, window.current_mirror)


@pytest.mark.parametrize(
    ("queued", "latest", "expected_name"),
    [
        (("sleep", "eat"), "eat", "carrot_offer"),
        (("eat", "sleep"), "sleep", "sleep_pre"),
    ],
)
def test_latest_manual_sleep_or_feed_waits_for_full_spin(pet, queued, latest, expected_name):
    start = len(pet.play_history)
    pet._dispatch_reaction(Reaction("spin_carrot"))
    _advance_until(pet, name="carrot_spin")

    for action in queued:
        pet.request_action(action)
        assert pet.controller.active_action == "spin_carrot"
        assert pet.current_name == "carrot_spin"

    _advance_until(pet, active_action=latest)
    assert pet.current_name == expected_name
    sequence = pet.play_history[start:]
    expected_spin = ["carrot_spin", "eat_carrot_spun", "idle_happy"]
    positions = [sequence.index(name) for name in expected_spin]
    assert positions == sorted(positions)
    if latest == "eat":
        _advance_until(pet, active_action="idle")
        assert pet.current_name == "idle_loop"
        _assert_no_carrot(pet)
    else:
        assert "eat_carrot_spun" in sequence
        assert pet.controller.pending_action is None


def test_spin_phase_skin_turn_and_resize_preserve_action_index_mask_and_capture(pet):
    _open_capture(pet)
    pet._dispatch_reaction(Reaction("spin_carrot"))
    _advance_until(pet, name="carrot_spin")
    _advance(pet)
    assert pet.current_name == "carrot_spin"
    saved_index = pet.current_index
    saved_step = pet.controller.current
    saved_path = pet.current_clip.frames[pet.current_skin][saved_index]
    assert not pet.current_mirror

    pet.set_skin("alt")
    assert pet.current_name == "carrot_spin"
    assert pet.current_index == saved_index
    assert pet.controller.current == saved_step
    _assert_visible_carrot_and_sync(pet)
    alternate_path = pet.current_clip.frames[pet.current_skin][pet.current_index]
    assert alternate_path != saved_path

    pet.set_direction("left")
    assert pet.current_name == "carrot_spin"
    assert pet.current_index == saved_index
    assert pet.controller.current == saved_step
    assert not pet.current_mirror  # universal facing 255 is never mirrored
    _assert_visible_carrot_and_sync(pet)
    assert pet.current_clip.frames[pet.current_skin][pet.current_index] == alternate_path

    pet.set_display_size(360)
    assert pet.current_name == "carrot_spin"
    assert pet.current_index == saved_index
    assert pet.controller.current == saved_step
    assert not pet.current_mirror
    assert (pet.capture_window.width(), pet.capture_window.height()) == (CANVAS, CANVAS)
    _assert_visible_carrot_and_sync(pet)


def test_old_manifest_falls_back_to_simple_eat_for_spin_reaction(app, synthetic_assets):
    legacy_dir = synthetic_assets / "legacy"
    legacy_dir.mkdir()
    window = make_window(_manifest(legacy_dir, legacy=True))
    _stop_timers(window)
    try:
        assert "spin_carrot" not in window.controller.actions
        window._dispatch_reaction(Reaction("spin_carrot"))
        assert window.controller.active_action == "eat"
        assert window.current_name == "eat"
        _advance_until(window, active_action="idle")
        assert window.current_name == "idle_loop"
    finally:
        window.close()
        app.processEvents()


def test_floor_docking_keeps_bending_and_carrot_visible_without_horizontal_jump(pet, monkeypatch):
    reference = pet._body_visible_rect()
    floor = Surface("screen:food-test", Rect(0, 0, 1200, 700), "screen")
    pet.snap_enabled = True
    pet.snap_surfaces = [floor]
    pet.snap_reference_rect = reference
    pet.move(100, round(floor.rect.bottom-reference.bottom))
    baseline = pet.pos()
    pet.snap_anchor = Anchor(floor.id, "bottom", (pet.x()+reference.center_x)/floor.rect.width)
    monkeypatch.setattr(pet, "_collect_snap_surfaces", lambda: [floor])
    pet.request_action("spin_carrot")
    saw_extended_frame = False
    for _ in range(80):
        if pet._is_carrot_pose():
            visible = pet._body_visible_rect().translated(pet.x(),pet.y())
            assert visible.bottom <= floor.rect.bottom
            assert pet.x() == baseline.x()
            saw_extended_frame |= pet.y() < baseline.y()
            pet._update_snap()
            assert pet._body_visible_rect().bottom+pet.y() <= floor.rect.bottom
        if pet.controller.active_action == "idle":
            break
        _advance(pet)
    assert saw_extended_frame
    pet._update_snap()
    assert pet.pos() == baseline
