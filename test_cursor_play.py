import math
import random

from cursor_play import CursorCue, CursorPlay
from snap_geometry import Rect


BODY = Rect(100, 100, 260, 260)


def _wave(index):
    angle = 2 * math.pi * index / 8
    return 325 + 16 * math.cos(angle), 320 + 16 * math.sin(angle)


def _pet():
    return CursorPlay(rng=random.Random(1))


def _reach_watch(pet, *, style='lively'):
    for index in range(30):
        now = index / 10
        cue = pet.tick(pointer=_wave(index), body=BODY, idle=True,
                       active_action='idle', style=style, now=now)
        if cue is not None and cue.action == 'earrub':
            return pet, index, cue
    raise AssertionError('The deliberate nearby gesture did not get a watch response')


def _reach_chase(pet=None, *, style='lively'):
    pet = pet or _pet()
    pet, watch_index, watch = _reach_watch(pet, style=style)
    assert watch.direction in {'left', 'right'}
    # The finite watch animation runs while more nearby motion is collected.
    for offset in range(1, 10):
        index = watch_index + offset
        pet.tick(pointer=_wave(index), body=BODY, idle=False,
                 active_action='earrub', style=style, now=index / 10)
    for offset in range(10, 30):
        index = watch_index + offset
        cue = pet.tick(pointer=_wave(index), body=BODY, idle=True,
                       active_action='idle', style=style, now=index / 10)
        if cue is not None and cue.action == 'walk':
            return pet, index, cue
    raise AssertionError('The follow-up gesture did not start a lively chase')


def test_cue_shape_and_starting_chase_does_not_move_immediately():
    pet, _, cue = _reach_chase()

    assert isinstance(cue, CursorCue)
    assert cue.action == 'walk'
    assert cue.direction in {'left', 'right'}
    assert cue.dx == 0
    assert pet.chasing


def test_stationary_far_and_one_pass_pointer_motion_do_not_trigger_watch():
    pet = _pet()
    stationary = (320, 180)
    cue = None
    for sample in range(16):
        cue = pet.tick(pointer=stationary, body=BODY, idle=True,
                       active_action='idle', now=sample / 10)
    assert cue is None

    far = _pet()
    for sample in range(16):
        cue = far.tick(pointer=(800 + 8 * sample, 180), body=BODY, idle=True,
                       active_action='idle', now=sample / 10)
    assert cue is None

    crossing = _pet()
    for sample in range(20):
        cue = crossing.tick(pointer=(300 + 7 * sample, 180), body=BODY,
                            idle=True, active_action='idle', now=sample / 10)
    assert cue is None


def test_teleport_and_long_sampling_gap_break_motion_history():
    pet = _pet()
    for index in range(6):
        cue = pet.tick(pointer=_wave(index), body=BODY, idle=True,
                       active_action='idle', now=index / 10)
    assert cue is None

    cue = pet.tick(pointer=(1000, 900), body=BODY, idle=True,
                   active_action='idle', now=0.6)
    assert cue is None
    cue = pet.tick(pointer=(325, 320), body=BODY, idle=True,
                   active_action='idle', now=1.2)
    assert cue is None
    for index in range(13, 25):
        cue = pet.tick(pointer=(325, 320), body=BODY, idle=True,
                       active_action='idle', now=index / 10)
        assert cue is None


def test_chase_steps_are_time_bounded_and_long_pause_cannot_create_a_leap():
    pet, index, _ = _reach_chase()
    first = pet.tick(pointer=_wave(index + 1), body=BODY, idle=False,
                     active_action='walk', now=(index + 1) / 10)
    assert first is not None
    assert abs(first.dx) <= 45 * 0.1 + 1e-9

    paused = pet.tick(pointer=_wave(index + 6), body=BODY, idle=False,
                      active_action='walk', now=(index + 6) / 10)
    assert paused is not None
    assert paused.dx == 0
    assert pet.chasing


def test_stationary_target_ends_chase_without_continuing_to_move():
    pet, index, _ = _reach_chase()
    pointer = _wave(index)
    for offset in range(1, 8):
        cue = pet.tick(pointer=pointer, body=BODY, idle=False,
                       active_action='walk', now=(index / 10) + offset / 10)
        if cue is not None and cue.action is not None:
            break

    assert cue is not None
    assert cue.action in {'abandon', 'earrub'}
    assert cue.dx == 0
    assert not pet.chasing


def test_chase_stops_when_movement_becomes_unsafe_but_not_when_blocked():
    pet, index, _ = _reach_chase()
    cue = pet.tick(pointer=_wave(index), body=BODY, idle=False,
                   active_action='walk', can_move=False, now=(index + 1) / 10)
    assert cue is not None and cue.action == 'earrub'
    assert cue.dx == 0
    assert not pet.chasing

    pet, index, _ = _reach_chase()
    cue = pet.tick(pointer=_wave(index + 1), body=BODY, idle=False,
                   active_action='walk', blocked=True, can_move=False,
                   now=(index + 1) / 10)
    assert cue is None
    assert not pet.chasing


