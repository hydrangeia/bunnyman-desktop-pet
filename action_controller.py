"""Complete rabbit actions and their safe interruption points, independent of Qt.

Game clips checked against stategraphs/SGcozy_bunnyman.lua and
stategraphs/commonstates.lua. The pet's dig action combines the game's hide
and emerge animations so a desktop interaction always returns above ground.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    clip: str
    mode: str = 'once'


@dataclass(frozen=True)
class ActionSpec:
    label: str
    group: str
    steps: tuple[Step, ...]
    exit_steps: tuple[Step, ...] = ()


def _steps(*names):
    return tuple(Step(name) for name in names)


def _catalog(idle):
    return {
        'idle': ActionSpec('待机', '日常互动', (Step(idle, 'loop'),)),
        'happy': ActionSpec('开心', '日常互动', _steps('idle_happy')),
        'earrub': ActionSpec('揉耳朵', '日常互动', _steps('idle_earrub')),
        'dance': ActionSpec('跳舞', '日常互动', _steps('dance')),
        'eat': ActionSpec('吃东西', '日常互动', _steps('eat')),
        'hungry': ActionSpec('肚子饿', '日常互动', _steps('hungry')),
        'angry': ActionSpec('生气', '日常互动', _steps('idle_angry')),
        'creepy': ActionSpec('诡笑', '日常互动', _steps('idle_creepy')),
        'disgust': ActionSpec('嫌弃', '日常互动', _steps('disgust')),
        'pickup': ActionSpec('拾取', '日常互动', _steps('pig_pickup')),
        'take': ActionSpec('接受礼物', '日常互动', _steps('pig_take')),
        'reject': ActionSpec('拒绝礼物', '日常互动', _steps('pig_reject')),
        'sleep': ActionSpec('睡觉', '休息与状态',
                            (Step('sleep_pre'), Step('sleep_loop', 'loop')), _steps('sleep_pst')),
        'wake': ActionSpec('醒来', '休息与状态', (Step(idle, 'loop'),)),
        'alert': ActionSpec('警觉', '休息与状态',
                            (Step('alert_pre'), Step('alert_loop', 'loop')), _steps('alert_pst')),
        'freeze': ActionSpec('冰冻', '休息与状态',
                             (Step('frozen', 'hold'),), _steps('frozen_loop_pst')),
        'thaw': ActionSpec('解冻', '休息与状态', (Step(idle, 'loop'),)),
        'shock': ActionSpec('触电', '休息与状态',
                            (Step('shock_loop', 'loop'),), _steps('shock_pst')),
        'walk': ActionSpec('走路', '移动与跳跃',
                           (Step('walk_pre'), Step('walk_loop', 'loop')), _steps('walk_pst')),
        'run': ActionSpec('跑步', '移动与跳跃',
                          (Step('run_pre'), Step('run_loop', 'loop')), _steps('run_pst')),
        'jump': ActionSpec('跳跃并落地', '移动与跳跃',
                           _steps('boat_jump_pre', 'boat_jump', 'boat_jump_loop', 'boat_jump_pst')),
        'dig': ActionSpec('钻地再钻出', '移动与跳跃',
                          _steps('despawn', 'spawn_pre', 'spawn_loop', 'spawn_pst')),
        'abandon': ActionSpec('放弃追逐', '移动与跳跃', _steps('abandon')),
        'attack': ActionSpec('攻击', '枕头与战斗', _steps('atk')),
        'attack_pillow': ActionSpec('举枕头并挥打', '枕头与战斗',
                                    _steps('atk_object_pre', 'idle_loop_overhead', 'atk_object')),
        'hold_pillow': ActionSpec('举枕头待机', '枕头与战斗',
                                  (Step('atk_object_pre'), Step('idle_loop_overhead', 'loop')),
                                  _steps('pillow_putdown')),
        'walk_pillow': ActionSpec('举枕头走路', '枕头与战斗',
                                  (Step('atk_object_pre'), Step('walk_overhead_pre'),
                                   Step('walk_overhead_loop', 'loop')),
                                  _steps('walk_overhead_pst', 'pillow_putdown')),
        'hit': ActionSpec('受击', '枕头与战斗', _steps('hit')),
        'hit_big': ActionSpec('受到重击', '枕头与战斗', _steps('hit_big')),
        'death': ActionSpec('倒下', '枕头与战斗',
                            (Step('death'), Step('corpse', 'hold')),
                            _steps('spawn_pre', 'spawn_loop', 'spawn_pst')),
    }


ALIASES = {
    'idle_loop':'idle', 'idle_happy':'happy', 'idle_earrub':'earrub',
    'eat_carrot':'eat',
    'idle_angry':'angry', 'idle_creepy':'creepy',
    'pig_pickup':'pickup', 'pig_take':'take', 'pig_reject':'reject',
    'sleep_pre':'sleep', 'sleep_loop':'sleep', 'sleep_pst':'wake',
    'walk_pre':'walk', 'walk_loop':'walk', 'walk_pst':'idle',
    'run_pre':'run', 'run_loop':'run', 'run_pst':'idle',
    'alert_pre':'alert', 'alert_loop':'alert', 'alert_pst':'idle',
    'shock_loop':'shock', 'shock_pst':'idle',
    'frozen':'freeze', 'frozen_loop_pst':'thaw',
    'despawn':'dig', 'spawn_pre':'dig', 'spawn_loop':'dig', 'spawn_pst':'dig',
    'boat_jump_pre':'jump', 'boat_jump':'jump', 'boat_jump_loop':'jump', 'boat_jump_pst':'jump',
    'atk':'attack', 'atk_object_pre':'attack_pillow', 'atk_object':'attack_pillow',
    'idle_loop_overhead':'hold_pillow', 'walk_overhead_pre':'walk_pillow',
    'walk_overhead_loop':'walk_pillow', 'walk_overhead_pst':'idle', 'corpse':'death',
}


class ActionController:
    """Queue the latest intention and finish physical recovery before switching.

    request() returns a Step only when playback may change immediately. Otherwise
    the renderer finishes the current clip, then calls finish_clip(), including
    at loop boundaries. Requests during finite sequences replace the pending
    destination; they never discard a wake, landing, or emergence segment.
    """
    def __init__(self, available_names, default_idle='idle_loop', initial_clip=None):
        self.available = set(available_names)
        self.default_idle = default_idle
        if default_idle not in self.available:
            raise ValueError('The default idle clip is required')
        catalog = _catalog(default_idle)
        if 'eat_carrot' in self.available:
            old_eat = catalog['eat']
            catalog['eat'] = ActionSpec(old_eat.label, old_eat.group,
                                        _steps('eat_carrot'), old_eat.exit_steps)
        # Older manifests do not contain the generated release clips. Keep
        # their previous pillow transitions usable while new exports get the
        # fully animated putdown sequence.
        if 'pillow_putdown' not in self.available:
            catalog['hold_pillow'] = ActionSpec(
                '举枕头待机', '枕头与战斗',
                (Step('atk_object_pre'), Step('idle_loop_overhead', 'loop')),
                _steps('atk_object'),
            )
            catalog['walk_pillow'] = ActionSpec(
                '举枕头走路', '枕头与战斗',
                (Step('atk_object_pre'), Step('walk_overhead_pre'),
                 Step('walk_overhead_loop', 'loop')),
                _steps('walk_overhead_pst', 'atk_object'),
            )
        self.actions = {
            key: spec for key,spec in catalog.items()
            if all(s.clip in self.available for s in spec.steps + spec.exit_steps)
        }
        self.active_action = 'idle'
        self.pending_action = None
        self._stage = 'body'
        self._remaining = []
        self.current = Step(default_idle,'loop')
        if initial_clip and initial_clip != default_idle:
            self._resume_clip(initial_clip)

    @property
    def action_ids(self):
        return list(self.actions)

    def _begin(self, action):
        if action in ('wake','thaw'):
            action = 'idle'
        self.active_action = action
        self._stage = 'body'
        self._remaining = list(self.actions[action].steps)
        self.current = self._remaining.pop(0)
        return self.current

    def _resume_clip(self, clip):
        if clip not in self.available:
            raise ValueError(f'Unknown initial clip: {clip}')
        if clip == 'corpse_hit' and 'death' in self.actions:
            self.actions['_preview'] = ActionSpec(
                '倒地预览收尾','开发预览', (Step(clip),Step('corpse','hold')),
                self.actions['death'].exit_steps)
            self.active_action = '_preview'
            self.current = Step(clip)
            self._remaining = [Step('corpse','hold')]
            return
        if clip == 'trans_beard_pre' and 'trans_rabbit_pst' in self.available:
            self.actions['_preview'] = ActionSpec(
                '变化预览收尾','开发预览', _steps(clip,'trans_rabbit_pst'))
            self.active_action = '_preview'
            self.current = Step(clip)
            self._remaining = [Step('trans_rabbit_pst')]
            return
        # Raw previews can end in a sleeping, underground, or frozen pose. Infer
        # the appropriate recovery rather than treating every pose as standing.
        preferred = {
            'sleep_pre':'sleep', 'sleep_loop':'sleep', 'sleep_pst':'sleep',
            'walk_pre':'walk', 'walk_loop':'walk', 'walk_pst':'walk',
            'run_pre':'run', 'run_loop':'run', 'run_pst':'run',
            'alert_pre':'alert', 'alert_loop':'alert', 'alert_pst':'alert',
            'frozen':'freeze', 'frozen_loop_pst':'freeze',
            'shock_loop':'shock', 'shock_pst':'shock',
            'despawn':'dig', 'spawn_pre':'dig', 'spawn_loop':'dig', 'spawn_pst':'dig',
            'boat_jump_pre':'jump', 'boat_jump':'jump', 'boat_jump_loop':'jump', 'boat_jump_pst':'jump',
            'atk_object_pre':'attack_pillow', 'atk_object':'attack_pillow',
            'idle_loop_overhead':'hold_pillow', 'walk_overhead_pre':'walk_pillow',
            'walk_overhead_loop':'walk_pillow', 'walk_overhead_pst':'walk_pillow',
            'death':'death', 'corpse':'death',
        }.get(clip)
        if preferred in self.actions:
            self.active_action = preferred
            spec = self.actions[preferred]
            for stage,steps in [('body',spec.steps), ('exit',spec.exit_steps)]:
                for index,step in enumerate(steps):
                    if step.clip == clip:
                        self._stage = stage
                        self.current = step
                        self._remaining = list(steps[index+1:])
                        return
        # Unclassified previews still finish their current clip before returning.
        self.actions['_preview'] = ActionSpec('预览收尾','开发预览',(Step(clip),))
        self.active_action = '_preview'
        self.current = Step(clip)

    def request(self, action):
        action = ALIASES.get(action,action)
        if action not in self.actions:
            raise ValueError(f'Unknown or unavailable action: {action}')
        # Wake/thaw are intentions to stand, not free-standing wake animations.
        if action in ('wake','thaw'):
            action = 'idle'
        if action == self.active_action and self._stage == 'body':
            self.pending_action = None
            return None
        self.pending_action = action
        if self.active_action == 'idle':
            self.pending_action = None
            return self._begin(action)
        if self.current.mode == 'hold':
            return self._start_exit()
        return None

    def _complete(self):
        destination = self.pending_action or 'idle'
        self.pending_action = None
        return self._begin(destination)

    def _start_exit(self):
        self._stage = 'exit'
        exit_steps = self.actions[self.active_action].exit_steps
        if self.active_action == 'attack_pillow':
            if (self.current.clip == 'atk_object'
                    and 'pillow_attack_release' in self.available):
                exit_steps = _steps('pillow_attack_release')
            elif 'pillow_putdown' in self.available:
                exit_steps = _steps('pillow_putdown')
        self._remaining = list(exit_steps)
        if not self._remaining:
            return self._complete()
        self.current = self._remaining.pop(0)
        return self.current

    def finish_clip(self):
        if self.current.mode == 'hold':
            return self.current
        if self.current.mode == 'loop':
            if self.pending_action is None:
                return self.current
            return self._start_exit()
        if self._remaining:
            # An interrupted entry may go straight to its exit once the entry
            # finishes. The resting/airborne state is never replaced by idle.
            if (self._stage == 'body' and self.pending_action is not None
                    and self._remaining[0].mode in ('loop','hold')):
                return self._start_exit()
            self.current = self._remaining.pop(0)
            return self.current
        if self._stage == 'exit':
            return self._complete()
        return self._start_exit()
