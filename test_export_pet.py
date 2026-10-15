"""Regression tests for the DST bunnyman frame exporter, using synthetic symbols."""
import numpy as np
import pytest
from PIL import Image

import export_pet as exporter


def h(name):
    return exporter.symbol_hash(name)


def symbol(color, size=(4, 4)):
    image = Image.new("RGBA", size, color)
    return image, 0, 0


def equipment_fixture():
    hat = {(h("hat"), 0): symbol((220, 180, 40, 255))}
    pillow = {
        (h("swap_object"), 0): symbol((40, 80, 220, 255)),
        (h("swap_body_rabbit"), 0): symbol((40, 180, 220, 255)),
    }
    frozen = {(h("frozen"), 0): symbol((100, 180, 240, 180))}
    return {
        "hat_nightcap": hat,
        "swap_pillows_petals": pillow,
        "frozen": frozen,
    }


@pytest.mark.parametrize(
    ("skin", "expected_visible_ear", "expected_hidden_ear"),
    [
        ("normal", "HAIR", "HAIR_HAT"),
        ("cozy", "HAIR_HAT", "HAIR"),
        ("cozy_pillow", "HAIR_HAT", "HAIR"),
    ],
)
def test_skin_setup_selects_one_ear_pose_and_the_right_hat(
    skin, expected_visible_ear, expected_hidden_ear
):
    base = {(h("body"), 0): symbol((180, 120, 80, 255))}
    symbols, hidden = exporter.symbol_setup(skin, "idle_loop", base, equipment_fixture())

    # The game uses HAIR for the bare look and HAIR_HAT for the nightcap look.
    assert h(expected_visible_ear) not in hidden
    assert h(expected_hidden_ear) in hidden
    assert sum(layer not in hidden for layer in (h("HAIR"), h("HAIR_HAT"))) == 1
    assert h("HAIR_NOHAT") not in hidden if skin == "normal" else h("HAIR_NOHAT") in hidden

    if skin == "normal":
        assert h("hat") in hidden
        assert (h("hat"), 0) not in symbols
    else:
        assert h("hat") not in hidden
        assert (h("hat"), 0) in symbols


def test_setup_uses_the_carry_arm_only_for_carrying_and_adds_pillow_swaps():
    base = {(h("body"), 0): symbol((180, 120, 80, 255))}
    equipment = equipment_fixture()

    normal_idle, normal_idle_hidden = exporter.symbol_setup(
        "normal", "idle_loop", base, equipment
    )
    normal_carry, normal_carry_hidden = exporter.symbol_setup(
        "normal", "idle_loop_overhead", base, equipment
    )
    cozy_pillow, cozy_pillow_hidden = exporter.symbol_setup(
        "cozy_pillow", "idle_loop", base, equipment
    )

    assert h("ARM_carry") in normal_idle_hidden
    assert h("ARM_normal") not in normal_idle_hidden
    assert h("ARM_carry") not in normal_carry_hidden
    assert h("ARM_normal") in normal_carry_hidden
    assert (h("swap_object"), 0) not in normal_idle
    assert (h("swap_object"), 0) in normal_carry
    assert (h("swap_object"), 0) in cozy_pillow
    assert (h("belt"), 0) in cozy_pillow
    assert h("ARM_carry") not in cozy_pillow_hidden
    assert h("ARM_normal") in cozy_pillow_hidden


def test_symbol_setup_does_not_mutate_the_shared_base_dictionary():
    body = symbol((180, 120, 80, 255))
    base = {(h("body"), 0): body}
    before = dict(base)

    cozy, _ = exporter.symbol_setup("cozy", "idle_loop", base, equipment_fixture())
    pillow, _ = exporter.symbol_setup(
        "cozy_pillow", "atk_object", base, equipment_fixture()
    )

    assert base == before
    assert (h("hat"), 0) in cozy and (h("hat"), 0) not in base
    assert (h("swap_object"), 0) in pillow and (h("swap_object"), 0) not in base


def element(key, *, layer="body", a=1, b=0, c=0, d=1, tx=0, ty=0, z=0):
    return (h(key), 0, h(layer), a, b, c, d, tx, ty, z)


def test_render_frame_draws_lower_z_element_over_higher_z_element():
    red = Image.new("RGBA", (5, 5), (240, 20, 30, 255))
    blue = Image.new("RGBA", (5, 5), (20, 30, 240, 255))
    symbols = {(h("red"), 0): (red, 0, 0), (h("blue"), 0): (blue, 0, 0)}
    frame = {"elements": [
        element("red", tx=2, ty=2, z=1),
        element("blue", tx=2, ty=2, z=9),
    ]}

    rendered = exporter.render_frame(frame, symbols, (10, 10), (0, 0))

    assert rendered.getpixel((4, 4)) == (240, 20, 30, 255)


def full_canvas_reference(frame, symbols, canvas, origin, scale):
    """Slow reference: transform each symbol over the entire canvas."""
    result = Image.new("RGBA", canvas)
    for item in sorted(frame["elements"], key=lambda e: e[-1], reverse=True):
        key, index, _layer, a, b, c, d, tx, ty, _z = item
        image, left, top = symbols[key, index]
        forward = np.array([
            [a, c, tx + origin[0] + a * left + c * top],
            [b, d, ty + origin[1] + b * left + d * top],
            [0, 0, 1],
        ], dtype=float)
        forward[:2] *= scale
        inverse = np.linalg.inv(forward)
        whole_canvas = image.transform(
            canvas,
            Image.Transform.AFFINE,
            tuple(inverse[:2].ravel()),
            Image.Resampling.BICUBIC,
        )
        result.alpha_composite(whole_canvas)
    return result


def test_local_bbox_render_matches_full_canvas_for_mirror_translation_and_scale():
    # Asymmetric translucent pixels make reflection, translation, and resampling
    # errors visible; the nonzero pivot checks the symbol origin as well.
    image = Image.new("RGBA", (9, 7), (0, 0, 0, 0))
    for y in range(1, 6):
        for x in range(2, 8):
            image.putpixel((x, y), (20 * x, 25 * y, 90, 160 + 10 * (x % 2)))
    symbols = {(h("glyph"), 0): (image, 3, -4)}
    frame = {"elements": [element(
        "glyph", a=-1.0, b=0.25, c=0.15, d=1.1, tx=17.0, ty=15.0, z=0
    )]}
    canvas = (48, 40)
    origin = (8, 6)
    scale = 0.7

    optimized = exporter.render_frame(frame, symbols, canvas, origin, scale=scale)
    reference = full_canvas_reference(frame, symbols, canvas, origin, scale)

    np.testing.assert_allclose(np.asarray(optimized), np.asarray(reference), atol=1)


@pytest.mark.parametrize("renderer", ["render_frame", "visible_bounds"])
def test_missing_optional_swap_slot_is_skipped(renderer):
    frame = {"elements": [element("swap_object", layer="ARM_carry")]}

    if renderer == "render_frame":
        result = exporter.render_frame(frame, {}, (12, 12), (0, 0))
        assert result.getbbox() is None
    else:
        assert exporter.visible_bounds(frame, {}, set()) == []


@pytest.mark.parametrize("renderer", ["render_frame", "visible_bounds"])
def test_missing_required_symbol_raises(renderer):
    frame = {"elements": [element("required_body")]}

    with pytest.raises(KeyError, match="Missing"):
        if renderer == "render_frame":
            exporter.render_frame(frame, {}, (12, 12), (0, 0))
        else:
            exporter.visible_bounds(frame, {}, set())
