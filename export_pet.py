"""Render a small selection of local DST bunnyman animations to RGBA frames.

Binary layouts checked against CN-DST-DEVELOPER/DstAnimTool and
nsimplex/ktools. Assets are read from the user's installed game.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import struct
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent


def symbol_hash(name):
    value = 0
    for character in name.lower():
        value = (ord(character) + 65599 * value) & 0xffffffff
    return value


OPTIONAL_SLOTS = {symbol_hash(name) for name in ['swap_hat', 'swap_object', 'swap_frozen', 'Belt']}
# prefabs/bunnyman.lua:372-374 hides these layers on an ordinary bunnyman.
# HAIR_HAT contains the alternate ear pose for hats, ARM_carry the carrying arm.
HIDDEN_LAYERS = {symbol_hash(name) for name in ['hat', 'ARM_carry', 'HAIR_HAT']}


class Reader:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def read(self, fmt):
        fmt = '<' + fmt
        values = struct.unpack(fmt, self.stream.read(struct.calcsize(fmt)))
        return values[0] if len(values) == 1 else values

    def string(self):
        return self.stream.read(self.read('I')).decode('utf-8')

    def names(self):
        result = {}
        for _ in range(self.read('I')):
            key = self.read('I')
            result[key] = self.string()
        return result


def parse_anim(data):
    r = Reader(data)
    assert r.stream.read(4) == b'ANIM' and r.read('I') == 4
    _, _, _, count = r.read('4I')
    animations = []
    for _ in range(count):
        name = r.string()
        facing = r.read('B')
        bank, fps, count_frames = r.read('IfI')
        frames = []
        for _ in range(count_frames):
            bounds = r.read('4f')
            for _ in range(r.read('I')):
                r.read('I')
            elements = [r.read('3I7f') for _ in range(r.read('I'))]
            frames.append({'bounds': bounds, 'elements': elements})
        animations.append({'name': name, 'facing': facing, 'bank': bank,
                           'fps': fps, 'frames': frames})
    names = r.names()
    assert r.stream.tell() == len(data)
    return animations, names


def decode_tex(data):
    r = Reader(data)
    assert r.stream.read(4) == b'KTEX'
    header = r.read('I')
    compression = (header >> 4) & 31
    mip_count = (header >> 13) & 31
    metas = [r.read('3HI') for _ in range(mip_count)]
    width, height, _, size = metas[0]
    payload = r.stream.read(size)
    if compression in (0, 1, 2):
        image = Image.frombytes('RGBA', (width, height), payload, 'bcn',
                                {0: 1, 1: 2, 2: 3}[compression])
    elif compression in (4, 5):
        image = Image.frombytes('RGB' if compression == 4 else 'RGBA',
                                (width, height), payload).convert('RGBA')
    else:
        raise ValueError(f'Unsupported KTEX compression {compression}')
    # Klei stores premultiplied colors; PNG/Qt expects straight alpha.
    pixels = np.array(image).astype(np.float32)
    alpha = pixels[..., 3:4]
    pixels[..., :3] = np.minimum(255, pixels[..., :3] * 255 / np.maximum(alpha, 1))
    return Image.fromarray(pixels.astype(np.uint8)).transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def parse_build(z):
    data = z.read('build.bin')
    r = Reader(data)
    assert r.stream.read(4) == b'BILD' and r.read('I') == 6
    count_symbols, _ = r.read('2I')
    name = r.string()
    atlas_names = [r.string() for _ in range(r.read('I'))]
    symbols = {}
    for _ in range(count_symbols):
        key, count = r.read('2I')
        symbols[key] = [r.read('2I4f2I') for _ in range(count)]
    vertices = [r.read('6f') for _ in range(r.read('I'))]
    names = r.names()
    assert r.stream.tell() == len(data)
    atlases = [decode_tex(z.read(n)) for n in atlas_names]
    return {'name': name, 'symbols': symbols, 'vertices': vertices,
            'names': names, 'atlases': atlases}


def build_symbol_images(build):
    """Reconstruct each symbol's triangles, preserving its original pivot."""
    result = {}
    for key, frames in build['symbols'].items():
        for frame in frames:
            number, duration, cx, cy, width, height, first, count = frame
            left, top = math.floor(cx - width / 2), math.floor(cy - height / 2)
            size = (math.ceil(cx + width / 2) - left,
                    math.ceil(cy + height / 2) - top)
            image = Image.new('RGBA', size)
            for start in range(first, first + count, 6):
                verts = build['vertices'][start:start + 6]
                if len(verts) != 6:
                    raise ValueError('Incomplete build quad')
                atlas = build['atlases'][round(verts[0][5])]
                # The compiled build splits large symbols into independent quads.
                # Their UVs and geometry are rectangular before animation transforms.
                x0, x1 = min(v[0] for v in verts), max(v[0] for v in verts)
                y0, y1 = min(v[1] for v in verts), max(v[1] for v in verts)
                u0, u1 = min(v[3] for v in verts), max(v[3] for v in verts)
                v0, v1 = min(v[4] for v in verts), max(v[4] for v in verts)
                crop = atlas.crop((round(u0 * atlas.width), round((1-v1) * atlas.height),
                                   round(u1 * atlas.width), round((1-v0) * atlas.height)))
                target = (max(1, round(x1-x0)), max(1, round(y1-y0)))
                crop = crop.resize(target, Image.Resampling.LANCZOS)
                image.paste(crop, (round(x0-left), round(y0-top)))
            for index in range(number, number + duration):
                result[key, index] = (image, left, top)
    return result


