"""Synthetic checks for feeding overlays and pillow release choreography."""
from PIL import Image

from action_controller import ActionController
import export_pet as exporter


LEGACY_CLIPS = set("""
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

NEW_CLIPS = LEGACY_CLIPS | {
    "eat_carrot", "pillow_putdown", "pillow_attack_release",
}


def controller(clips=NEW_CLIPS, initial_clip=None):
    return ActionController(clips, initial_clip=initial_clip)


def advance_until(pet, target, limit=12):
    trace = [pet.current.clip]
    for _ in range(limit):
        if pet.active_action == target and pet.current.clip == pet.actions[target].steps[0].clip:
            return trace
        trace.append(pet.finish_clip().clip)
    raise AssertionError(f"{target} did not start: {trace}")


def test_feed_action_prefers_composited_carrot_clip_and_keeps_legacy_fallback():
    modern = controller()
    assert modern.request("eat").clip == "eat_carrot"

    legacy = controller(LEGACY_CLIPS)
    assert legacy.request("eat").clip == "eat"


def test_holding_pillow_leaves_through_putdown_clip():
    pet = controller()
    assert pet.request("hold_pillow").clip == "atk_object_pre"
    assert pet.finish_clip().clip == "idle_loop_overhead"
    assert pet.request("idle") is None
    assert pet.finish_clip().clip == "pillow_putdown"
    assert pet.finish_clip().clip == "idle_loop"


def test_walk_with_pillow_stops_then_lowers_it_before_switching():
    pet = controller()
    assert pet.request("walk_pillow").clip == "atk_object_pre"
    assert pet.finish_clip().clip == "walk_overhead_pre"
    assert pet.finish_clip().clip == "walk_overhead_loop"
    pet.request("dance")
    assert pet.finish_clip().clip == "walk_overhead_pst"
    assert pet.finish_clip().clip == "pillow_putdown"
    assert pet.finish_clip().clip == "dance"


def test_attack_pillow_uses_attack_pose_release_after_striking():
    pet = controller()
    assert pet.request("attack_pillow").clip == "atk_object_pre"
    assert pet.finish_clip().clip == "idle_loop_overhead"
    assert pet.finish_clip().clip == "atk_object"
    assert pet.finish_clip().clip == "pillow_attack_release"
    assert pet.finish_clip().clip == "idle_loop"


def test_interrupting_pillow_attack_finishes_with_its_smooth_release():
    pet = controller()
    assert pet.request("attack_pillow").clip == "atk_object_pre"
    pet.request("dance")
    assert pet.finish_clip().clip == "idle_loop_overhead"
    assert pet.finish_clip().clip == "atk_object"
    assert pet.finish_clip().clip == "pillow_attack_release"
    assert pet.finish_clip().clip == "dance"


def test_putdown_symbol_setup_keeps_the_real_pillow_and_carry_arm():
    symbol = lambda color: (Image.new("RGBA", (4, 4), color), 0, 0)
    base = {(exporter.symbol_hash("body"), 0): symbol((220, 180, 150, 255))}
    equipment = {
        "hat_nightcap": {(exporter.symbol_hash("hat"), 0): symbol((200, 160, 40, 255))},
        "swap_pillows_petals": {
            (exporter.symbol_hash("swap_object"), 0): symbol((180, 220, 100, 255)),
            (exporter.symbol_hash("swap_body_rabbit"), 0): symbol((180, 220, 100, 255)),
        },
        "frozen": {},
    }

    for skin in ("normal", "cozy", "cozy_pillow"):
        symbols, hidden = exporter.symbol_setup(skin, "pillow_putdown", base, equipment)
        assert (exporter.symbol_hash("swap_object"), 0) in symbols
        assert exporter.symbol_hash("ARM_carry") not in hidden
        assert exporter.symbol_hash("ARM_normal") in hidden


def test_eat_overlay_holds_visible_carrot_then_shrinks_it_away():
    carrot = Image.new("RGBA", (16, 30), (230, 90, 24, 255))
    origin = (300, 400)
    indices = (0, 4, 8, 16, 24, 28, 34, 39, 40)
    frames = []
    for index in indices:
        body = Image.new("RGBA", (620, 616))
        frames.append(exporter._eat_carrot_frame(body, carrot, index, 48, origin))

    alpha_sums = [sum(frame.getchannel("A").getdata()) for frame in frames]
    # It remains full-size through frame 28, so frames 0/8/16/24 are easy to see.
    assert [alpha_sums[indices.index(i)] for i in (0, 8, 16, 24, 28)] == [480 * 255] * 5
    assert exporter.EAT_CARROT_SCALE == 0.68
    assert frames[0].getbbox()[1] > frames[1].getbbox()[1]  # hand moves up toward mouth
    assert frames[2].getbbox() == frames[3].getbbox() == frames[4].getbbox()
    assert alpha_sums[5] > alpha_sums[6] > alpha_sums[7] > alpha_sums[8]
    assert frames[-1].getbbox() is None


def test_pillow_attack_release_blends_all_the_way_to_standing():
    held = Image.new("RGBA", (8, 8), (250, 240, 20, 255))
    idle = Image.new("RGBA", (8, 8), (20, 80, 230, 255))
    frames = exporter._blend_to_idle(held, idle)

    assert len(frames) == 8
    assert frames[0].getpixel((0, 0)) == (250, 240, 20, 255)
    assert frames[-1].getpixel((0, 0)) == (20, 80, 230, 255)
    assert frames[1].getpixel((0, 0)) != frames[2].getpixel((0, 0))


def test_effect_clip_holds_last_built_symbol_for_missing_tail_cells():
    key = exporter.symbol_hash("spark")
    red = (Image.new("RGBA", (2, 2), (255, 0, 0, 255)), 0, 0)
    blue = (Image.new("RGBA", (2, 2), (0, 0, 255, 255)), 0, 0)
    clip = {"frames": [{"elements": [(key, 0), (key, 2), (key, 3)]}]}

    symbols = exporter.complete_animation_symbols({(key, 0): red, (key, 2): blue}, [clip])

    assert symbols[key, 0] == red
    assert symbols[key, 1] == red
    assert symbols[key, 2] == blue
    assert symbols[key, 3] == blue
