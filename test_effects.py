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


def test_feeding_setup_lowers_hand_pillow_and_keeps_cozy_body_pillow():
    symbol = lambda color: (Image.new("RGBA", (4, 4), color), 0, 0)
    body_pad = symbol((180, 220, 100, 255))
    hand_pillow = symbol((160, 180, 80, 255))
    base = {(exporter.symbol_hash("body"), 0): symbol((220, 180, 150, 255))}
    equipment = {
        "hat_nightcap": {(exporter.symbol_hash("hat"), 0): symbol((200, 160, 40, 255))},
        "swap_pillows_petals": {
            (exporter.symbol_hash("swap_object"), 0): hand_pillow,
            (exporter.symbol_hash("swap_body_rabbit"), 0): body_pad,
        },
        "frozen": {},
    }

    symbols, hidden = exporter.symbol_setup(
        "cozy_pillow", "eat", base, equipment, lower_pillow=True,
    )
    old_symbols, old_hidden = exporter.symbol_setup(
        "cozy_pillow", "idle_loop", base, equipment,
    )

    assert (exporter.symbol_hash("swap_object"), 0) not in symbols
    assert exporter.symbol_hash("ARM_carry") in hidden
    assert exporter.symbol_hash("ARM_normal") not in hidden
    assert symbols[exporter.symbol_hash("belt"), 0] == body_pad
    assert (exporter.symbol_hash("hat"), 0) in symbols
    assert (exporter.symbol_hash("swap_object"), 0) in old_symbols
    assert exporter.symbol_hash("ARM_carry") not in old_hidden


def test_eat_prop_disappears_at_native_four_frame_consume_event():
    size = (620, 616)
    bodies = []
    for index in range(8):
        bodies.append(Image.new("RGBA", size, (20 + index, 70, 110, 255)))
    carrot = Image.new("RGBA", size)
    carrot.paste((230, 90, 24, 255), (500, 500, 516, 530))

    frames = exporter._eat_carrot_frames(bodies, carrot)

    assert len(frames) == len(bodies)
    assert all(frames[index].getpixel((505, 505)) == (230, 90, 24, 255)
               for index in range(exporter.EAT_CONSUMPTION_FRAME))
    for index in range(exporter.EAT_CONSUMPTION_FRAME, len(bodies)):
        assert frames[index].tobytes() == bodies[index].tobytes()
    assert bodies[0].getpixel((505, 505)) == (20, 70, 110, 255)


def test_spin_sequence_uses_native_pre_loop_post_order_and_stopped_hold():
    pre = ["pre-0", "pre-1"]
    loop = ["loop-0", "loop-1"]
    post = ["post-0", "post-final"]

    sequence = exporter._carrot_spin_sequence(
        pre, loop, post, loop_cycles=2, hold_frames=3,
    )

    assert sequence == [
        "pre-0", "pre-1", "loop-0", "loop-1", "loop-0", "loop-1",
        "post-0", "post-final", "post-final", "post-final", "post-final",
    ]


def test_idle_and_spun_eat_overlays_both_end_at_the_same_raw_body():
    size = (620, 616)
    body = [Image.new("RGBA", size, (30 + index, 70, 110, 255))
            for index in range(6)]
    idle_carrot = Image.new("RGBA", size)
    idle_carrot.putpixel((500, 500), (230, 90, 24, 255))
    spun_carrot = Image.new("RGBA", size)
    spun_carrot.putpixel((500, 500), (24, 90, 230, 255))

    idle_eat = exporter._eat_carrot_frames(body, idle_carrot)
    spun_eat = exporter._eat_carrot_frames(body, spun_carrot)

    assert idle_eat[0].getpixel((500, 500)) == (230, 90, 24, 255)
    assert spun_eat[0].getpixel((500, 500)) == (24, 90, 230, 255)
    assert idle_eat[4].tobytes() == spun_eat[4].tobytes() == body[4].tobytes()


def test_prop_composite_keeps_actor_frames_paired_on_the_same_canvas():
    size = (620, 616)
    bodies = []
    props = []
    for index in range(4):
        body = Image.new("RGBA", size)
        body.putpixel((10, 10), (index + 1, 0, 0, 255))
        prop = Image.new("RGBA", size)
        prop.putpixel((500, 400), (0, index + 1, 0, 255))
        bodies.append(body)
        props.append(prop)

    frames = exporter._compose_prop_sequence(bodies, props)

    assert len(frames) == 4
    for index, frame in enumerate(frames):
        assert frame.size == size
        assert frame.getpixel((10, 10)) == (index + 1, 0, 0, 255)
        assert frame.getpixel((500, 400)) == (0, index + 1, 0, 255)


def test_ground_prop_scale_keeps_its_actor_relative_pivot_fixed():
    actor_scale = 0.68
    prop_scale = actor_scale * exporter.CARROT_PROP_SCALE
    actor_origin = (400 / actor_scale, 396 / actor_scale)

    prop_origin = exporter._ground_prop_origin(actor_origin, actor_scale)
    screen_anchor = (prop_origin[0] * prop_scale, prop_origin[1] * prop_scale)
    expected_anchor = (
        400 + exporter.CARROT_GROUND_OFFSET[0] * actor_scale,
        396 + exporter.CARROT_GROUND_OFFSET[1] * actor_scale,
    )

    assert all(abs(actual - expected) < 1e-9
               for actual, expected in zip(screen_anchor, expected_anchor))


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
