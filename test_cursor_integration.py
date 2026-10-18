"""Focused Qt integration checks for cursor play using only synthetic frames."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QEvent, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from cursor_play import CursorCue
from desktop_pet import Clip, PetManifest, make_window
from snap_geometry import Anchor, Rect, Surface


CLIP_NAMES = (
    "idle_loop", "idle_happy", "idle_earrub", "abandon", "eat_carrot",
    "walk_pre", "walk_loop", "walk_pst",
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def synthetic_assets():
    with TemporaryDirectory(prefix=".cursor-play-test-", dir=Path(__file__).parent) as directory:
        yield Path(directory)


def _synthetic_manifest(tmp_path: Path) -> PetManifest:
    clips = {}
    for clip_index, name in enumerate(CLIP_NAMES):
        for facing in ("8", "5"):
            path = tmp_path / f"{name}-{facing}.png"
            frame = QImage(16, 16, QImage.Format.Format_ARGB32)
            frame.fill(QColor(0, 0, 0, 0))
            color = QColor.fromHsv((clip_index * 37 + int(facing)) % 360, 200, 240)
            frame.fill(color)
            assert frame.save(str(path))
            clip_id = f"{name}-{facing}"
            clips[clip_id] = Clip(
                clip_id=clip_id,
                name=name,
                label=name,
                group="test",
                facing=facing,
                fps=12,
                frames={"synthetic": (path,)},
            )
    return PetManifest(
        path=tmp_path / "manifest.json",
        skins={"synthetic": "Synthetic"},
        default_skin="synthetic",
        default_animation="idle_loop",
        clips=clips,
        canvas=(16, 16),
        origin=None,
        props={},
        effects={},
    )


@pytest.fixture
def pet(app, synthetic_assets):
    window = make_window(_synthetic_manifest(synthetic_assets))
    window.snap_enabled = False
    area = app.primaryScreen().availableGeometry()
    if area.width() < window.display_size or area.height() < window.display_size:
        pytest.skip("The offscreen screen is smaller than the synthetic pet window")
    window.move(area.x() + 20, area.y() + 20)
    window.show()
    app.processEvents()
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
    yield window
    window.close()
    app.processEvents()


def _attach_screen_anchor(window, app):
    visible = window._body_visible_rect()
    center = QPoint(round(window.x() + visible.center_x), round(window.y() + visible.center_y))
    screen = app.screenAt(center)
    assert screen is not None
    area = screen.availableGeometry()
    rect = Rect(area.x(), area.y(), area.x() + area.width(), area.y() + area.height())
    surface_id = f"screen:{screen.name()}"
    window.snap_surfaces = [Surface(surface_id, rect, "screen")]
    window.snap_anchor = Anchor(
        surface_id,
        "bottom",
        (window.x() + visible.center_x - rect.left) / rect.width,
    )
    return rect


def _stub_tick(monkeypatch, window, cue):
    tick = Mock(return_value=cue)
    monkeypatch.setattr(window.cursor_play, "tick", tick)
    return tick


def _start_cursor_walk(window, monkeypatch, *, dx=80, now=10.0):
    pointer = QPoint(window.x() + 300, window.y() + 220)
    tick = _stub_tick(
        monkeypatch,
        window,
        CursorCue(action="walk", direction="right", dx=dx),
    )
    before = (window.x(), window.y())
    window._tick_cursor_play(pointer=pointer, now=now)
    tick.assert_called_once()
    assert tick.call_args.kwargs["pointer"] == (pointer.x(), pointer.y())
    assert tick.call_args.kwargs["now"] == now
    assert window.controller.active_action == "walk"
    assert window.current_name == "walk_pre"
    # The start cue can request locomotion, but the body waits for walk_loop.
    assert (window.x(), window.y()) == before
    return pointer


def _enter_walk_loop(window):
    window.timer.stop()
    window.advance_frame()
    assert window.current_name == "walk_loop"
    window.timer.stop()


def test_cursor_walk_clamps_to_screen_and_keeps_y_and_snap_ratio(pet, app, monkeypatch):
    rect = _attach_screen_anchor(pet, app)
    _start_cursor_walk(pet, monkeypatch, dx=90)
    _enter_walk_loop(pet)

    movement_reference = pet._cursor_reference
    expected_y = pet.y()
    pointer = QPoint(pet.x() + 300, pet.y() + 220)
    tick = _stub_tick(monkeypatch, pet, CursorCue(dx=45))
    pet._tick_cursor_play(pointer=pointer, now=10.1)
    assert tick.call_args.kwargs["pointer"] == (pointer.x(), pointer.y())
    assert pet.x() > 20 + rect.left
    assert pet.y() == expected_y
    assert pet.snap_anchor.side == "bottom"
    expected_ratio = (pet.x() + movement_reference.center_x - rect.left) / rect.width
    assert pet.snap_anchor.ratio == pytest.approx(expected_ratio)

    bounds = pet._cursor_movement_bounds()
    assert bounds is not None
    maximum = bounds[1]
    _stub_tick(monkeypatch, pet, CursorCue(dx=10_000))
    pet._tick_cursor_play(pointer=QPoint(pet.x() + 300, pet.y() + 220), now=10.2)
    assert pet.x() == maximum
    assert pet.y() == expected_y
    expected_ratio = (maximum + movement_reference.center_x - rect.left) / rect.width
    assert pet.snap_anchor.ratio == pytest.approx(expected_ratio)


def test_walk_policy_uses_actual_body_outside_wider_movement_envelope(pet, app, monkeypatch):
    area = app.primaryScreen().availableGeometry()
    actual = pet._body_visible_rect()
    pet.move(area.x() + 80, area.y() + area.height() - actual.bottom)
    _attach_screen_anchor(pet, app)
    actual = pet._body_visible_rect()
    envelope = Rect(actual.left - 40, actual.top, actual.right + 60, actual.bottom)
    monkeypatch.setattr(pet, "_cursor_walk_rect", Mock(return_value=envelope))
    pointer = QPoint(round(pet.x() + actual.right + 30), round(pet.y() + actual.center_y))
    tick = _stub_tick(monkeypatch, pet, CursorCue(action="walk", direction="right"))

    pet._tick_cursor_play(pointer=pointer, now=10.0)

    policy_body = tick.call_args.kwargs["body"]
    assert policy_body == actual.translated(pet.x(), pet.y())
    assert not policy_body.contains(pointer.x(), pointer.y())
    assert envelope.translated(pet.x(), pet.y()).contains(pointer.x(), pointer.y())
    assert pet._cursor_body_reference == actual
    assert pet._cursor_reference == envelope


def test_snap_rebases_from_walk_envelope_to_changed_idle_silhouette(pet, app, monkeypatch):
    area = app.primaryScreen().availableGeometry()
    actual = pet._body_visible_rect()
    pet.move(area.x() + 80, area.y() + area.height() - actual.bottom)
    pet.snap_enabled = True
    rect = _attach_screen_anchor(pet, app)
    actual = pet._body_visible_rect()
    envelope = Rect(actual.left - 40, actual.top, actual.right + 60, actual.bottom)
    monkeypatch.setattr(pet, "_cursor_walk_rect", Mock(return_value=envelope))
    monkeypatch.setattr(pet, "_collect_snap_surfaces", lambda: pet.snap_surfaces)

    x_before = pet.x()
    _start_cursor_walk(pet, monkeypatch, dx=0)
    assert pet.x() == x_before
    expected_ratio = (x_before + envelope.center_x - rect.left) / rect.width
    assert pet.snap_anchor.ratio == pytest.approx(expected_ratio)

    _enter_walk_loop(pet)
    pet._update_snap()
    assert pet.x() == x_before

    pet._cancel_cursor_play()
    pet.advance_frame()
    assert pet.current_name == "walk_pst"
    pet.advance_frame()
    assert pet._controller_is_idle()

    changed_idle = Rect(actual.left + 35, actual.top, actual.right + 35, actual.bottom)
    monkeypatch.setattr(pet, "_body_visible_rect", lambda: changed_idle)
    pet._update_snap()

    assert pet.x() == x_before
    assert pet.snap_reference_rect == changed_idle
    assert not pet._cursor_rebase_on_idle
    expected_ratio = (x_before + changed_idle.center_x - rect.left) / rect.width
    assert pet.snap_anchor.ratio == pytest.approx(expected_ratio)


def test_feed_stops_owned_walk_through_recovery_before_eating(pet, monkeypatch):
    _start_cursor_walk(pet, monkeypatch, dx=70)
    _enter_walk_loop(pet)

    _stub_tick(monkeypatch, pet, CursorCue(dx=35))
    pet._tick_cursor_play(pointer=QPoint(pet.x() + 300, pet.y() + 220), now=10.1)
    stopped_x = pet.x()
    assert pet._cursor_walk_owned

    pet._user_reaction("feed")
    assert pet.controller.active_action == "walk"
    assert pet.controller.pending_action == "eat"
    assert not pet._cursor_walk_owned

    # The cursor cue is deliberately hostile here; the queued human action owns
    # the recovery and must prevent further cursor-driven displacement.
    _stub_tick(monkeypatch, pet, CursorCue(dx=200))
    pet._tick_cursor_play(pointer=QPoint(pet.x() + 300, pet.y() + 220), now=10.2)
    assert pet.x() == stopped_x

    pet.advance_frame()
    assert pet.current_name == "walk_pst"
    assert pet.controller.pending_action == "eat"
    assert pet.x() == stopped_x
    pet.advance_frame()
    assert pet.current_name == "eat_carrot"
    assert pet.controller.active_action == "eat"


@pytest.mark.parametrize("lifecycle", ["hide", "minimize", "close"])
def test_window_lifecycle_stops_cursor_timer_and_cancels_owned_walk(
    pet, app, monkeypatch, lifecycle
):
    _start_cursor_walk(pet, monkeypatch, dx=0)
    assert pet._cursor_walk_owned
    cancel = Mock(wraps=pet.cursor_play.cancel)
    monkeypatch.setattr(pet.cursor_play, "cancel", cancel)

    if lifecycle == "hide":
        pet.hide()
    elif lifecycle == "minimize":
        pet.setWindowState(Qt.WindowState.WindowMinimized)
        pet.changeEvent(QEvent(QEvent.Type.WindowStateChange))
        app.processEvents()
    else:
        pet.close()

    assert not pet.cursor_timer.isActive()
    assert not pet._cursor_walk_owned
    assert cancel.called


def test_disabled_policy_cancels_cursor_play_before_a_new_walk(pet, monkeypatch):
    pet.policy.set_enabled(False)
    tick = _stub_tick(monkeypatch, pet, CursorCue(action="walk", direction="right"))

    pet._tick_cursor_play(pointer=QPoint(pet.x() + 300, pet.y() + 220), now=10.0)

    tick.assert_not_called()
    assert pet.controller.active_action == "idle"
    assert not pet._cursor_walk_owned


def test_direction_turn_keeps_capture_frame_in_sync(pet):
    _attach_screen_anchor(pet, QApplication.instance())
    pet.toggle_capture_window(True)
    capture = pet.capture_window
    assert capture is not None and capture.isVisible()
    initial_paths = capture.frame_paths
    assert initial_paths is not None and not initial_paths[2]

    _stub_tick_for_turn = Mock(return_value=CursorCue(direction="left"))
    pet.cursor_play.tick = _stub_tick_for_turn
    pet._tick_cursor_play(pointer=QPoint(pet.x() + 300, pet.y() + 220), now=10.0)

    assert pet.direction == "left"
    assert capture.frame_paths == (
        pet.current_clip.frames[pet.current_skin][pet.current_index],
        None,
        pet.current_mirror,
    )
    assert capture.frame_paths[0] != initial_paths[0]
    assert capture.frame_paths[2] is True
    assert (capture.width(), capture.height()) == pet._capture_canvas()
