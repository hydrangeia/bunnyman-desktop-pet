"""Pure-Python tests for time-based rabbit interaction policy."""
import random

import pytest

from action_controller import ActionController, _catalog
from interaction_policy import InteractionPolicy


class FakeClock:
    def __init__(self, now=0.0):
        self.now = float(now)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds
        return self.now


def policy(style="lively", *, start=0.0, seed=13):
    clock = FakeClock(start)
    return InteractionPolicy(style, clock=clock, rng=random.Random(seed)), clock


def make_controller():
    clips = {
        step.clip
        for spec in _catalog("idle_loop").values()
        for step in spec.steps + spec.exit_steps
    }
    return ActionController(clips)


@pytest.mark.parametrize(
    ("event", "expected_action"),
    [
        ("pet", "happy"),
        ("double_click", "dance"),
        ("feed", "eat"),
        ("play", "attack_pillow"),
        ("sleep", "sleep"),
        ("wake", "wake"),
    ],
)
def test_user_events_map_to_expected_actions(event, expected_action):
    pet_policy, _ = policy()

    reaction = pet_policy.react(event, now=10)

    assert reaction.action == expected_action
    assert reaction.source == "user"


def test_drop_mapping_is_seeded_and_uses_only_supported_reactions():
    first, _ = policy(seed=31)
    second, _ = policy(seed=31)

    first_reaction = first.react("drop", now=10)
    second_reaction = second.react("drop", now=10)

    assert first_reaction.action in {"happy", "earrub"}
    assert second_reaction.action == first_reaction.action
    assert first_reaction.text == "到啦！"


@pytest.mark.parametrize(
    ("style", "expected_action"), [("lively", "happy"), ("quiet", "earrub")]
)
def test_hover_maps_to_style_reaction(style, expected_action):
    pet_policy, _ = policy(style)

    assert pet_policy.react("hover", now=20).action == expected_action


def test_feed_cooldown_returns_feedback_without_replaying_eat():
    pet_policy, _ = policy()

    first = pet_policy.react("feed", now=100)
    cooling_down = pet_policy.react("feed", now=103.999)
    ready_again = pet_policy.react("feed", now=104)

    assert first.action == "eat"
    assert cooling_down.action is None
    assert cooling_down.text == "慢点，我还在嚼呢。"
    assert ready_again.action == "eat"


def test_pet_and_hover_cooldowns_suppress_repeated_reactions():
    pet_policy, _ = policy()

    assert pet_policy.react("pet", now=0).action == "happy"
    assert pet_policy.react("pet", now=0.69) is None
    assert pet_policy.react("pet", now=0.701).action == "happy"

    assert pet_policy.react("hover", now=20).action == "happy"
    assert pet_policy.react("hover", now=27.99) is None
    assert pet_policy.react("hover", now=28.01).action == "happy"


def test_default_style_is_lively_and_first_auto_interval_is_12_to_24_seconds():
    pet_policy, clock = policy()

    assert pet_policy.style == "lively"
    interval = pet_policy.next_auto_at - clock()
    assert 12 <= interval <= 24


@pytest.mark.parametrize(
    ("style", "minimum", "maximum", "allowed"),
    [
        ("lively", 12, 24, {"earrub", "happy", "dance", "hungry"}),
        ("quiet", 60, 110, {"earrub", "happy"}),
    ],
)
def test_automatic_activity_waits_for_the_selected_style_interval(
    style, minimum, maximum, allowed
):
    pet_policy, clock = policy(style, start=500, seed=5)
    due = pet_policy.next_auto_at

    assert minimum <= due - clock() <= maximum
    assert pet_policy.tick(
        idle=True, active_action="idle", now=due - 0.001
    ) is None
    reaction = pet_policy.tick(idle=True, active_action="idle", now=due)

    assert reaction is not None
    assert reaction.source == "auto"
    assert reaction.action in allowed


@pytest.mark.parametrize(
    "blocker",
    ["busy", "non_idle_action", "pending", "drag_or_menu", "disabled"],
)
def test_automatic_activity_is_suppressed_while_blocked(blocker):
    pet_policy, _ = policy()
    options = {"idle": True, "active_action": "idle", "pending": False, "blocked": False}
    if blocker == "busy":
        options.update(idle=False, active_action="dance")
    elif blocker == "non_idle_action":
        options.update(active_action="dance")
    elif blocker == "pending":
        options.update(pending=True)
    elif blocker == "drag_or_menu":
        options.update(blocked=True)
    else:
        pet_policy.set_enabled(False, now=0)

    assert pet_policy.tick(**options, now=30) is None


def test_elapsed_time_does_not_catch_up_as_a_burst():
    pet_policy, _ = policy()
    late_now = 1_000_000.0
    # A recent human action keeps the nap threshold out of this check while the
    # preexisting schedule is far behind the clock.
    pet_policy.note_user_activity(now=late_now - 30)

    first = pet_policy.tick(idle=True, active_action="idle", now=late_now)
    second = pet_policy.tick(idle=True, active_action="idle", now=late_now)

    assert first is not None and first.source == "auto"
    assert second is None
    assert pet_policy.next_auto_at > late_now