# Display labels are kept with the exported assets for the desktop menu.
LABELS = {
    'idle_loop': '待机', 'idle_happy': '开心', 'idle_earrub': '揉耳朵',
    'idle_angry': '生气', 'idle_creepy': '诡笑', 'hungry': '肚子饿',
    'dance': '跳舞', 'eat': '吃东西', 'eat_carrot': '吃胡萝卜',
    'carrot_offer': '递上胡萝卜', 'carrot_place': '放下胡萝卜',
    'carrot_spin': '旋转胡萝卜', 'eat_carrot_spun': '吃旋转胡萝卜',
    'disgust': '嫌弃',
    'pig_pickup': '拾取', 'pig_take': '接受礼物', 'pig_reject': '拒绝礼物',
    'walk_pre': '走路起步', 'walk_loop': '走路', 'walk_pst': '走路停下',
    'run_pre': '跑步起步', 'run_loop': '跑步', 'run_pst': '跑步停下',
    'sleep_pre': '入睡', 'sleep_loop': '睡觉', 'sleep_pst': '醒来',
    'alert_pre': '开始警觉', 'alert_loop': '警觉', 'alert_pst': '解除警觉',
    'frozen': '冰冻', 'frozen_loop_pst': '解冻',
    'shock_loop': '触电', 'shock_pst': '触电结束',
    'atk': '攻击', 'atk_object_pre': '举起枕头', 'atk_object': '挥打枕头',
    'idle_loop_overhead': '举枕头待机', 'walk_overhead_pre': '举枕头起步',
    'walk_overhead_loop': '举枕头走路', 'walk_overhead_pst': '举枕头停下',
    'hit': '受击', 'hit_big': '重击', 'abandon': '放弃追逐',
    'death': '倒下', 'corpse': '倒地', 'corpse_hit': '倒地受击',
    'spawn_pre': '出场准备', 'spawn_loop': '出场途中', 'spawn_pst': '出场落定',
    'despawn': '退场', 'trans_beard_pre': '变身前摇', 'trans_rabbit_pst': '变回兔人收尾',
    'boat_jump_pre': '跳跃准备', 'boat_jump': '起跳', 'boat_jump_loop': '空中跳跃',
    'boat_jump_pst': '落地', 'manrabbit': '跳跃参考姿势',
}


def action_group(name):
    if name.startswith(('sleep', 'frozen', 'shock')):
        return '休息与状态'
    if name.startswith(('walk', 'run', 'boat')):
        return '移动与跳跃'
    if name.startswith(('atk', 'hit', 'corpse', 'death', 'alert')) or name == 'idle_loop_overhead':
        return '枕头与战斗'
    if name.startswith(('spawn', 'despawn', 'trans')):
        return '出场与变化'
    return '日常互动'


def load_assets(anim_dir):
    symbols = {}
    all_names = {}
    animations = []
    sources = ['manrabbit_basic', 'manrabbit_actions', 'manrabbit_attacks', 'manrabbit_boat_jump']
    for name in ['manrabbit_build', *sources]:
        with zipfile.ZipFile(anim_dir / (name + '.zip')) as z:
            if 'build.bin' in z.namelist():
                build = parse_build(z)
                symbols.update(build_symbol_images(build))
                all_names.update(build['names'])
            if name in sources:
                clips, names = parse_anim(z.read('anim.bin'))
                for clip in clips:
                    clip['source'] = 'anim/' + name + '.zip'
                animations.extend(clips)
                all_names.update(names)
    equipment = {}
    for name in ['hat_nightcap', 'swap_pillows_petals', 'frozen']:
        with zipfile.ZipFile(anim_dir / (name + '.zip')) as z:
            build = parse_build(z)
            equipment[name] = build_symbol_images(build)
            all_names.update(build['names'])
    # despawn references a blank torso cell (6) absent from manrabbit_build.
    # Preserve that empty cell rather than substituting a visible body part.
    symbols[symbol_hash('manrabbit_torso'),6] = (Image.new('RGBA',(1,1)),0,0)
    return animations, symbols, equipment, all_names


