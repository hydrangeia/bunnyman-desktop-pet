"""Silent, bounded reactions to deliberate nearby cursor movement."""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

from snap_geometry import Rect


@dataclass(frozen=True)
class CursorCue:
    action: str | None = None
    direction: str | None = None
    dx: float = 0.0


class _MotionWindow:
    """Track one continuous, local, non-linear pointer gesture."""

    MAX_SAMPLE_GAP = 0.4
    MAX_SPEED_PER_WIDTH = 2.5
    MAX_STEP_PER_WIDTH = 0.6
    MIN_STEP_PER_WIDTH = 0.035
    MAX_SPAN_PER_WIDTH = 1.2
    MAX_PATH_PER_WIDTH = 3.0
    STILL_GAP = 0.28

    def __init__(self):
        self.previous: tuple[float, float] | None = None
        self.previous_at: float | None = None
        self.started_at: float | None = None
        self.started_at_point: tuple[float, float] | None = None
        self.last_motion_at: float | None = None
        self.path = 0.0
        self.samples = 0
        self.min_x = self.max_x = 0.0
        self.min_y = self.max_y = 0.0

    def clear(self):
        self.__init__()

    def reset(self, pointer: tuple[float, float], now: float):
        self.clear()
        self.previous = (float(pointer[0]), float(pointer[1]))
        self.previous_at = now

    def _clear_candidate(self):
        self.started_at = None
        self.started_at_point = None
        self.last_motion_at = None
        self.path = 0.0
        self.samples = 0
        self.min_x = self.max_x = 0.0
        self.min_y = self.max_y = 0.0

    @staticmethod
    def _distance_to_rect(point: tuple[float, float], body: Rect) -> float:
        x, y = point
        dx = max(body.left - x, 0.0, x - body.right)
        dy = max(body.top - y, 0.0, y - body.bottom)
        return math.hypot(dx, dy)

    def _near(self, point: tuple[float, float], body: Rect) -> bool:
        width = body.width
        return width > 0 and self._distance_to_rect(point, body) <= max(36.0, 1.5 * width)

    def update(self, pointer: tuple[float, float], body: Rect, now: float):
        point = (float(pointer[0]), float(pointer[1]))
        if not all(math.isfinite(value) for value in point) or not self._near(point, body):
            self.clear()
            return False
        if self.previous is None or self.previous_at is None:
            self.reset(point, now)
            return False

        dt = now - self.previous_at
        old = self.previous
        self.previous = point
        self.previous_at = now
        if dt <= 0 or dt > self.MAX_SAMPLE_GAP:
            self._clear_candidate()
            return False

        width = body.width
        distance = math.hypot(point[0] - old[0], point[1] - old[1])
        if (distance > max(24.0, self.MAX_STEP_PER_WIDTH * width)
                or distance / dt > self.MAX_SPEED_PER_WIDTH * width):
            self._clear_candidate()
            return False

        min_step = max(2.0, self.MIN_STEP_PER_WIDTH * width)
        if distance < min_step:
            if (self.started_at is not None and self.last_motion_at is not None
                    and now - self.last_motion_at > self.STILL_GAP):
                self._clear_candidate()
            return False

        if self.started_at is None:
            self.started_at = now - dt
            self.started_at_point = old
            self.last_motion_at = now
            self.min_x = min(old[0], point[0])
            self.max_x = max(old[0], point[0])
            self.min_y = min(old[1], point[1])
            self.max_y = max(old[1], point[1])
        self.last_motion_at = now
        self.path += distance
        self.samples += 1
        self.min_x = min(self.min_x, point[0])
        self.max_x = max(self.max_x, point[0])
        self.min_y = min(self.min_y, point[1])
        self.max_y = max(self.max_y, point[1])

        if (self.path > self.MAX_PATH_PER_WIDTH * width
                or self.max_x - self.min_x > self.MAX_SPAN_PER_WIDTH * width
                or self.max_y - self.min_y > self.MAX_SPAN_PER_WIDTH * width):
            self._clear_candidate()
            return False
        return False

    def qualifies(self, body: Rect, *, follow_up=False) -> bool:
        if self.started_at is None or self.started_at_point is None or self.last_motion_at is None:
            return False
        width = body.width
        duration = self.last_motion_at - self.started_at
        net = math.hypot(self.previous[0] - self.started_at_point[0],
                         self.previous[1] - self.started_at_point[1])
        if follow_up:
            min_duration, min_path, min_samples, net_ratio = 0.35, 0.16 * width, 3, 0.72
        else:
            min_duration, min_path, min_samples, net_ratio = 0.9, 0.34 * width, 6, 0.65
        return (duration >= min_duration and self.path >= min_path
                and self.samples >= min_samples and net <= net_ratio * self.path)


