import random

from interaction_policy import InteractionPolicy


def policy():
    return InteractionPolicy(clock=lambda:0,rng=random.Random(1))


def test_cold_surprise_requires_three_scrolls_and_eventually_breaks_ice():
    p=policy()
    assert p.react('wheel_down',now=0) is None
    assert p.react('wheel_down',now=0.2) is None
    assert p.react('wheel_down',now=0.4).action=='freeze'
    assert p.tick(idle=False,active_action='freeze',now=4.3) is None
    assert p.tick(idle=False,active_action='freeze',now=4.4).action=='thaw'


def test_extra_scrolls_do_not_cancel_automatic_thaw():
    p=policy()
    for now in [0,0.1,0.2,0.3,0.4]:
        p.react('wheel_down',now=now)
    assert p.auto_thaw_at==4.2
    assert p.tick(idle=False,active_action='freeze',now=4.3).action=='thaw'


def test_auto_activity_toggle_does_not_disable_an_interaction_cleanup():
    p=policy();p.set_enabled(False,now=0)
    for now in [0,0.1,0.2]:
        p.react('wheel_down',now=now)
    assert p.tick(idle=False,active_action='freeze',now=5).action=='thaw'


def test_changing_activity_settings_while_frozen_preserves_thaw():
    p=policy()
    for now in [0,0.1,0.2]:p.react('wheel_down',now=now)
    p.set_enabled(False,now=1)
    p.set_style('quiet',now=2)
    assert p.tick(idle=False,active_action='freeze',now=5).action=='thaw'


def test_a_cooled_down_tap_does_not_leave_the_rabbit_frozen():
    p=policy()
    p.react('ear_touch',now=0)
    for now in [0.1,0.2,0.3]:p.react('wheel_down',now=now)
    assert p.react('ear_touch',now=0.4) is None
    assert p.tick(idle=False,active_action='freeze',now=5).action=='thaw'


def test_new_human_intention_wins_over_surprise_timer():
    p=policy()
    for now in [0,0.1,0.2]:p.react('wheel_down',now=now)
    assert p.react('feed',now=1).action=='eat'
    assert p.tick(idle=False,active_action='freeze',pending=True,now=10) is None
    assert p.auto_thaw_at is None


def test_separated_wheel_ticks_do_not_accumulate_forever():
    p=policy()
    for now in [0,2,4,6]:
        assert p.react('wheel_down',now=now) is None


def test_repeated_pokes_have_a_small_surprise_not_a_permanent_loop():
    p=policy()
    events=[p.react('pet',now=t) for t in [0,0.55,1.1,1.65]]
    assert events[-1].action=='hit'
    assert p.react('pet',now=1.7) is None


def test_friendly_discoveries_and_cooldowns():
    p=policy()
    assert p.react('ear_touch',now=0).action=='earrub'
    assert p.react('ear_touch',now=0.1) is None
    assert p.react('belly_touch',now=0).action=='hungry'
    assert p.react('shake',now=0).action=='hit_big'
    assert p.react('shake',now=1) is None


def test_double_clicks_offer_more_than_one_finite_action():
    p=policy()
    actions=[p.react('double_click',now=n*2).action for n in range(20)]
    assert actions[0]=='dance'
    assert set(actions)<= {'dance','jump','attack_pillow','dig'}
    assert len(set(actions))>1