def symbol_setup(skin, animation, base, equipment, *, lower_pillow=False):
    symbols = dict(base)
    hidden = set(HIDDEN_LAYERS)
    if skin != 'normal':
        symbols.update(equipment['hat_nightcap'])
        hidden = {symbol_hash(n) for n in ['HAIR', 'HAIR_NOHAT', 'ARM_carry']}
    carrying = ((skin == 'cozy_pillow' and not lower_pillow) or 'overhead' in animation
                or animation.startswith(('atk_object', 'pillow_putdown')))
    pillow = equipment['swap_pillows_petals']
    if skin == 'cozy_pillow':
        # The waist pillow is part of this skin even when its hand-held pillow
        # has been put down for a feeding or spin interaction.
        for (key, index), value in pillow.items():
            if key == symbol_hash('swap_body_rabbit'):
                symbols[symbol_hash('belt'), index] = value
    if carrying:
        for (key, index), value in pillow.items():
            if key == symbol_hash('swap_object'):
                symbols[key, index] = value
        hidden.discard(symbol_hash('ARM_carry'))
        hidden.add(symbol_hash('ARM_normal'))
    if animation.startswith('frozen'):
        for (key, index), value in equipment['frozen'].items():
            if key == symbol_hash('frozen'):
                symbols[symbol_hash('swap_frozen'), index] = value
    return symbols, hidden


def load_effect_assets(anim_dir):
    """Load the game builds and clips used for feed and action overlays."""
    result = {}
    for name in ('carrot', 'frozen_shatter', 'pillow_equipment_fx', 'sparks'):
        with zipfile.ZipFile(anim_dir / (name + '.zip')) as z:
            build = parse_build(z)
            clips, names = parse_anim(z.read('anim.bin'))
            for clip in clips:
                clip['source'] = 'anim/' + name + '.zip'
            result[name] = {
                'symbols': build_symbol_images(build),
                'clips': clips,
                'names': names | build['names'],
            }
    return result


def find_clip(animations, name, facing):
    for animation in animations:
        if animation['name'] == name and animation['facing'] == facing:
            return animation
    raise KeyError(f'Missing animation {name} facing {facing}')


def complete_animation_symbols(symbols, animations):
    """Hold the last built cell when an FX clip references an absent tail cell."""
    required = {}
    for animation in animations:
        for frame in animation['frames']:
            for key, index, *_ in frame['elements']:
                required[key] = max(index, required.get(key, -1))
    completed = dict(symbols)
    for key, max_index in required.items():
        available = sorted(index for symbol_key, index in symbols if symbol_key == key)
        if not available:
            continue
        for index in range(max_index + 1):
            if (key, index) in completed:
                continue
            earlier = [candidate for candidate in available if candidate < index]
            fallback = max(earlier) if earlier else min(available)
            completed[key, index] = symbols[key, fallback]
    return completed


def _save_clip_images(skin, clip_id, images, fps, label, group, source):
    folder = HERE / 'frames' / skin / clip_id
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, image in enumerate(images):
        path = folder / f'{index:03}.png'
        save_png_atomic(image, path)
        paths.append(path.relative_to(HERE).as_posix())
    name, facing = clip_id.rsplit('__', 1)
    return {
        'name': name, 'label': label, 'group': group, 'facing': int(facing),
        'fps': fps, 'source': source, 'frames': {skin: paths},
    }


def save_png_atomic(image, path):
    temporary = path.with_name(path.stem + '.new.png')
    image.save(temporary, format='PNG', compress_level=2)
    temporary.replace(path)


def _render_clip(clip, symbols, canvas, origin, hidden, scale):
    return [render_frame(frame, symbols, canvas, origin,
                         hidden_layers=hidden, scale=scale)
            for frame in clip['frames']]


def _blend_to_idle(start, idle, steps=7):
    """Blend a held-item pose into the first standing frame over several ticks."""
    return [Image.blend(start, idle, index / steps)
            for index in range(steps + 1)]


CARROT_GROUND_OFFSET = (130.0, -54.0)
CARROT_PROP_SCALE = 0.55
EAT_CONSUMPTION_FRAME = 4
CARROT_SPIN_LOOP_CYCLES = 2
CARROT_STOP_HOLD_FRAMES = 12


def _ground_prop_origin(origin, actor_scale, offset=CARROT_GROUND_OFFSET):
    """Keep a uniformly smaller prop at a fixed screen position and pivot."""
    prop_scale = actor_scale * CARROT_PROP_SCALE
    anchor_pixels = (
        origin[0] * actor_scale + offset[0] * actor_scale,
        origin[1] * actor_scale + offset[1] * actor_scale,
    )
    return anchor_pixels[0] / prop_scale, anchor_pixels[1] / prop_scale


def _overlay_prop(body, prop):
    if body.size != prop.size:
        raise ValueError(f'Body and prop canvases differ: {body.size} != {prop.size}')
    result = body.copy()
    result.alpha_composite(prop)
    return result


def _compose_prop_sequence(body_frames, prop_frames):
    if len(body_frames) != len(prop_frames):
        raise ValueError('Body and prop frame counts must match')
    return [_overlay_prop(body, prop)
            for body, prop in zip(body_frames, prop_frames)]


