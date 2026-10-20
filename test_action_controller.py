"""Synthetic regression tests for complete bunnyman action transitions."""
import pytest

from action_controller import ActionController


AVAILABLE = set("""
    idle_loop idle_happy idle_earrub idle_angry idle_creepy dance eat hungry
    disgust pig_pickup pig_take pig_reject sleep_pre sleep_loop sleep_pst
    alert_pre alert_loop alert_pst frozen frozen_loop_pst shock_loop shock_pst
    walk_pre walk_loop walk_pst run_pre run_loop run_pst
    boat_jump_pre boat_jump boat_jump_loop boat_jump_pst
    despawn spawn_pre spawn_loop spawn_pst abandon atk
    atk_object_pre idle_loop_overhead atk_object
    walk_overhead_pre walk_overhead_loop walk_overhead_pst
    hit hit_big death corpse
""".split())


def controller(initial_clip=None):
    return ActionController(AVAILABLE, initial_clip=initial_clip)


def trace_until_action(pet, action, trace, limit=32):
    """Advance only at clip boundaries and fail if a request cannot settle."""
    first_clip = pet.actions[action].steps[0].clip
    for _ in range(limit):
        if pet.active_action == action and pet.current.clip == first_clip:
            return trace
        trace.append(pet.finish_clip().clip)
    pytest.fail(f"{action!r} was not reached within {limit} clip boundaries: {trace}")


def test_sleep_returns_through_wake_before_idle():
    pet = controller()
    assert pet.request("sleep").clip == "sleep_pre"
    assert pet.finish_clip().clip == "sleep_loop"
    assert pet.request("idle") is None
    assert pet.finish_clip().clip == "sleep_pst"
    assert pet.finish_clip().clip == "idle_loop"
    assert pet.active_action == "idle"


def test_raw_sleep_loop_request_cannot_skip_wake_clip():
    pet = controller(initial_clip="sleep_loop")
    assert pet.active_action == "sleep"
    assert pet.request("idle") is None

    assert pet.finish_clip().clip == "sleep_pst"
    assert pet.finish_clip().clip == "idle_loop"


def test_clicking_happy_during_sleep_entry_still_plays_wake():
    pet = controller()
    pet.request("sleep")
    assert pet.current.clip == "sleep_pre"
    pet.request("happy")

    trace = trace_until_action(pet, "happy", [pet.current.clip])

    assert "sleep_pst" in trace
    assert trace.index("sleep_pst") < trace.index("idle_happy")


def test_requests_during_wake_replace_destination_without_restarting_wake():
    pet = controller()
    pet.request("sleep")
    pet.finish_clip()  # sleep_loop
    pet.request("happy")
    assert pet.finish_clip().clip == "sleep_pst"

    assert pet.request("dance") is None
    assert pet.current.clip == "sleep_pst"
    assert pet.request("happy") is None  # latest destination wins
    assert pet.current.clip == "sleep_pst"
    assert pet.finish_clip().clip == "idle_happy"
    assert pet.active_action == "happy"


def test_dig_finishes_emergence_before_the_requested_action():
    pet = controller()
    assert pet.request("dig").clip == "despawn"
    pet.request("dance")

    trace = trace_until_action(pet, "dance", [pet.current.clip])

    assert trace[:4] == ["despawn", "spawn_pre", "spawn_loop", "spawn_pst"]
    assert trace[4] == "dance"


@pytest.mark.parametrize(
    ("initial_clip", "destination", "expected_recovery"),
    [
        ("despawn", "idle", ["spawn_pre", "spawn_loop", "spawn_pst"]),
        ("spawn_loop", "dance", ["spawn_pst"]),
    ],
)
def test_raw_dig_clips_finish_emergence_before_leaving(
    initial_clip, destination, expected_recovery
):
    pet = controller(initial_clip=initial_clip)
    assert pet.request(destination) is None
    trace = [pet.current.clip]

    trace_until_action(pet, destination, trace)

    start = trace.index(expected_recovery[0])
    assert trace[start : start + len(expected_recovery)] == expected_recovery
    assert trace[-1] == pet.actions[destination].steps[0].clip