class CursorPlay:
    """Turn deliberate nearby cursor movement into a short, safe rabbit play cue.

    The caller owns animation playback and physical placement. This policy emits
    only finite action intentions and bounded horizontal movement increments.
    """

    WATCH_CHANCE = 0.68
    WATCH_WINDOW = 5.0
    CHASE_LIMIT = 2.0
    CHASE_DISTANCE_PER_WIDTH = 0.75
    CHASE_SPEED_PER_WIDTH = 0.28125  # 45 px/s for a 160 px visible body.
    CHASE_TICK_CAP = 0.15
    CHASE_SAMPLE_GAP = 0.4
    POINTER_STILL_LIMIT = 0.7
    COOLDOWN = 12.0
    INTERRUPT_COOLDOWN = 2.0
    NEAR_PER_WIDTH = 1.5
    REACH_PER_WIDTH = 0.12

    def __init__(self, clock=time.monotonic, rng=None):
        self.clock = clock
        self.rng = rng if rng is not None else random.Random()
        self._motion = _MotionWindow()
        self._phase = 'gather'
        self._cooldown_until = float('-inf')
        self._watch_started = None
        self._watch_had_earrub = False
        self._chase_started = None
        self._chase_direction = None
        self._chase_distance = 0.0
        self._chase_last_tick = None
        self._chase_last_pointer = None
        self._chase_last_pointer_motion = None

    @property
    def chasing(self) -> bool:
        return self._phase == 'chase'

    def _clear_episode(self):
        self._motion.clear()
        self._watch_started = None
        self._watch_had_earrub = False
        self._chase_started = None
        self._chase_direction = None
        self._chase_distance = 0.0
        self._chase_last_tick = None
        self._chase_last_pointer = None
        self._chase_last_pointer_motion = None

    def _cool(self, now: float, duration: float, *, replace=False):
        deadline = now + duration
        self._clear_episode()
        self._phase = 'cooldown'
        self._cooldown_until = deadline if replace else max(self._cooldown_until, deadline)

    def cancel(self, now=None):
        """Forget cursor history after user input and briefly suppress retriggers."""
        now = self.clock() if now is None else now
        self._cool(now, self.INTERRUPT_COOLDOWN, replace=True)

    @staticmethod
    def _direction(pointer, body, fallback=None):
        delta = pointer[0] - body.center_x
        if delta < -2.0:
            return 'left'
        if delta > 2.0:
            return 'right'
        return fallback

    @staticmethod
    def _distance_to_body(pointer, body):
        x, y = pointer
        dx = max(body.left - x, 0.0, x - body.right)
        dy = max(body.top - y, 0.0, y - body.bottom)
        return math.hypot(dx, dy)

    def _pointer_is_near(self, pointer, body):
        return self._distance_to_body(pointer, body) <= max(36.0, self.NEAR_PER_WIDTH * body.width)

    def _is_reached(self, pointer, body):
        return self._distance_to_body(pointer, body) <= max(8.0, self.REACH_PER_WIDTH * body.width)

    def _start_watch(self, pointer, body, now):
        direction = self._direction(pointer, body)
        self._phase = 'watch'
        self._watch_started = now
        self._watch_had_earrub = False
        self._motion.reset(pointer, now)
        return CursorCue(action='earrub', direction=direction)

    def _start_chase(self, pointer, body, now):
        direction = self._direction(pointer, body, self._chase_direction)
        if direction is None:
            direction = 'right'
        self._phase = 'chase'
        self._chase_started = now
        self._chase_direction = direction
        self._chase_distance = 0.0
        self._chase_last_tick = now
        self._chase_last_pointer = (float(pointer[0]), float(pointer[1]))
        self._chase_last_pointer_motion = now
        self._motion.clear()
        return CursorCue(action='walk', direction=direction, dx=0.0)

    def _stop_chase(self, pointer, body, now, reason):
        if self._is_reached(pointer, body):
            action = 'happy'
        elif reason in {'lost', 'far'}:
            action = 'abandon'
        else:
            action = 'earrub'
        direction = self._direction(pointer, body, self._chase_direction)
        self._cool(now, self.COOLDOWN)
        return CursorCue(action=action, direction=direction)

    def _tick_watch(self, *, pointer, body, idle, active_action, can_move, style, now):
        if active_action not in {'idle', 'earrub'}:
            self._cool(now, self.INTERRUPT_COOLDOWN)
            return None
        if now - self._watch_started > self.WATCH_WINDOW:
            self._cool(now, self.COOLDOWN)
            return None

        if active_action == 'earrub':
            self._watch_had_earrub = True
        self._motion.update(pointer, body, now)

        if active_action != 'idle' or not self._watch_had_earrub or not idle:
            return None
        if style == 'quiet':
            self._cool(now, self.COOLDOWN)
            return None
        if not self._motion.qualifies(body, follow_up=True):
            return None
        if not can_move:
            self._cool(now, self.COOLDOWN)
            return None
        if self._direction(pointer, body) is None:
            self._cool(now, self.COOLDOWN)
            return None
        return self._start_chase(pointer, body, now)

    def _tick_chase(self, *, pointer, body, active_action, can_move, style, now):
        if active_action != 'walk':
            self._cool(now, self.INTERRUPT_COOLDOWN)
            return None
        if style == 'quiet':
            return self._stop_chase(pointer, body, now, 'tired')
        if not can_move:
            return self._stop_chase(pointer, body, now, 'tired')

        try:
            current_pointer = (float(pointer[0]), float(pointer[1]))
        except (TypeError, ValueError, OverflowError):
            current_pointer = (float('nan'), float('nan'))
        if not all(math.isfinite(value) for value in current_pointer):
            direction = self._chase_direction
            self._cool(now, self.COOLDOWN)
            return CursorCue(action='abandon', direction=direction)

        started = self._chase_started
        previous_at = self._chase_last_tick
        previous_pointer = self._chase_last_pointer
        dt = now - previous_at if previous_at is not None else 0.0
        self._chase_last_tick = now

        if self._is_reached(current_pointer, body):
            return self._stop_chase(current_pointer, body, now, 'reached')
        if not self._pointer_is_near(current_pointer, body):
            return self._stop_chase(current_pointer, body, now, 'far')
        elapsed = now - started
        if elapsed >= self.CHASE_LIMIT or self._chase_distance >= self.CHASE_DISTANCE_PER_WIDTH * body.width:
            return self._stop_chase(current_pointer, body, now, 'tired')

        pointer_step = math.hypot(current_pointer[0] - previous_pointer[0],
                                  current_pointer[1] - previous_pointer[1])
        if dt > 0 and (pointer_step > max(24.0, 0.6 * body.width)
                       or pointer_step / dt > 2.5 * body.width):
            return self._stop_chase(current_pointer, body, now, 'lost')
        if dt <= 0 or dt > self.CHASE_SAMPLE_GAP:
            self._chase_last_pointer = current_pointer
            return CursorCue(direction=self._chase_direction)

        if pointer_step >= max(2.0, 0.035 * body.width):
            self._chase_last_pointer_motion = now
        elif (self._chase_last_pointer_motion is not None
              and now - self._chase_last_pointer_motion >= self.POINTER_STILL_LIMIT - 1e-9):
            return self._stop_chase(current_pointer, body, now, 'lost')

        self._chase_last_pointer = current_pointer
        toward = self._direction(current_pointer, body)
        if toward is not None:
            self._chase_direction = toward
        direction = self._chase_direction

        step_dt = min(dt, self.CHASE_TICK_CAP)
        max_dx = self.CHASE_SPEED_PER_WIDTH * body.width * step_dt
        dx = 0.0
        if toward == 'left':
            dx = -max_dx
        elif toward == 'right':
            dx = max_dx
        dx = max(-max_dx, min(max_dx, dx))
        self._chase_distance += abs(dx)
        return CursorCue(direction=direction, dx=dx)

    def tick(self, *, pointer: tuple[float, float], body: Rect, idle: bool,
             active_action: str, pending: bool = False, blocked: bool = False,
             enabled: bool = True, style: str = 'lively', can_move: bool = True,
             now=None) -> CursorCue | None:
        """Advance the silent play policy once, normally every 100 ms.

        ``dx`` is signed and bounded by elapsed time, body width, and a short
        per-tick cap. Starting and stopping locomotion are action cues for the
        caller's animation controller.
        """
        now = self.clock() if now is None else now
        if style not in {'lively', 'quiet'}:
            raise ValueError(f'Unknown interaction style: {style}')
        if blocked or pending or not enabled:
            self._cool(now, self.INTERRUPT_COOLDOWN)
            return None

        if self._phase == 'cooldown':
            if now < self._cooldown_until:
                return None
            self._phase = 'gather'
            self._motion.clear()

        if self._phase == 'chase':
            return self._tick_chase(pointer=pointer, body=body,
                                    active_action=active_action, can_move=can_move,
                                    style=style, now=now)
        if self._phase == 'watch':
            return self._tick_watch(pointer=pointer, body=body, idle=idle,
                                    active_action=active_action, can_move=can_move,
                                    style=style, now=now)

        if not idle or active_action != 'idle':
            self._cool(now, self.INTERRUPT_COOLDOWN)
            return None
        self._motion.update(pointer, body, now)
        if not self._motion.qualifies(body):
            return None
        if self.rng.random() >= self.WATCH_CHANCE:
            self._cool(now, self.COOLDOWN)
            return None
        return self._start_watch(pointer, body, now)