def _eat_carrot_frames(body_frames, ground_carrot,
                       consume_frame=EAT_CONSUMPTION_FRAME):
    """Show the ground carrot up to the native consume event, then raw body."""
    return [(_overlay_prop(body, ground_carrot) if index < consume_frame
             else body.copy())
            for index, body in enumerate(body_frames)]


def _carrot_spin_sequence(spin_pre, spin_loop, spin_pst,
                          loop_cycles=CARROT_SPIN_LOOP_CYCLES,
                          hold_frames=CARROT_STOP_HOLD_FRAMES):
    """Return native spin frames, holding the final stopped pose in place."""
    if loop_cycles < 1:
        raise ValueError('A carrot spin needs at least one spin_loop cycle')
    if hold_frames < 0:
        raise ValueError('The stopped hold cannot have a negative length')
    if not spin_pst:
        raise ValueError('The native spin_pst animation must contain a frame')
    return [*spin_pre,
            *(spin_loop * loop_cycles),
            *spin_pst,
            *([spin_pst[-1]] * hold_frames)]


def _render_ground_prop(frame, symbols, canvas, origin, scale):
    prop_scale = scale * CARROT_PROP_SCALE
    prop_origin = _ground_prop_origin(origin, scale)
    return render_frame(frame, symbols, canvas, prop_origin,
                        hidden_layers=set(), scale=prop_scale)


def _add_generated_clip(generated, skin, clip_id, name, label, group, fps,
                        source, images):
    entry = _save_clip_images(skin, clip_id, images, fps, label, group, source)
    generated.setdefault(clip_id, {
        'name': name, 'label': label, 'group': group,
        'facing': entry['facing'], 'fps': fps, 'source': source, 'frames': {},
    })
    generated[clip_id]['frames'][skin] = entry['frames'][skin]
    return entry


def _write_webp_preview(path, frames, fps):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(path, save_all=True, append_images=frames[1:],
                   duration=round(1000 / fps), loop=0, lossless=True)


def _write_carrot_review(preview_frames, fps):
    """Write transparent full-action previews and a compact comparison sheet."""
    from PIL import ImageDraw

    folder = HERE / '.build' / 'carrot-review'
    folder.mkdir(parents=True, exist_ok=True)
    clips = ('carrot_offer__255', 'carrot_place__255',
             'carrot_spin__8', 'eat_carrot__255', 'eat_carrot_spun__255')
    skins = ('normal', 'cozy', 'cozy_pillow')
    for clip_id in clips:
        for skin in skins:
            _write_webp_preview(folder / f'{clip_id}__{skin}.webp',
                                preview_frames[clip_id][skin], fps)

    keyframes = {
        'carrot_offer__255': lambda frames: len(frames) // 2,
        'carrot_place__255': lambda frames: len(frames) // 2,
        'carrot_spin__8': lambda frames: 16 + 8,
        'eat_carrot__255': lambda frames: 0,
        'eat_carrot_spun__255': lambda frames: 0,
    }
    cell_w, cell_h, image_w, image_h = 220, 232, 200, 198
    sheet = Image.new('RGB', (cell_w * len(skins), cell_h * len(clips)), '#f3f0e9')
    draw = ImageDraw.Draw(sheet)
    for row, clip_id in enumerate(clips):
        for column, skin in enumerate(skins):
            frames = preview_frames[clip_id][skin]
            index = min(keyframes[clip_id](frames), len(frames) - 1)
            image = frames[index].copy()
            image.thumbnail((image_w, image_h), Image.Resampling.LANCZOS)
            left = column * cell_w + (cell_w - image.width) // 2
            top = row * cell_h + 22 + (image_h - image.height) // 2
            sheet.paste('#d8d4ca', (column * cell_w, row * cell_h,
                                    (column + 1) * cell_w, (row + 1) * cell_h))
            sheet.paste(image, (left, top), image)
            draw.text((column * cell_w + 6, row * cell_h + 5),
                      f'{clip_id} / {skin} / f{index}', fill='#211e1a')
    sheet.save(folder / 'contact-sheet.png')

    proof = Image.new('RGB', (cell_w * 2, cell_h * len(skins)), '#f3f0e9')
    draw = ImageDraw.Draw(proof)
    for row, skin in enumerate(skins):
        for column, clip_id in enumerate(('eat_carrot__255', 'eat_carrot_spun__255')):
            frame = preview_frames[clip_id][skin][EAT_CONSUMPTION_FRAME].copy()
            frame.thumbnail((image_w, image_h), Image.Resampling.LANCZOS)
            left = column * cell_w + (cell_w - frame.width) // 2
            top = row * cell_h + 22 + (image_h - frame.height) // 2
            proof.paste('#d8d4ca', (column * cell_w, row * cell_h,
                                    (column + 1) * cell_w, (row + 1) * cell_h))
            proof.paste(frame, (left, top), frame)
            label = 'idle' if clip_id == 'eat_carrot__255' else 'spun'
            draw.text((column * cell_w + 6, row * cell_h + 5),
                      f'{skin} / {label} / raw eat f{EAT_CONSUMPTION_FRAME}',
                      fill='#211e1a')
    proof.save(folder / 'eat-consume-frame4.png')