@pytest.mark.parametrize(
    ("action", "entry_clip", "exit_clip"),
    [("walk", "walk_pre", "walk_pst"), ("run", "run_pre", "run_pst")],
)
def test_walk_and_run_leave_through_their_stop_clip(action, entry_clip, exit_clip):
    pet = controller()
    assert pet.request(action).clip == entry_clip
    pet.request("dance")

    trace = trace_until_action(pet, "dance", [pet.current.clip])

    assert exit_clip in trace
    assert trace.index(exit_clip) < trace.index("dance")


def test_jump_finishes_landing_before_switching_to_a_new_action():
    pet = controller()
    assert pet.request("jump").clip == "boat_jump_pre"
    assert pet.finish_clip().clip == "boat_jump"
    assert pet.finish_clip().clip == "boat_jump_loop"
    pet.request("dance")

    trace = trace_until_action(pet, "dance", [pet.current.clip])

    assert trace[-2:] == ["boat_jump_pst", "dance"]


def test_freeze_request_runs_thaw_before_new_action():
    pet = controller()
    assert pet.request("freeze").clip == "frozen"
    thaw = pet.request("dance")
    assert thaw is not None and thaw.clip == "frozen_loop_pst"

    trace = trace_until_action(pet, "dance", ["frozen", thaw.clip])

    assert trace[-2:] == ["frozen_loop_pst", "dance"]


def test_standing_up_from_corpse_runs_full_emergence_sequence():
    pet = controller()
    assert pet.request("death").clip == "death"
    assert pet.finish_clip().clip == "corpse"
    first = pet.request("idle")
    assert first is not None and first.clip == "spawn_pre"

    trace = trace_until_action(pet, "idle", ["death", "corpse", first.clip])

    assert trace[-4:] == ["spawn_pre", "spawn_loop", "spawn_pst", "idle_loop"]


def test_once_action_finishes_and_requesting_same_action_does_not_restart_it():
    pet = controller()
    assert pet.request("happy").clip == "idle_happy"
    current = pet.current
    assert pet.request("happy") is None
    assert pet.current is current
    assert pet.pending_action is None

    pet.request("dance")
    assert pet.current is current  # request queues; the current once clip completes
    assert pet.finish_clip().clip == "dance"
    assert pet.active_action == "dance"


def test_latest_pending_target_wins_after_a_finite_once_action():
    pet = controller()
    pet.request("happy")
    pet.request("dance")
    pet.request("earrub")

    assert pet.finish_clip().clip == "idle_earrub"
    assert pet.active_action == "earrub"


CARROT_CLIPS = {
    "carrot_offer", "carrot_place", "carrot_spin", "eat_carrot", "eat_carrot_spun"
}


def test_new_feed_actions_use_the_finite_carrot_sequences():
    pet = ActionController(AVAILABLE | CARROT_CLIPS)

    assert [step.clip for step in pet.actions["eat"].steps] == [
        "carrot_offer", "eat_carrot"
    ]
    assert [step.clip for step in pet.actions["spin_carrot"].steps] == [
        "carrot_offer", "carrot_place", "carrot_spin", "eat_carrot_spun", "idle_happy"
    ]
    assert all(step.mode == "once" for step in pet.actions["spin_carrot"].steps)


@pytest.mark.parametrize(
    ("queued_action", "expected_start"),
    [("eat", "carrot_offer"), ("sleep", "sleep_pre"), ("dance", "dance")],
)
def test_queued_feed_sleep_or_manual_action_waits_for_the_whole_carrot_spin(
    queued_action, expected_start
):
    pet = ActionController(AVAILABLE | CARROT_CLIPS)
    assert pet.request("spin_carrot").clip == "carrot_offer"
    pet.request(queued_action)

    completed = [pet.finish_clip().clip for _ in range(5)]

    assert completed == [
        "carrot_place", "carrot_spin", "eat_carrot_spun", "idle_happy", expected_start
    ]
    assert pet.active_action == queued_action


def test_queued_direct_feed_finishes_sleep_and_both_feed_clips():
    pet = ActionController(AVAILABLE | CARROT_CLIPS)
    pet.request("sleep")
    assert pet.finish_clip().clip == "sleep_loop"
    assert pet.request("eat") is None

    assert pet.finish_clip().clip == "sleep_pst"
    assert pet.finish_clip().clip == "carrot_offer"
    assert pet.finish_clip().clip == "eat_carrot"
    assert pet.finish_clip().clip == "idle_loop"
    assert pet.active_action == "idle"


