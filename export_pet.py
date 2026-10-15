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
    'dance': '跳舞', 'eat': '吃东西', 'disgust': '嫌弃',
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


def symbol_setup(skin, animation, base, equipment):
    symbols = dict(base)
    hidden = set(HIDDEN_LAYERS)
    if skin != 'normal':
        symbols.update(equipment['hat_nightcap'])
        hidden = {symbol_hash(n) for n in ['HAIR', 'HAIR_NOHAT', 'ARM_carry']}
    carrying = (skin == 'cozy_pillow' or 'overhead' in animation
                or animation.startswith(('atk_object', 'pillow_putdown')))
    if carrying:
        pillow = equipment['swap_pillows_petals']
        for (key, index), value in pillow.items():
            if key == symbol_hash('swap_object'):
                symbols[key, index] = value
            if skin == 'cozy_pillow' and key == symbol_hash('swap_body_rabbit'):
                symbols[symbol_hash('belt'), index] = value
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


def _carrot_image(effect_assets, scale):
    carrot = effect_assets['carrot']
    idle = find_clip(carrot['clips'], 'idle', 255)
    points = visible_bounds(idle['frames'][0], carrot['symbols'], set())
    left = math.floor(min(x for x, _ in points)) - 3
    top = math.floor(min(y for _, y in points)) - 3
    right = math.ceil(max(x for x, _ in points)) + 3
    bottom = math.ceil(max(y for _, y in points)) + 3
    canvas = (max(1, math.ceil((right - left) * scale)),
              max(1, math.ceil((bottom - top) * scale)))
    origin = (-left, -top)
    image = render_frame(idle['frames'][0], carrot['symbols'], canvas, origin,
                         hidden_layers=set(), scale=scale)
    box = image.getbbox()
    return image.crop(box) if box else image


EAT_CARROT_SCALE = 0.68
EAT_CARROT_BITE_START = 28
EAT_CARROT_BITE_END = 40


def _eat_carrot_frame(body, carrot, index, total, origin):
    """Move the real carrot from the hand to the mouth, hold, then eat it."""
    if index >= EAT_CARROT_BITE_END:
        return body
    image = carrot
    if index <= 4:
        amount = index / 4
        center_x = origin[0] + 12
        center_y = origin[1] - (78 + 30 * amount)
    elif index < EAT_CARROT_BITE_START:
        center_x = origin[0] + 12
        center_y = origin[1] - 108
    else:
        amount = max(0.0, (EAT_CARROT_BITE_END - index) /
                     (EAT_CARROT_BITE_END - EAT_CARROT_BITE_START))
        if amount <= 0:
            return body
        size = (max(1, round(carrot.width * amount)),
                max(1, round(carrot.height * amount)))
        image = carrot.resize(size, Image.Resampling.LANCZOS)
        alpha = image.getchannel('A').point(lambda value: round(value * amount))
        image.putalpha(alpha)
        center_x = origin[0] + 12
        center_y = origin[1] - 108
    x = round(center_x - image.width / 2)
    y = round(center_y - image.height / 2)
    body.alpha_composite(image, (x, y))
    return body


def export_extra_assets(anim_dir, animations, base, equipment, manifest, scale):
    """Export changed transitions and visual extras without rewriting old clips."""
    extras = load_effect_assets(anim_dir)
    canvas = tuple(manifest['canvas'])
    origin_pixels = tuple(manifest['origin'])
    origin = tuple(value / scale for value in origin_pixels)
    skins = manifest['skins']
    by_name_and_facing = {(a['name'], a['facing']): a for a in animations}
    generated = {}

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

    # Keep the original eat clip intact for the raw preview. Composite the
    # actual carrot sprite over its hand/mouth movement for the player action.
    eat = find_clip(animations, 'eat', 255)
    carrot = _carrot_image(extras, scale)
    carrot_for_eating = carrot.resize(
        (max(1, round(carrot.width * EAT_CARROT_SCALE)),
         max(1, round(carrot.height * EAT_CARROT_SCALE))),
        Image.Resampling.LANCZOS,
    )
    eat_id = 'eat_carrot__255'
    for skin in skins:
        symbols, hidden = symbol_setup(skin, 'eat', base, equipment)
        body_frames = _render_clip(eat, symbols, canvas, origin, hidden, scale)
        frames = [_eat_carrot_frame(frame, carrot_for_eating, index,
                                    len(body_frames), origin_pixels)
                  for index, frame in enumerate(body_frames)]
        entry = _save_clip_images(
            skin, eat_id, frames, eat['fps'], '吃胡萝卜', '日常互动',
            'anim/manrabbit_actions.zip:eat + anim/carrot.zip:idle',
        )
        generated.setdefault(eat_id, {'name': 'eat_carrot', 'label': '吃胡萝卜',
                                      'group': '日常互动', 'facing': 255,
                                      'fps': eat['fps'], 'source': entry['source'],
                                      'frames': {}})
        generated[eat_id]['frames'][skin] = entry['frames'][skin]

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
        'stategraphs/SGcozy_bunnyman.lua', 'prefabs/carrot.lua', 'prefabs/veggies.lua',
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