def export_extra_assets(anim_dir, animations, base, equipment, manifest, scale):
    """Export changed transitions and visual extras without rewriting old clips."""
    extras = load_effect_assets(anim_dir)
    canvas = tuple(manifest['canvas'])
    origin_pixels = tuple(manifest['origin'])
    origin = tuple(value / scale for value in origin_pixels)
    skins = manifest['skins']
    by_name_and_facing = {(a['name'], a['facing']): a for a in animations}
    generated = {}
    preview_frames = {}

    # Lowering the pillow reuses the real lift animation in reverse. The attack
    # ending starts from its own final pose and dissolves into standing instead.
    for facing in sorted({f for name, f in by_name_and_facing if name == 'atk_object_pre'}):
        pre = by_name_and_facing['atk_object_pre', facing]
        attack = by_name_and_facing['atk_object', facing]
        idle = by_name_and_facing['idle_loop', facing]
        putdown_id = f'pillow_putdown__{facing}'
        attack_release_id = f'pillow_attack_release__{facing}'
        for skin in skins:
            pillow_symbols, pillow_hidden = symbol_setup(
                skin, 'pillow_putdown', base, equipment
            )
            putdown_frames = _render_clip(
                {'frames': list(reversed(pre['frames']))}, pillow_symbols,
                canvas, origin, pillow_hidden, scale,
            )
            idle_symbols, idle_hidden = symbol_setup(skin, 'idle_loop', base, equipment)
            idle_image = render_frame(idle['frames'][0], idle_symbols, canvas, origin,
                                      hidden_layers=idle_hidden, scale=scale)
            putdown_frames.extend(_blend_to_idle(putdown_frames[-1], idle_image)[1:])
            entry = _save_clip_images(
                skin, putdown_id, putdown_frames, 30, '放下枕头', '枕头与战斗',
                'reverse of anim/manrabbit_attacks.zip:atk_object_pre',
            )
            generated.setdefault(putdown_id, {'name': 'pillow_putdown',
                                                'label': '放下枕头',
                                                'group': '枕头与战斗',
                                                'facing': facing, 'fps': 30,
                                                'source': entry['source'], 'frames': {}})
            generated[putdown_id]['frames'][skin] = entry['frames'][skin]

            attack_symbols, attack_hidden = symbol_setup(skin, 'atk_object', base, equipment)
            attack_image = render_frame(attack['frames'][-1], attack_symbols, canvas, origin,
                                        hidden_layers=attack_hidden, scale=scale)
            release_frames = _blend_to_idle(attack_image, idle_image)
            entry = _save_clip_images(
                skin, attack_release_id, release_frames, 30, '放下枕头', '枕头与战斗',
                'blend of anim/manrabbit_attacks.zip:atk_object and idle_loop',
            )
            generated.setdefault(attack_release_id, {'name': 'pillow_attack_release',
                                                       'label': '放下枕头',
                                                       'group': '枕头与战斗',
                                                       'facing': facing, 'fps': 30,
                                                       'source': entry['source'], 'frames': {}})
            generated[attack_release_id]['frames'][skin] = entry['frames'][skin]

    carrot_anim = extras['carrot']
    carrot_idle = find_clip(carrot_anim['clips'], 'idle', 255)
    carrot_idle_prop = _render_ground_prop(
        carrot_idle['frames'][0], carrot_anim['symbols'], canvas, origin, scale,
    )
    carrot_bounds = carrot_idle_prop.getbbox()
    carrot = carrot_idle_prop.crop(carrot_bounds) if carrot_bounds else Image.new('RGBA', (1, 1))

    # These two gestures keep the same ground carrot in place. Their native
    # poses make the offer and the later pickup readable without inventing a
    # carrot hand pose.
    offer = find_clip(animations, 'pig_take', 255)
    place = find_clip(animations, 'pig_pickup', 255)
    for clip, clip_id, name, label in (
        (offer, 'carrot_offer__255', 'carrot_offer', '递上胡萝卜'),
        (place, 'carrot_place__255', 'carrot_place', '放下胡萝卜'),
    ):
        source = f"{clip['source']}:{clip['name']} + {carrot_idle['source']}:idle"
        preview_frames[clip_id] = {}
        for skin in skins:
            symbols, hidden = symbol_setup(
                skin, name, base, equipment, lower_pillow=True,
            )
            body_frames = _render_clip(clip, symbols, canvas, origin, hidden, scale)
            props = [carrot_idle_prop] * len(body_frames)
            frames = _compose_prop_sequence(body_frames, props)
            _add_generated_clip(generated, skin, clip_id, name, label,
                                '日常互动', clip['fps'], source, frames)
            preview_frames[clip_id][skin] = frames

    # Spin with the native carrot pre/loop/post sequence while the rabbit
    # stays in its front-facing idle. Hold the post clip's final pose so the
    # carrot keeps the same orientation when the feeding clip starts.
    spin_pre = find_clip(carrot_anim['clips'], 'spin_pre', 255)
    spin_loop = find_clip(carrot_anim['clips'], 'spin_loop', 255)
    spin_pst = find_clip(carrot_anim['clips'], 'spin_pst', 8)
    idle_loop = find_clip(animations, 'idle_loop', 8)
    prop_spin_frames = _carrot_spin_sequence(
        spin_pre['frames'], spin_loop['frames'], spin_pst['frames'],
    )
    spin_fps = spin_pre['fps']
    if any(clip['fps'] != spin_fps for clip in
           (spin_loop, spin_pst, carrot_idle, idle_loop)):
        raise ValueError('Native bunnyman and carrot spin clips must share one FPS')
    spin_source = (
        f"{idle_loop['source']}:idle_loop + {spin_pre['source']}:spin_pre + "
        f"{spin_loop['source']}:spin_loop x{CARROT_SPIN_LOOP_CYCLES} + "
        f"{spin_pst['source']}:spin_pst facing 8 + final pose held "
        f"{CARROT_STOP_HOLD_FRAMES} frames"
    )
    spin_id = 'carrot_spin__8'
    preview_frames[spin_id] = {}
    for skin in skins:
        symbols, hidden = symbol_setup(
            skin, 'carrot_spin', base, equipment, lower_pillow=True,
        )
        body_idle = _render_clip(idle_loop, symbols, canvas, origin, hidden, scale)
        body_frames = [body_idle[index % len(body_idle)]
                       for index in range(len(prop_spin_frames))]
        props = [_render_ground_prop(frame, carrot_anim['symbols'], canvas, origin,
                                     scale)
                 for frame in prop_spin_frames]
        bottom_limit = round(origin_pixels[1] + 4)
        if any(prop.getbbox() and prop.getbbox()[3] > bottom_limit for prop in props):
            raise AssertionError('A spinning carrot frame extends below its floor line')
        frames = _compose_prop_sequence(body_frames, props)
        _add_generated_clip(generated, skin, spin_id, 'carrot_spin', '旋转胡萝卜',
                            '日常互动', spin_fps, spin_source, frames)
        preview_frames[spin_id][skin] = frames

    # The game consumes a carrot at 4 FRAMES. It stays on the ground through
    # those four ticks; every frame after that is the untouched native eat
    # body rendered with its hand pillow lowered on the cozy_pillow skin.
    eat = find_clip(animations, 'eat', 255)
    eat_id = 'eat_carrot__255'
    eat_source = f"{eat['source']}:eat + {carrot_idle['source']}:idle"
    spun_eat_id = 'eat_carrot_spun__255'
    spun_carrot_prop = _render_ground_prop(
        spin_pst['frames'][-1], carrot_anim['symbols'], canvas, origin, scale,
    )
    spun_eat_source = (
        f"{eat['source']}:eat + {spin_pst['source']}:spin_pst facing 8"
    )
    preview_frames[eat_id] = {}
    preview_frames[spun_eat_id] = {}
    for skin in skins:
        symbols, hidden = symbol_setup(
            skin, 'eat', base, equipment, lower_pillow=True,
        )
        body_frames = _render_clip(eat, symbols, canvas, origin, hidden, scale)
        frames = _eat_carrot_frames(body_frames, carrot_idle_prop)
        spun_frames = _eat_carrot_frames(body_frames, spun_carrot_prop)
        if any(frames[index].tobytes() != body_frames[index].tobytes()
               for index in range(EAT_CONSUMPTION_FRAME, len(frames))):
            raise AssertionError(f'{skin} eat frames changed after native consume frame')
        if any(spun_frames[index].tobytes() != body_frames[index].tobytes()
               for index in range(EAT_CONSUMPTION_FRAME, len(spun_frames))):
            raise AssertionError(f'{skin} spun-eat frames changed after native consume frame')
        _add_generated_clip(generated, skin, eat_id, 'eat_carrot', '吃胡萝卜',
                            '日常互动', eat['fps'], eat_source, frames)
        _add_generated_clip(generated, skin, spun_eat_id, 'eat_carrot_spun',
                            '吃旋转胡萝卜', '日常互动', eat['fps'], spun_eat_source,
                            spun_frames)
        preview_frames[eat_id][skin] = frames
        preview_frames[spun_eat_id][skin] = spun_frames

    _write_carrot_review(preview_frames, spin_fps)

    # Preserve the exact character canvas and origin, so UI overlays align by
    # frame path alone and can contribute their alpha to the window mask.
    effects = {
        'hit': ('sparks', 'sparks_1', 2),
        'thaw': ('frozen_shatter', 'medium', 1),
        'pillow': ('pillow_equipment_fx', 'debris_petals', 1),
    }
    manifest.setdefault('effects', {})
    for effect_name, (asset_name, animation_name, effect_scale) in effects.items():
        asset = extras[asset_name]
        clip = find_clip(asset['clips'], animation_name, 255)
        effect_symbols = complete_animation_symbols(asset['symbols'], [clip])
        effect_origin = tuple(value / effect_scale for value in origin)
        frames = [render_frame(frame, effect_symbols, canvas, effect_origin,
                               hidden_layers=set(), scale=scale * effect_scale)
                  for frame in clip['frames']]
        folder = HERE / 'frames' / 'effects' / effect_name
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for index, image in enumerate(frames):
            path = folder / f'{index:03}.png'
            save_png_atomic(image, path)
            paths.append(path.relative_to(HERE).as_posix())
        manifest['effects'][effect_name] = {
            'frames': paths, 'fps': clip['fps'], 'anchor': 'body',
            'origin': list(origin_pixels),
            'source': f'anim/{asset_name}.zip:{animation_name}',
        }

    prop_path = HERE / 'props' / 'carrot.png'
    prop_path.parent.mkdir(parents=True, exist_ok=True)
    save_png_atomic(carrot, prop_path)
    manifest['props'] = {'carrot': {'path': prop_path.relative_to(HERE).as_posix()}}
    manifest.pop('game_directory', None)
    manifest['animations'].update(generated)
    manifest['source_scripts'] = list(dict.fromkeys([
        *manifest.get('source_scripts', []),
        'stategraphs/SGcozy_bunnyman.lua', 'brains/cozy_bunnymanbrain.lua',
        'prefabs/carrot.lua', 'prefabs/veggies.lua',
        'prefabs/shatter.lua', 'prefabs/sparks.lua', 'prefabs/pillow_equipment.lua',
    ]))
    manifest['statistics'] = {
        'action_names': len({entry['name'] for entry in manifest['animations'].values()}),
        'directional_clips': len(manifest['animations']),
        'frames_per_skin': sum(len(entry['frames'].get('normal', []))
                               for entry in manifest['animations'].values()),
    }