def test_latest_queued_intent_wins_after_the_carrot_spin_finishes():
    pet = ActionController(AVAILABLE | CARROT_CLIPS)
    pet.request("spin_carrot")
    pet.request("sleep")
    pet.request("dance")

    trace = [pet.current.clip]
    for _ in range(5):
        trace.append(pet.finish_clip().clip)

    assert trace == [
        "carrot_offer", "carrot_place", "carrot_spin", "eat_carrot_spun", "idle_happy", "dance"
    ]
    assert pet.active_action == "dance"


@pytest.mark.parametrize(
    ("clips", "expected_clip"),
    [(AVAILABLE, "eat"), (AVAILABLE | {"eat_carrot"}, "eat_carrot")],
)
def test_legacy_manifests_keep_their_feed_action_and_hide_carrot_spin(clips, expected_clip):
    pet = ActionController(clips)

    assert "spin_carrot" not in pet.actions
    assert pet.request("eat_carrot").clip == expected_clip


# Exercise a request at every step boundary in the controller's multi-stage
# physical actions. A step represents a complete animation clip; frame playback
# lives in the UI and is intentionally absent from these synthetic tests.
BOUNDARY_PATHS = {
    "sleep": (("sleep_pre", "sleep_loop"), ("sleep_pst",)),
    "dig": (("despawn", "spawn_pre", "spawn_loop", "spawn_pst"),
            ("spawn_pre", "spawn_loop", "spawn_pst")),
    "walk": (("walk_pre", "walk_loop"), ("walk_pst",)),
    "run": (("run_pre", "run_loop"), ("run_pst",)),
    "jump": (("boat_jump_pre", "boat_jump", "boat_jump_loop", "boat_jump_pst"),
             ("boat_jump_pst",)),
    "freeze": (("frozen",), ("frozen_loop_pst",)),
    "death": (("death", "corpse"), ("spawn_pre", "spawn_loop", "spawn_pst")),
    "alert": (("alert_pre", "alert_loop"), ("alert_pst",)),
    "shock": (("shock_loop",), ("shock_pst",)),
    "hold_pillow": (("atk_object_pre", "idle_loop_overhead"), ("atk_object",)),
    "walk_pillow": (("atk_object_pre", "walk_overhead_pre", "walk_overhead_loop"),
                    ("walk_overhead_pst", "atk_object")),
}
BOUNDARY_CASES = [
    (action, clips, recovery, index)
    for action, (clips, recovery) in BOUNDARY_PATHS.items()
    for index in range(len(clips))
]


@pytest.mark.parametrize(
    ("action", "clips", "recovery", "boundary_index"),
    BOUNDARY_CASES,
    ids=[f"{action}-{clips[index]}" for action, clips, _recovery, index in BOUNDARY_CASES],
)
def test_each_multistage_clip_boundary_can_reach_latest_target(
    action, clips, recovery, boundary_index
):
    pet = controller()
    first = pet.request(action)
    assert first is not None and first.clip == clips[0]
    trace = [first.clip]

    for expected_clip in clips[1 : boundary_index + 1]:
        step = pet.finish_clip()
        trace.append(step.clip)
        assert step.clip == expected_clip

    target = "happy" if action == "dance" else "dance"
    returned = pet.request(target)
    if returned is not None and returned.clip != trace[-1]:
        trace.append(returned.clip)
    trace_until_action(pet, target, trace)

    target_clip = pet.actions[target].steps[0].clip
    target_index = trace.index(target_clip)
    for clip in recovery:
        assert clip in trace[:target_index], (
            f"{action} at {clips[boundary_index]} reached {target} before {clip}: {trace}"
        )
    assert pet.pending_action is None


FINITE_ACTIONS = (
    "happy", "earrub", "dance", "eat", "hungry", "angry", "creepy",
    "disgust", "pickup", "take", "reject", "jump", "dig", "abandon",
    "attack", "hit", "hit_big",
)


@pytest.mark.parametrize("action", FINITE_ACTIONS)
def test_finite_actions_return_to_idle_without_a_request(action):
    pet = controller()
    pet.request(action)
    trace = [pet.current.clip]

    trace_until_action(pet, "idle", trace)

    assert trace[-1] == "idle_loop"
    assert pet.pending_action is None