@pytest.mark.parametrize("start", [0.0, 1_000_000.0])
def test_clock_origin_zero_and_large_values_schedule_relative_to_now(start):
    pet_policy, clock = policy(start=start, seed=2)
    due = pet_policy.next_auto_at

    assert 12 <= due - start <= 24
    assert pet_policy.last_user_at == start
    assert pet_policy.tick(
        idle=True, active_action="idle", now=due - 0.01
    ) is None
    assert pet_policy.tick(
        idle=True, active_action="idle", now=due
    ).source == "auto"
    assert clock() == start


def test_auto_nap_after_three_idle_minutes_wakes_after_25_seconds():
    pet_policy, _ = policy()

    nap = pet_policy.tick(idle=True, active_action="idle", now=180)
    assert nap.action == "sleep"
    assert nap.source == "auto"
    assert pet_policy.auto_sleep_started == 180

    assert pet_policy.tick(idle=False, active_action="sleep", now=204.999) is None
    wake = pet_policy.tick(idle=False, active_action="sleep", now=205)
    assert wake.action == "wake"
    assert wake.source == "auto"
    assert pet_policy.last_nap_at == 205


def test_manual_sleep_has_no_automatic_wake_timer():
    pet_policy, _ = policy()

    assert pet_policy.react("sleep", now=5).action == "sleep"
    assert pet_policy.auto_sleep_started is None
    assert pet_policy.tick(
        idle=False, active_action="sleep", now=10_000
    ) is None


def test_user_activity_cancels_automatic_wake_that_could_replace_a_queued_action():
    pet_policy, _ = policy()
    assert pet_policy.tick(idle=True, active_action="idle", now=180).action == "sleep"

    queued = pet_policy.react("play", now=181)

    assert queued.action == "attack_pillow"
    assert pet_policy.auto_sleep_started is None
    assert pet_policy.tick(
        idle=False, active_action="sleep", pending=True, now=220
    ) is None


def test_repeated_auto_nap_waits_until_25_seconds_nap_plus_180_seconds_spacing():
    pet_policy, _ = policy()
    assert pet_policy.tick(idle=True, active_action="idle", now=180).action == "sleep"
    assert pet_policy.tick(idle=False, active_action="sleep", now=205).action == "wake"

    before_spacing = pet_policy.tick(
        idle=True, active_action="idle", now=384.999
    )
    assert before_spacing is None or before_spacing.action != "sleep"
    assert pet_policy.tick(
        idle=True, active_action="idle", now=385
    ).action == "sleep"


def test_style_and_enabled_changes_restart_the_schedule():
    pet_policy, _ = policy()

    pet_policy.set_style("quiet", now=50)
    quiet_due = pet_policy.next_auto_at
    assert pet_policy.last_user_at == 50
    assert 60 <= quiet_due - 50 <= 110

    pet_policy.set_enabled(False, now=100)
    disabled_due = pet_policy.next_auto_at
    assert pet_policy.enabled is False
    assert pet_policy.last_user_at == 100
    assert 60 <= disabled_due - 100 <= 110
    assert pet_policy.tick(idle=True, active_action="idle", now=1_000) is None

    pet_policy.set_enabled(True, now=200)
    enabled_due = pet_policy.next_auto_at
    assert pet_policy.enabled is True
    assert pet_policy.last_user_at == 200
    assert 60 <= enabled_due - 200 <= 110
    assert pet_policy.tick(
        idle=True, active_action="idle", now=enabled_due - 0.001
    ) is None


def test_automatic_wake_flows_through_sleep_posture_in_action_controller():
    pet_policy, _ = policy()
    actions = make_controller()

    nap = pet_policy.tick(idle=True, active_action=actions.active_action, now=180)
    assert nap.action == "sleep"
    assert actions.request(nap.action).clip == "sleep_pre"
    assert actions.finish_clip().clip == "sleep_loop"

    wake = pet_policy.tick(
        idle=False, active_action=actions.active_action, now=205
    )
    assert wake.action == "wake"
    assert actions.request(wake.action) is None
    assert actions.finish_clip().clip == "sleep_pst"
    assert actions.finish_clip().clip == "idle_loop"


def test_feed_requested_during_sleep_waits_for_wake_before_eating():
    pet_policy, _ = policy()
    actions = make_controller()
    assert actions.request(pet_policy.react("sleep", now=0).action).clip == "sleep_pre"
    assert actions.finish_clip().clip == "sleep_loop"

    feed = pet_policy.react("feed", now=1)
    assert feed.action == "eat"
    assert actions.request(feed.action) is None
    assert actions.finish_clip().clip == "sleep_pst"
    assert actions.finish_clip().clip == "eat"


def test_drop_then_double_click_keep_latest_target_after_waking():
    pet_policy, _ = policy(seed=17)
    actions = make_controller()
    actions.request("sleep")
    actions.finish_clip()  # sleep_loop

    dropped = pet_policy.react("drop", now=1)
    double_click = pet_policy.react("double_click", now=2)
    assert dropped.action in {"happy", "earrub"}
    assert double_click.action == "dance"
    assert actions.request(dropped.action) is None
    assert actions.request(double_click.action) is None

    assert actions.finish_clip().clip == "sleep_pst"
    assert actions.finish_clip().clip == "dance"
    assert actions.active_action == "dance"