def visible_bounds(frame, symbols, hidden):
    bounds = []
    for key, index, layer, a, b, c, d, tx, ty, z in frame['elements']:
        if layer in hidden:
            continue
        if (key, index) not in symbols:
            if key in OPTIONAL_SLOTS:
                continue
            raise KeyError(f'Missing required symbol {key}/{index}')
        image, left, top = symbols[key,index]
        box = image.getbbox()
        if not box:
            continue
        x0,y0,x1,y1 = box
        for x,y in [(x0+left,y0+top),(x1+left,y0+top),(x0+left,y1+top),(x1+left,y1+top)]:
            bounds.append((a*x+c*y+tx,b*x+d*y+ty))
    return bounds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True,
                        help='Path to the local Don\'t Starve Together installation')
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--sample', action='store_true', help='Render a few sample frames for visual checks')
    parser.add_argument('--extras-only', action='store_true',
                        help='Render new props, effects, and transition clips only')
    args = parser.parse_args()
    animations, base, equipment, names = load_assets(args.game/'data'/'anim')
    if args.inspect:
        print([(a['name'], a['facing'],len(a['frames'])) for a in animations])
        print({n:sorted(set(k for k,i in v)) for n,v in equipment.items()})
        return
    # Keep body scale and ground pivot identical across clips and all three looks.
    setups = {(skin,a['name']): symbol_setup(skin,a['name'],base,equipment)
              for skin in ['normal','cozy','cozy_pillow'] for a in animations}
    points = [p for skin in ['normal','cozy','cozy_pillow'] for a in animations
              for f in a['frames'] for p in visible_bounds(f,*setups[skin,a['name']])]
    left,top = math.floor(min(x for x,y in points))-20,math.floor(min(y for x,y in points))-20
    right,bottom = math.ceil(max(x for x,y in points))+20,math.ceil(max(y for x,y in points))+20
    scale = min(1, 620/max(right-left,bottom-top))
    canvas = (math.ceil((right-left)*scale),math.ceil((bottom-top)*scale))
    origin = (-left,-top)
    manifest = {'version':2, 'fps':30, 'default_skin':'cozy', 'default_animation':'idle_loop',
                'canvas':canvas, 'origin':[origin[0]*scale,origin[1]*scale],
                'skins':{'normal':{'label':'普通兔人'}, 'cozy':{'label':'睡帽兔人'},
                         'cozy_pillow':{'label':'睡帽＋枕头'}},
                'animations':{},
                'source_scripts':['prefabs/bunnyman.lua','prefabs/cozy_bunnyman.lua',
                                  'prefabs/hats.lua','prefabs/pillow_equipment.lua','stategraphs/commonstates.lua']}
    print('Canvas',canvas,'origin',manifest['origin'],'scale',scale,flush=True)
    if args.extras_only:
        existing = json.loads((HERE / 'manifest.json').read_text(encoding='utf-8'))
        export_extra_assets(args.game/'data'/'anim', animations, base, equipment,
                            existing, scale)
        target = HERE/'manifest.json'
        temporary = HERE/'manifest.new.json'
        temporary.write_text(json.dumps(existing,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(target)
        print('Updated extras',existing['statistics'],flush=True)
        return
    if args.sample:
        from PIL import ImageDraw
        samples = []
        for skin in manifest['skins']:
            for name in ['idle_loop','sleep_loop','atk_object','dance']:
                a = next(a for a in animations if a['name']==name and a['facing'] in (8,255))
                image = render_frame(a['frames'][len(a['frames'])//2],*setups[skin,name][:1],canvas,origin,
                                     hidden_layers=setups[skin,name][1],scale=scale)
                samples.append((skin,name,image))
        sheet = Image.new('RGB',(960,900),'#e6dfd0')
        draw = ImageDraw.Draw(sheet)
        for i,(skin,name,image) in enumerate(samples):
            image.thumbnail((220,270))
            x,y=(i%4)*240,(i//4)*300
            sheet.paste(image,(x+(240-image.width)//2,y+22),image)
            draw.text((x+8,y+5),skin+' / '+name,fill='#3b342e')
        sheet.save(HERE/'full_sample.jpg')
        return
    for a in animations:
        name = a['name']
        clipid = name+'__'+str(a['facing'])
        entry = {'name':name,'label':LABELS.get(name,name),'group':action_group(name),
                 'facing':a['facing'],'fps':a['fps'],'source':a['source'],'frames':{}}
        for skin in manifest['skins']:
            symbols,hidden = setups[skin,name]
            folder = HERE/'frames'/skin/clipid
            folder.mkdir(parents=True,exist_ok=True)
            paths = []
            preview_images = []
            for i,frame in enumerate(a['frames']):
                image = render_frame(frame,symbols,canvas,origin,hidden_layers=hidden,scale=scale)
                path = folder/f'{i:03}.png'
                image.save(path,compress_level=2)
                paths.append(path.relative_to(HERE).as_posix())
                if name in ('idle_loop','dance','sleep_loop','idle_earrub') and a['facing'] in (8,255):
                    preview_images.append(image)
            entry['frames'][skin] = paths
            if preview_images:
                boxes = [im.getbbox() for im in preview_images if im.getbbox()]
                if boxes:
                    box=(min(b[0] for b in boxes)-5,min(b[1] for b in boxes)-5,
                         max(b[2] for b in boxes)+5,max(b[3] for b in boxes)+5)
                    preview_images=[im.crop(box) for im in preview_images]
                    for im in preview_images:
                        im.thumbnail((300,300))
                    stem=skin+'_'+name
                    preview_images[0].save(HERE/(stem+'.webp'),save_all=True,append_images=preview_images[1:],
                                           duration=round(1000/a['fps']),loop=0,lossless=True)
                    preview_images[0].save(HERE/(stem+'.png'))
        manifest['animations'][clipid]=entry
        print('Rendered',clipid,len(a['frames']),'frames x 3 looks',flush=True)
    export_extra_assets(args.game/'data'/'anim', animations, base, equipment,
                        manifest, scale)
    target=HERE/'manifest.json'
    temporary=HERE/'manifest.new.json'
    temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(target)
    print('Ready',manifest['statistics'],flush=True)


def render_frame(frame, symbols, canvas, origin, hidden_layers=None, scale=1):
    result = Image.new('RGBA', canvas)
    hidden_layers = HIDDEN_LAYERS if hidden_layers is None else hidden_layers
    for element in sorted(frame['elements'], key=lambda e: e[-1], reverse=True):
        key, index, layer, a, b, c, d, tx, ty, z = element
        if layer in hidden_layers:
            continue
        if (key, index) not in symbols:
            # Hat/held-item/frozen/belt swap slots have no default image.
            if key in OPTIONAL_SLOTS:
                continue
            raise KeyError(f'Missing symbol {key} frame {index}')
        image, left, top = symbols[key, index]
        transform = np.array([[a, c, tx + origin[0] + a*left + c*top],
                              [b, d, ty + origin[1] + b*left + d*top],
                              [0, 0, 1]], dtype=float)
        transform[:2] *= scale
        if abs(np.linalg.det(transform)) < 1e-8:
            continue
        corners = transform @ np.array([[0, image.width, 0, image.width],
                                         [0, 0, image.height, image.height], [1,1,1,1]])
        x0, y0 = np.floor(corners[:2].min(axis=1)-2).astype(int)
        x1, y1 = np.ceil(corners[:2].max(axis=1)+2).astype(int)
        x0, y0 = max(0,x0), max(0,y0)
        x1, y1 = min(canvas[0],x1), min(canvas[1],y1)
        if x1 <= x0 or y1 <= y0:
            continue
        transform[:2,2] -= [x0,y0]
        inverse = np.linalg.inv(transform)
        transformed = image.transform((x1-x0,y1-y0), Image.Transform.AFFINE,
                                      tuple(inverse[:2].ravel()), Image.Resampling.BICUBIC)
        result.alpha_composite(transformed, (x0,y0))
    return result


if __name__ == '__main__':
    main()
