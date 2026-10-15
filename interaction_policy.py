"""Time-based rabbit reactions, independent of Qt and the animation player."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Reaction:
    action: str | None
    text: str = ''
    source: str = 'user'


class InteractionPolicy:
    PROFILES = {
        'lively': {'interval': (12,24), 'nap_after': 180, 'nap_length': 25, 'hover_cooldown':8},
        'quiet': {'interval': (60,110), 'nap_after': 300, 'nap_length': 60, 'hover_cooldown':25},
    }

    def __init__(self, style='lively', *, clock=time.monotonic, rng=None):
        if style not in self.PROFILES:
            raise ValueError(f'Unknown interaction style: {style}')
        self.clock = clock
        self.rng = rng if rng is not None else random.Random()
        self.style = style
        self.enabled = True
        now = self.clock()
        self.last_user_at = now
        self.last_nap_at = now
        self.auto_sleep_started = None
        self._last_events = {}
        self._pokes = []
        self._wheel_count = 0
        self._wheel_at = float('-inf')
        self._double_count = 0
        self.auto_thaw_at = None
        self._schedule(now)

    def _schedule(self, now):
        self.next_auto_at = now + self.rng.uniform(*self.PROFILES[self.style]['interval'])

    def note_user_activity(self, now=None):
        now = self.clock() if now is None else now
        self.last_user_at = now
        # A user request owns subsequent sleep/wake decisions. An automatic wake
        # must never replace a queued human interaction or wake a manual nap.
        self.auto_sleep_started = None
        self.auto_thaw_at = None
        self._schedule(now)

    def set_style(self, style, now=None):
        if style not in self.PROFILES:
            raise ValueError(f'Unknown interaction style: {style}')
        self.style = style
        thaw_at = self.auto_thaw_at
        self.note_user_activity(now)
        self.auto_thaw_at = thaw_at

    def set_enabled(self, enabled, now=None):
        self.enabled = bool(enabled)
        thaw_at = self.auto_thaw_at
        self.note_user_activity(now)
        self.auto_thaw_at = thaw_at

    def _ready(self, event, now, cooldown):
        if now - self._last_events.get(event,float('-inf')) < cooldown:
            return False
        self._last_events[event] = now
        return True

    def react(self, event, now=None):
        """Produce a user reaction; the UI submits it through ActionController."""
        now = self.clock() if now is None else now
        if event not in {'pet','double_click','feed','drop','play','sleep','wake','hover',
                         'ear_touch','belly_touch','wheel_down','wheel_up','shake'}:
            raise ValueError(f'Unknown interaction: {event}')
        if event == 'hover':
            if not self._ready(event,now,self.PROFILES[self.style]['hover_cooldown']):
                return None
            self.note_user_activity(now)
            return Reaction('happy' if self.style == 'lively' else 'earrub')
        previous_thaw = self.auto_thaw_at
        self.note_user_activity(now)
        if event == 'wheel_down':
            self.auto_thaw_at = previous_thaw
            self._wheel_count = self._wheel_count+1 if now-self._wheel_at<1.5 else 1
            self._wheel_at = now
            if self._wheel_count<3 or not self._ready('cold_surprise',now,8):
                return None
            self._wheel_count = 0
            self.auto_thaw_at = now+4
            return Reaction('freeze')
        if event == 'wheel_up':
            self._wheel_count = 0
            return Reaction('thaw')
        if event == 'ear_touch':
            if not self._ready(event,now,2):
                self.auto_thaw_at = previous_thaw
                return None
            return Reaction('earrub')
        if event == 'belly_touch':
            if not self._ready(event,now,3):
                self.auto_thaw_at = previous_thaw
                return None
            return Reaction('hungry')
        if event == 'shake':
            if not self._ready(event,now,8):
                self.auto_thaw_at = previous_thaw
                return None
            return Reaction('hit_big')
        if event == 'feed':
            if not self._ready(event,now,4):
                self.auto_thaw_at = previous_thaw
                return Reaction(None,'慢点，我还在嚼呢。')
            return Reaction('eat','胡萝卜！')
        if event == 'pet':
            self._pokes = [stamp for stamp in self._pokes if now-stamp<=2]
            self._pokes.append(now)
            if len(self._pokes)>=4 and self._ready('poke_surprise',now,8):
                self._pokes.clear()
                return Reaction('hit')
            if not self._ready(event,now,0.7):
                self.auto_thaw_at = previous_thaw
                return None
            return Reaction('happy','嘿嘿～')
        if event == 'double_click':
            if not self._ready(event,now,1.5):
                self.auto_thaw_at = previous_thaw
                return None
            self._double_count += 1
            action = 'dance' if self._double_count==1 else self.rng.choice(
                ['dance','jump','attack_pillow','dig'])
            return Reaction(action)
        if event == 'drop':
            if not self._ready(event,now,0.8):
                self.auto_thaw_at = previous_thaw
                return None
            return Reaction('happy' if self.rng.random()<0.75 else 'earrub','到啦！')
        if event == 'play':
            return Reaction('attack_pillow','枕头准备好啦！')
        if event == 'sleep':
            return Reaction('sleep','呼……')
        return Reaction('wake','醒啦。')

    def tick(self, *, idle, active_action, pending=False, blocked=False, now=None):
        """Return an autonomous reaction only at a free-standing idle boundary.

        Automatic naps have a timed wake; manually chosen sleep has none. Busy,
        dragging, menus and raw previews suppress new automatic intentions.
        """
        now = self.clock() if now is None else now
        if blocked or pending:
            return None
        if self.auto_thaw_at is not None:
            if active_action == 'freeze' and now>=self.auto_thaw_at:
                self.auto_thaw_at = None
                self._schedule(now)
                return Reaction('thaw','','auto')
            return None
        if not self.enabled:
            return None
        profile = self.PROFILES[self.style]
        if self.auto_sleep_started is not None:
            if active_action == 'sleep' and now-self.auto_sleep_started >= profile['nap_length']:
                self.auto_sleep_started = None
                self.last_nap_at = now
                self._schedule(now)
                return Reaction('wake','', 'auto')
            return None
        if not idle or active_action != 'idle':
            return None
        if (now-self.last_user_at >= profile['nap_after']
                and now-self.last_nap_at >= profile['nap_after']):
            self.auto_sleep_started = now
            self.last_nap_at = now
            self._schedule(now)
            return Reaction('sleep','打个盹……','auto')
        if now < self.next_auto_at:
            return None
        self._schedule(now)
        if self.style == 'quiet':
            action = self.rng.choices(['earrub','happy'],weights=[4,1])[0]
        else:
            action = self.rng.choices(['earrub','happy','dance','hungry','jump','dig','attack_pillow'],
                                      weights=[20,10,5,2,2,1,2])[0]
        return Reaction(action,'','auto')