def test_quiet_style_never_starts_locomotion():
    pet, watch_index, cue = _reach_watch(_pet(), style='quiet')
    assert cue.action == 'earrub'

    # Continue the same gesture through the finite watch action and its idle gate.
    for offset in range(1, 10):
        index = watch_index + offset
        cue = pet.tick(pointer=_wave(index), body=BODY, idle=False,
                       active_action='earrub', style='quiet', now=index / 10)
        assert cue is None
    index = watch_index + 10
    cue = pet.tick(pointer=_wave(index), body=BODY, idle=True,
                   active_action='idle', style='quiet', now=index / 10)
    assert cue is None
    assert not pet.chasing


def test_disabled_blocked_pending_cancel_and_busy_actions_suppress_policy():
    for kwargs in ({'blocked': True}, {'pending': True}, {'enabled': False}):
        pet = _pet()
        for index in range(8):
            cue = pet.tick(pointer=_wave(index), body=BODY, idle=True,
                           active_action='idle', now=index / 10, **kwargs)
            assert cue is None
            assert not pet.chasing

    pet, index, _ = _reach_chase()
    # Explicit input owns the animation; policy resets without a cleanup action.
    cue = pet.tick(pointer=_wave(index + 1), body=BODY, idle=False,
                   active_action='walk', pending=True, now=(index + 1) / 10)
    assert cue is None
    assert not pet.chasing

    pet = _pet()
    for sample in range(5):
        pet.tick(pointer=_wave(sample), body=BODY, idle=True,
                  active_action='idle', now=sample / 10)
    cue = pet.tick(pointer=_wave(6), body=BODY, idle=False,
                   active_action='sleep', now=0.6)
    assert cue is None
    assert not pet.chasing

    pet.cancel(now=1.0)
    cue = pet.tick(pointer=_wave(20), body=BODY, idle=True,
                   active_action='idle', now=1.1)
    assert cue is None


def test_unexpected_menu_or_drag_state_does_not_emit_chase_cleanup():
    pet, index, _ = _reach_chase()
    cue = pet.tick(pointer=_wave(index + 1), body=BODY, idle=False,
                   active_action='walk', blocked=True, now=(index + 1) / 10)
    assert cue is None
    assert not pet.chasing

    pet, index, _ = _reach_chase()
    cue = pet.tick(pointer=_wave(index + 1), body=BODY, idle=False,
                   active_action='attack_pillow', now=(index + 1) / 10)
    assert cue is None
    assert not pet.chasing


def test_chase_stops_after_duration_and_applies_full_cooldown():
    pet, index, _ = _reach_chase()
    start = index / 10
    cue = None
    for offset in range(1, 22):
        sample_index = index + offset
        cue = pet.tick(pointer=_wave(sample_index), body=BODY, idle=False,
                       active_action='walk', now=start + offset / 10)
        if cue is not None and cue.action is not None:
            break
    assert cue is not None and cue.action == 'earrub'
    assert not pet.chasing

    for offset in range(1, 120):
        cue = pet.tick(pointer=_wave(index + 22 + offset), body=BODY, idle=True,
                       active_action='idle', now=start + 2.1 + offset / 10)
        assert cue is None


def test_distance_cap_stops_chase_and_starts_cooldown():
    pet, index, _ = _reach_chase()
    pet.CHASE_LIMIT = 10.0
    pet.CHASE_DISTANCE_PER_WIDTH = 0.08
    start = index / 10
    cue = None
    for offset in range(1, 20):
        sample_index = index + offset
        cue = pet.tick(pointer=_wave(sample_index), body=BODY, idle=False,
                       active_action='walk', now=start + offset / 10)
        if cue is not None and cue.action is not None:
            break

    assert cue is not None and cue.action == 'earrub'
    assert not pet.chasing
    cue = pet.tick(pointer=_wave(index + 30), body=BODY, idle=True,
                   active_action='idle', now=start + 3.0)
    assert cue is None


def test_pending_and_finite_stop_animation_preserve_natural_chase_cooldown():
    pet, index, _ = _reach_chase()
    stopped_at = index / 10 + 0.1
    cue = pet.tick(pointer=(250, 180), body=BODY, idle=False,
                   active_action='walk', now=stopped_at)
    assert cue is not None and cue.action == 'happy'
    assert not pet.chasing

    # The controller queues happy while walk exits, then plays its finite clip.
    for offset in range(2, 6):
        cue = pet.tick(pointer=_wave(index + offset), body=BODY, idle=False,
                       active_action='happy', pending=True,
                       now=stopped_at + offset / 10)
        assert cue is None
    for offset in range(6, 20):
        cue = pet.tick(pointer=_wave(index + offset), body=BODY, idle=False,
                       active_action='happy',
                       now=stopped_at + offset / 10)
        assert cue is None

    # Repeated deliberate motion after the animation still cannot retrigger
    # during the natural 12-second chase cooldown.
    for offset in range(20, 120):
        cue = pet.tick(pointer=_wave(index + offset), body=BODY, idle=True,
                       active_action='idle',
                       now=stopped_at + offset / 10)
        assert cue is None


def test_nonfinite_pointer_stops_a_chase_without_movement():
    pet, index, _ = _reach_chase()
    cue = pet.tick(pointer=(float('nan'), 320), body=BODY, idle=False,
                   active_action='walk', now=(index + 1) / 10)

    assert cue is not None
    assert cue.action == 'abandon'
    assert cue.dx == 0
    assert not pet.chasing
