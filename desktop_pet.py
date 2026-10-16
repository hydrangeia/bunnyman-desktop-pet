"""Transparent DST rabbit desktop pet with lazy-loaded animation clips."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DISPLAY_SIZE = 520
CLICK_DRAG_THRESHOLD = 5
PIXMAP_CACHE_SEGMENTS = 8

ACTION_LABELS = {
    "idle_loop": "待机",
    "idle_happy": "开心",
    "idle_earrub": "揉耳朵",
    "idle_angry": "生气",
    "idle_creepy": "诡笑",
    "hungry": "饥饿",
    "eat": "吃东西",
    "dance": "跳舞",
    "disgust": "嫌弃",
    "pig_pickup": "拾取",
    "pig_take": "接收",
    "pig_reject": "拒绝",
    "hit": "受击",
    "hit_big": "重击",
    "corpse_hit": "受击",
    "atk": "攻击",
    "atk_object_pre": "挥枕头",
    "atk_object": "挥枕头",
    "idle_loop_overhead": "举枕待机",
    "walk_overhead_pre": "举枕走路",
    "walk_overhead_loop": "举枕走路",
    "walk_overhead_pst": "举枕走路",
    "sleep_pre": "睡觉",
    "sleep_loop": "睡觉",
    "sleep_pst": "醒来",
    "alert_pre": "警觉",
    "alert_loop": "警觉",
    "alert_pst": "警觉",
    "frozen": "冰冻",
    "frozen_loop_pst": "解冻",
    "abandon": "退场",
    "death": "死亡",
    "corpse": "死亡",
    "trans_beard_pre": "胡须变化",
    "trans_rabbit_pst": "兔人变化",
    "spawn_pre": "出场",
    "spawn_loop": "出场",
    "spawn_pst": "出场",
    "despawn": "退场",
    "boat_jump_pre": "跳船",
    "boat_jump": "跳船",
    "boat_jump_loop": "跳船",
    "boat_jump_pst": "跳船",
    "getup": "起身复原",
    "recover": "起身复原",
    "walk_pre": "走路",
    "walk_loop": "走路",
    "walk_pst": "走路",
    "run_pre": "跑步",
    "run_loop": "跑步",
    "run_pst": "跑步",
}

GROUP_LABELS = {
    "basic": "基础动作",
    "basics": "基础动作",
    "action": "行为动作",
    "actions": "行为动作",
    "behavior": "行为动作",
    "behaviour": "行为动作",
    "attack": "攻击动作",
    "attacks": "攻击动作",
    "combat": "攻击动作",
    "boat": "船上动作",
    "boat_jump": "船上动作",
    "movement": "移动动作",
    "move": "移动动作",
    "transform": "变身动作",
    "transformation": "变身动作",
}


@dataclass(frozen=True)
class Clip:
    clip_id: str
    name: str
    label: str
    group: str
    facing: str
    fps: float
    frames: dict[str, tuple[Path, ...]]


@dataclass(frozen=True)
class Effect:
    name: str
    fps: float
    anchor: str
    origin: tuple[float, float] | None
    frames: tuple[Path, ...]


@dataclass(frozen=True)
class PetManifest:
    path: Path
    skins: dict[str, str]
    default_skin: str
    default_animation: str
    clips: dict[str, Clip]
    canvas: tuple[float, float] | None
    origin: tuple[float, float] | None
    props: dict[str, Path]
    effects: dict[str, Effect]

    @property
    def names(self) -> list[str]:
        return list(dict.fromkeys(clip.name for clip in self.clips.values()))

    def group_for(self, name: str) -> str:
        for clip in self.clips.values():
            if clip.name == name:
                return clip.group or "其他"
        return "其他"

    def label_for(self, name: str) -> str:
        if name in ACTION_LABELS:
            return ACTION_LABELS[name]
        for clip in self.clips.values():
            if clip.name == name and clip.label:
                return clip.label
        return name


def _as_facing(value: Any) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


def load_manifest(manifest_path: Path) -> PetManifest:
    """Parse both the skin-aware v2 manifest and the original single-skin format."""
    manifest_path = manifest_path.resolve()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取动画清单 {manifest_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("manifest.json 顶层必须是对象")

    raw_skins = raw.get("skins")
    if isinstance(raw_skins, dict) and raw_skins:
        skins = {
            str(skin_id): str(
                skin_info.get("label", skin_id)
                if isinstance(skin_info, dict)
                else skin_info or skin_id
            )
            for skin_id, skin_info in raw_skins.items()
        }
    else:
        skins = {"default": "默认外观"}
    default_skin = str(raw.get("default_skin", next(iter(skins))))
    if default_skin not in skins:
        default_skin = next(iter(skins))

    raw_animations = raw.get("animations")
    if not isinstance(raw_animations, dict) or not raw_animations:
        raise ValueError("manifest.json 中没有 animations 动画")

    clips: dict[str, Clip] = {}
    for clip_id, definition in raw_animations.items():
        if not isinstance(clip_id, str) or not isinstance(definition, dict):
            continue
        logical_name = str(definition.get("name", clip_id))
        facing = _as_facing(definition.get("facing", 255))
        raw_fps = definition.get("fps", raw.get("fps", 12))
        try:
            fps = float(raw_fps)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"动画 {clip_id} 的 fps 必须是正数") from exc
        if fps <= 0:
            raise ValueError(f"动画 {clip_id} 的 fps 必须是正数")

        raw_frames = definition.get("frames")
        if isinstance(raw_frames, list):
            frames_by_skin: dict[str, Any] = {default_skin: raw_frames}
        elif isinstance(raw_frames, dict):
            frames_by_skin = raw_frames
        else:
            continue

        frames: dict[str, tuple[Path, ...]] = {}
        for skin_id, paths in frames_by_skin.items():
            if not isinstance(paths, list) or not paths:
                continue
            normalized_paths: list[Path] = []
            for frame_path in paths:
                if not isinstance(frame_path, str):
                    raise ValueError(f"动画 {clip_id} 的帧路径必须是字符串")
                normalized_paths.append((manifest_path.parent / frame_path).resolve())
            if normalized_paths:
                frames[str(skin_id)] = tuple(normalized_paths)
        if not frames:
            continue
        clips[clip_id] = Clip(
            clip_id=clip_id,
            name=logical_name,
            label=str(definition.get("label", logical_name)),
            group=str(definition.get("group", "其他")),
            facing=facing,
            fps=fps,
            frames=frames,
        )

    if not clips:
        raise ValueError("manifest.json 中没有包含帧路径的动画片段")
    default_animation = str(raw.get("default_animation", "idle_loop"))
    if default_animation not in {clip.name for clip in clips.values()}:
        if default_animation in clips:
            default_animation = clips[default_animation].name
        else:
            default_animation = clips[next(iter(clips))].name
    raw_canvas = raw.get("canvas")
    canvas = (
        (float(raw_canvas[0]), float(raw_canvas[1]))
        if isinstance(raw_canvas, list) and len(raw_canvas) == 2
        else None
    )
    raw_origin = raw.get("origin")
    origin = (
        (float(raw_origin[0]), float(raw_origin[1]))
        if isinstance(raw_origin, list) and len(raw_origin) == 2
        else None
    )
    props: dict[str, Path] = {}
    raw_props = raw.get("props")
    if isinstance(raw_props, dict):
        for prop_id, definition in raw_props.items():
            if isinstance(definition, dict) and isinstance(definition.get("path"), str):
                props[str(prop_id)] = (manifest_path.parent / definition["path"]).resolve()

    effects: dict[str, Effect] = {}
    raw_effects = raw.get("effects")
    if isinstance(raw_effects, dict):
        for effect_id, definition in raw_effects.items():
            if not isinstance(definition, dict):
                continue
            raw_paths = definition.get("frames")
            if not isinstance(raw_paths, list) or not raw_paths:
                continue
            paths: list[Path] = []
            for frame_path in raw_paths:
                if not isinstance(frame_path, str):
                    raise ValueError(f"特效 {effect_id} 的帧路径必须是字符串")
                paths.append((manifest_path.parent / frame_path).resolve())
            try:
                fps = float(definition.get("fps", raw.get("fps", 12)))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"特效 {effect_id} 的 fps 必须是正数") from exc
            if fps <= 0:
                raise ValueError(f"特效 {effect_id} 的 fps 必须是正数")
            raw_effect_origin = definition.get("origin")
            effect_origin = (
                (float(raw_effect_origin[0]), float(raw_effect_origin[1]))
                if isinstance(raw_effect_origin, list) and len(raw_effect_origin) == 2
                else None
            )
            effects[str(effect_id)] = Effect(
                name=str(effect_id),
                fps=fps,
                anchor=str(definition.get("anchor", "body")),
                origin=effect_origin,
                frames=tuple(paths),
            )
    return PetManifest(
        path=manifest_path,
        skins=skins,
        default_skin=default_skin,
        default_animation=default_animation,
        clips=clips,
        canvas=canvas,
        origin=origin,
        props=props,
        effects=effects,
    )


def choose_variant(
    manifest: PetManifest, name: str, direction: str, skin: str
) -> tuple[Clip, str, bool]:
    """Choose an exact directional clip, then a universal or available fallback."""
    directional_facing = {"front": "8", "left": "5", "right": "5", "back": "2"}.get(
        direction, "8"
    )
    candidates = [clip for clip in manifest.clips.values() if clip.name == name]
    if not candidates:
        candidates = [
            clip for clip in manifest.clips.values()
            if clip.name == manifest.default_animation
        ]
    if not candidates:
        candidates = list(manifest.clips.values())

    order = [directional_facing, "255", "245", "8", "5", "2"]
    preferred = next((face for face in order if any(c.facing == face for c in candidates)), None)
    if preferred is not None:
        clip = next(clip for clip in candidates if clip.facing == preferred)
    else:
        clip = candidates[0]

    if skin in clip.frames:
        resolved_skin = skin
    elif manifest.default_skin in clip.frames:
        resolved_skin = manifest.default_skin
    else:
        resolved_skin = next(iter(clip.frames))
    mirror = direction == "left" and clip.facing == "5"
    return clip, resolved_skin, mirror


def validate_manifest_frames(manifest: PetManifest) -> tuple[int, tuple[int, int]]:
    """Check every referenced frame header and confirm a shared canvas size."""
    from PySide6.QtGui import QImageReader

    frame_count = 0
    canvas: tuple[int, int] | None = None
    frame_sets = [
        (f"{clip.clip_id}/{skin_id}", paths)
        for clip in manifest.clips.values()
        for skin_id, paths in clip.frames.items()
    ]
    frame_sets.extend(
        (f"effect/{effect.name}", effect.frames)
        for effect in manifest.effects.values()
    )
    for prop_id, path in manifest.props.items():
        if not path.is_file():
            raise ValueError(f"缺少道具图片 {prop_id}: {path}")
    for set_name, paths in frame_sets:
        for path in paths:
            if not path.is_file():
                raise ValueError(f"缺少动画帧 {set_name}: {path}")
            reader = QImageReader(str(path))
            size = reader.size()
            if not size.isValid():
                image = reader.read()
                if image.isNull():
                    raise ValueError(f"无法解析动画帧 {path}")
                size = image.size()
            current_size = (size.width(), size.height())
            if current_size[0] <= 0 or current_size[1] <= 0:
                raise ValueError(f"无法读取动画画布尺寸: {path}")
            if canvas is None:
                canvas = current_size
            elif current_size != canvas:
                raise ValueError(
                    f"动画帧画布不一致: {path} 是 {current_size}，预期 {canvas}"
                )
            frame_count += 1
    if canvas is None:
        raise ValueError("没有找到可验证的动画帧")
    return frame_count, canvas


def make_window(manifest: PetManifest):
    from action_controller import ActionController
    from interaction_policy import InteractionPolicy
    from PySide6.QtCore import QEvent, QPoint, QRect, QTimer, Qt
    from PySide6.QtGui import QActionGroup, QBitmap, QCursor, QImage, QPixmap
    from PySide6.QtGui import QRegion
    from PySide6.QtWidgets import QApplication, QLabel, QMenu, QWidget
    from snap_geometry import (
        Anchor,
        Rect,
        Surface,
        enumerate_windows,
        find_snap,
        find_support,
        native_monitor_rects,
        position_for_anchor,
    )

    class PetWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.manifest = manifest
            self.skin = manifest.default_skin
            self.display_size = DISPLAY_SIZE
            self.direction = "front"
            self.current_name = manifest.default_animation
            self.current_clip: Clip | None = None
            self.current_skin = self.skin
            self.current_mirror = False
            self.current_frames: list[QPixmap] = []
            self.current_body_region: QRegion | None = None
            self.effect_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
            self.current_effect: str | None = None
            self.current_effect_frames: list[QPixmap] = []
            self.current_effect_index = 0
            self.current_effect_region: QRegion | None = None
            self._pillow_effect_fired = False
            self.current_mode = "loop"
            self.current_index = 0
            self.smoke_timer_interval: int | None = None
            self.controller = ActionController(
                manifest.names, default_idle=manifest.default_animation
            )
            self.policy = InteractionPolicy(style="lively")
            self.raw_mode = False
            self.pixmap_cache: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
            self.play_history: list[str] = []
            self.press_position: QPoint | None = None
            self.window_position_at_press: QPoint | None = None
            self.is_dragging = False
            self.double_click_candidate = False
            self.menu_open = False
            self.last_hover_feedback_pos: QPoint | None = None
            self.double_click_interval = max(1, QApplication.doubleClickInterval())
            self.pending_click_event = "pet"
            self.drag_last_pos: QPoint | None = None
            self.drag_distance = 0.0
            self.drag_axis_sign = 0
            self.drag_reversals = 0
            self.snap_enabled = True
            self.snap_anchor: Anchor | None = None
            self.snap_reference_rect: Rect | None = None
            self.snap_surfaces: list[Surface] = []
            self._native_monitors = native_monitor_rects()
            self.capture_window = None
            self.capture_background = "green"

            self.setWindowTitle("DST 兔人桌宠")
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setMouseTracking(True)
            self.setFixedSize(self.display_size, self.display_size)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

            self.image_label = QLabel(self)
            self.image_label.setGeometry(0, 0, self.display_size, self.display_size)
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            self.effect_label = QLabel(self)
            self.effect_label.setGeometry(0, 0, self.display_size, self.display_size)
            self.effect_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.effect_label.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            self.effect_label.hide()

            self.timer = QTimer(self)
            self.timer.timeout.connect(self.advance_frame)
            self.effect_timer = QTimer(self)
            self.effect_timer.timeout.connect(self._advance_effect_frame)

            self.single_click_timer = QTimer(self)
            self.single_click_timer.setSingleShot(True)
            self.single_click_timer.timeout.connect(self._on_single_click)
            self.hover_timer = QTimer(self)
            self.hover_timer.setSingleShot(True)
            self.hover_timer.setInterval(350)
            self.hover_timer.timeout.connect(self._on_hover_dwell)
            self.policy_timer = QTimer(self)
            self.policy_timer.setInterval(400)
            self.policy_timer.timeout.connect(self._tick_policy)
            self.policy_timer.start()
            self.snap_timer = QTimer(self)
            self.snap_timer.setInterval(250)
            self.snap_timer.timeout.connect(self._update_snap)
            self._activate(self.controller.current.clip, self.controller.current.mode)

        def _load_segment(self, clip: Clip, skin_id: str) -> dict[str, Any]:
            key = (skin_id, clip.clip_id)
            if key in self.pixmap_cache:
                entry = self.pixmap_cache.pop(key)
                self.pixmap_cache[key] = entry
                return entry

            frames: list[QPixmap] = []
            for path in clip.frames[skin_id]:
                pixmap = QPixmap(str(path))
                if pixmap.isNull():
                    raise ValueError(f"无法加载动画帧: {path}")
                frames.append(
                    pixmap.scaled(
                        self.display_size,
                        self.display_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            entry = {"frames": frames, "regions": {}}
            self.pixmap_cache[key] = entry
            while len(self.pixmap_cache) > PIXMAP_CACHE_SEGMENTS:
                self.pixmap_cache.popitem(last=False)
            return entry

        def _alpha_region(self, pixmap: QPixmap, mirrored: bool) -> QRegion:
            """Build and cache a click mask from pixels whose alpha exceeds 8."""
            image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            width, height = image.width(), image.height()
            try:
                import numpy as np

                raw = np.frombuffer(image.constBits(), dtype=np.uint8)
                rgba = raw[: image.sizeInBytes()].reshape(
                    height, image.bytesPerLine()
                )[:, : width * 4].reshape(height, width, 4)
                # QBitmap interprets zero-valued pixels as the clickable mask.
                visible = np.where(rgba[:, :, 3] > 8, 0, 255).astype(np.uint8)
                if mirrored:
                    visible = visible[:, ::-1].copy()
                mask_image = QImage(
                    visible.data,
                    width,
                    height,
                    width,
                    QImage.Format.Format_Grayscale8,
                ).copy()
            except ImportError:
                raise RuntimeError("生成透明鼠标遮罩需要 NumPy")
            return QRegion(QBitmap.fromImage(mask_image))

        def _load_effect(self, effect_name: str) -> dict[str, Any]:
            if effect_name in self.effect_cache:
                entry = self.effect_cache.pop(effect_name)
                self.effect_cache[effect_name] = entry
                return entry
            definition = self.manifest.effects[effect_name]
            frames: list[QPixmap] = []
            for path in definition.frames:
                pixmap = QPixmap(str(path))
                if pixmap.isNull():
                    raise ValueError(f"无法加载特效帧: {path}")
                frames.append(
                    pixmap.scaled(
                        self.display_size,
                        self.display_size,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            entry = {"frames": frames, "regions": {}}
            self.effect_cache[effect_name] = entry
            while len(self.effect_cache) > 2:
                self.effect_cache.popitem(last=False)
            return entry

        def _effect_region(self, index: int) -> QRegion:
            if self.current_effect is None:
                return QRegion()
            entry = self.effect_cache.get(self.current_effect)
            if entry is None:
                return QRegion()
            key = (index, self.current_mirror)
            region = entry["regions"].get(key)
            if region is None:
                pixmap = self.current_effect_frames[index]
                region = self._alpha_region(pixmap, self.current_mirror)
                region.translate(
                    (self.display_size - pixmap.width()) // 2,
                    (self.display_size - pixmap.height()) // 2,
                )
                entry["regions"][key] = region
            return region

        def _apply_composite_mask(self) -> None:
            region = (
                self.current_body_region
                if self.current_body_region is not None
                else QRegion()
            )
            if self.current_effect is not None and self.current_effect_frames:
                region = region.united(self._effect_region(self.current_effect_index))
            if region.isEmpty():
                region = QRegion(0, 0, 1, 1)
            self.setMask(region)

        def _render_effect_frame(self) -> None:
            if self.current_effect is None or not self.current_effect_frames:
                self.effect_label.clear()
                self.effect_label.hide()
                self.current_effect_region = None
                self._apply_composite_mask()
                self._publish_capture_frame()
                return
            pixmap = self.current_effect_frames[self.current_effect_index]
            if self.current_mirror:
                pixmap = QPixmap.fromImage(pixmap.toImage().mirrored(True, False))
            self.effect_label.setPixmap(pixmap)
            self.effect_label.show()
            self.current_effect_region = self._effect_region(self.current_effect_index)
            self._apply_composite_mask()
            self._publish_capture_frame()

        def play_effect(self, effect_name: str) -> None:
            if effect_name not in self.manifest.effects:
                return
            self.effect_timer.stop()
            self.current_effect = effect_name
            entry = self._load_effect(effect_name)
            self.current_effect_frames = entry["frames"]
            self.current_effect_index = 0
            self._render_effect_frame()
            interval = self.smoke_timer_interval or max(
                1, round(1000 / self.manifest.effects[effect_name].fps)
            )
            if len(self.current_effect_frames) > 1:
                self.effect_timer.start(interval)

        def _advance_effect_frame(self) -> None:
            if self.current_effect is None:
                self.effect_timer.stop()
                return
            if self.current_effect_index + 1 >= len(self.current_effect_frames):
                self.effect_timer.stop()
                self.current_effect = None
                self.current_effect_frames = []
                self.current_effect_index = 0
                self._render_effect_frame()
                return
            self.current_effect_index += 1
            self._render_effect_frame()

        def _maybe_trigger_pillow_effect(self) -> None:
            if (
                self.current_name == "atk_object"
                and self.current_index >= 9
                and not self._pillow_effect_fired
                and "pillow" in self.manifest.effects
            ):
                self._pillow_effect_fired = True
                self.play_effect("pillow")

        def _activate(
            self,
            name: str,
            mode: str,
            frame_index: int = 0,
            preserve_effect: bool = False,
        ) -> None:
            previous_name = self.current_name
            clip, skin_id, mirror = choose_variant(
                self.manifest, name, self.direction, self.skin
            )
            self.current_name = name
            self.current_clip = clip
            self.current_skin = skin_id
            self.current_mirror = mirror
            cache_entry = self._load_segment(clip, skin_id)
            self.current_cache_key = (skin_id, clip.clip_id)
            self.current_frames = cache_entry["frames"]
            self.current_mode = mode
            self.current_index = min(frame_index, len(self.current_frames) - 1)
            if name == "atk_object" and (not preserve_effect or previous_name != name):
                self._pillow_effect_fired = False
            self.play_history.append(name)
            if len(self.play_history) > 1000:
                del self.play_history[:500]
            self._render_frame()
            self.timer.stop()
            if mode != "hold" or self.current_index < len(self.current_frames) - 1:
                interval = self.smoke_timer_interval or max(1, round(1000 / clip.fps))
                self.timer.start(interval)
            if not preserve_effect:
                if name in {"hit", "hit_big", "corpse_hit"}:
                    self.play_effect("hit")
                elif name == "frozen_loop_pst":
                    self.play_effect("thaw")
                self._maybe_trigger_pillow_effect()

        def _render_frame(self) -> None:
            pixmap = self.current_frames[self.current_index]
            cache_entry = self.pixmap_cache.get(self.current_cache_key)
            region_key = (self.current_index, self.current_mirror)
            if cache_entry is not None:
                region = cache_entry["regions"].get(region_key)
                if region is None:
                    region = self._alpha_region(pixmap, self.current_mirror)
                    region.translate(
                        (self.display_size - pixmap.width()) // 2,
                        (self.display_size - pixmap.height()) // 2,
                    )
                    if region.isEmpty():
                        region = QRegion(0, 0, 1, 1)
                    cache_entry["regions"][region_key] = region
                self.current_body_region = region
            if self.current_mirror:
                pixmap = QPixmap.fromImage(pixmap.toImage().mirrored(True, False))
            self.image_label.setPixmap(pixmap)
            if self.current_effect is not None:
                self._render_effect_frame()
            else:
                self._apply_composite_mask()
            if self._is_sleeping_pose():
                self._maintain_sleep_support()
            self._publish_capture_frame()

        def _capture_canvas(self) -> tuple[int, int]:
            if self.manifest.canvas is not None:
                return tuple(max(1, round(value)) for value in self.manifest.canvas)
            if self.current_clip is not None:
                paths = self.current_clip.frames.get(self.current_skin)
                if paths:
                    pixmap = QPixmap(str(paths[min(self.current_index, len(paths) - 1)]))
                    if not pixmap.isNull():
                        return pixmap.width(), pixmap.height()
            return self.display_size, self.display_size

        def _publish_capture_frame(self) -> None:
            capture = self.capture_window
            if capture is None or not capture.isVisible() or self.current_clip is None:
                return
            body_paths = self.current_clip.frames.get(self.current_skin)
            if not body_paths:
                return
            body_path = body_paths[min(self.current_index, len(body_paths) - 1)]
            effect_path = None
            if self.current_effect is not None:
                effect = self.manifest.effects.get(self.current_effect)
                if effect is not None and effect.frames:
                    effect_path = effect.frames[
                        min(self.current_effect_index, len(effect.frames) - 1)
                    ]
            capture.set_frame_paths(body_path, effect_path, self.current_mirror)

        def toggle_capture_window(self, enabled: bool) -> None:
            if not enabled:
                if self.capture_window is not None:
                    self.capture_window.hide()
                return
            if self.capture_window is None:
                from capture_window import CaptureWindow

                capture = CaptureWindow(
                    canvas=self._capture_canvas(),
                    icon=QApplication.windowIcon(),
                )
                self.capture_window = capture
                capture.destroyed.connect(
                    lambda *_args, owner=self, target=capture: setattr(
                        owner, "capture_window", None
                    )
                    if owner.capture_window is target
                    else None
                )
                capture.set_background(self.capture_background)
            self.capture_window.showNormal()
            self.capture_window.raise_()
            self._publish_capture_frame()

        def set_capture_background(self, color: str) -> None:
            if color not in {"green", "blue", "magenta"}:
                return
            self.capture_background = color
            if self.capture_window is not None:
                self.capture_window.set_background(color)

        def _body_visible_rect(self) -> Rect:
            region = self.current_body_region
            bounds = region.boundingRect() if region is not None else QRect()
            return Rect(
                float(bounds.x()),
                float(bounds.y()),
                float(bounds.x() + bounds.width()),
                float(bounds.y() + bounds.height()),
            )

        def _map_native_rect(self, rect: Rect) -> Rect:
            center_x, center_y = rect.center_x, rect.center_y
            for screen in QApplication.screens():
                native = self._native_monitors.get(screen.name())
                if native is None or not native.contains(center_x, center_y):
                    continue
                logical = screen.geometry()
                if native.width <= 0 or native.height <= 0:
                    break
                scale_x = logical.width() / native.width
                scale_y = logical.height() / native.height
                return Rect(
                    logical.x() + (rect.left - native.left) * scale_x,
                    logical.y() + (rect.top - native.top) * scale_y,
                    logical.x() + (rect.right - native.left) * scale_x,
                    logical.y() + (rect.bottom - native.top) * scale_y,
                )
            return rect

        def _collect_snap_surfaces(self) -> list[Surface]:
            windows = enumerate_windows(
                exclude_handle=int(self.winId()),
                coordinate_mapper=self._map_native_rect,
            )
            screens = []
            for screen in QApplication.screens():
                available = screen.availableGeometry()
                rect = Rect(
                    float(available.x()),
                    float(available.y()),
                    float(available.x() + available.width()),
                    float(available.y() + available.height()),
                )
                screens.append(Surface(f"screen:{screen.name()}", rect, "screen"))
            self.snap_surfaces = [*windows, *screens]
            return self.snap_surfaces

        def _surface_for_anchor(self, surfaces: list[Surface]) -> Surface | None:
            if self.snap_anchor is None:
                return None
            return next(
                (surface for surface in surfaces if surface.id == self.snap_anchor.surface_id),
                None,
            )

        def _window_on_screen(self) -> bool:
            visible = self._body_visible_rect().translated(self.x(), self.y())
            return any(
                visible.right > screen.geometry().x()
                and visible.left < screen.geometry().x() + screen.geometry().width()
                and visible.bottom > screen.geometry().y()
                and visible.top < screen.geometry().y() + screen.geometry().height()
                for screen in QApplication.screens()
            )

        def _detach_snap(self) -> None:
            self.snap_anchor = None
            self.snap_reference_rect = None

        def set_snap_enabled(self, enabled: bool) -> None:
            self.snap_enabled = bool(enabled)
            if not self.snap_enabled:
                self.snap_timer.stop()
                self._detach_snap()
            elif self.isVisible():
                self.snap_timer.start()
                self._update_snap()

        def _is_sleeping_pose(self) -> bool:
            return self.current_name in {"sleep_pre", "sleep_loop", "sleep_pst"}

        def _classify_click(self, global_position: QPoint) -> str:
            local = self.mapFromGlobal(global_position)
            bounds = self.current_body_region.boundingRect()
            if bounds.height() <= 0:
                return "pet"
            relative_y = (local.y() - bounds.top()) / bounds.height()
            if relative_y < 0.30:
                return "ear_touch"
            if relative_y >= 0.70:
                return "belly_touch"
            return "pet"

        def _record_drag_motion(self, position: QPoint) -> None:
            if self.drag_last_pos is None:
                self.drag_last_pos = position
                return
            delta = position - self.drag_last_pos
            dx, dy = delta.x(), delta.y()
            distance = (dx * dx + dy * dy) ** 0.5
            self.drag_last_pos = position
            if distance < 8:
                return
            self.drag_distance += distance
            dominant = dx if abs(dx) >= abs(dy) else dy
            direction = 1 if dominant > 0 else -1
            if self.drag_axis_sign and direction != self.drag_axis_sign:
                self.drag_reversals += 1
            self.drag_axis_sign = direction

        def _is_shake_gesture(self) -> bool:
            return self.drag_distance >= 180 and self.drag_reversals >= 2

        def _try_snap_to_surface(self, surfaces: list[Surface]) -> bool:
            result = find_snap(
                (self.x(), self.y()),
                self._body_visible_rect(),
                surfaces,
                threshold=24,
            )
            if result is None:
                return False
            position, anchor = result
            self.snap_anchor = anchor
            self.snap_reference_rect = self._body_visible_rect()
            self.move(*position)
            return True

        def _maintain_sleep_support(self) -> None:
            if not self.snap_enabled or not self.isVisible() or self.isMinimized():
                return
            if self.is_dragging or self.press_position is not None:
                return
            if not self._window_on_screen():
                self._detach_snap()
                return
            surfaces = self.snap_surfaces or self._collect_snap_surfaces()
            surface = self._surface_for_anchor(surfaces)
            if surface is not None:
                support_side = (
                    "bottom" if surface.kind == "screen" else "top"
                )
                if self.snap_anchor.side != support_side:
                    self._detach_snap()
                    surface = None
            if surface is None:
                self._detach_snap()
                support = find_support(
                    (self.x(), self.y()), self._body_visible_rect(), surfaces
                )
                if support is None:
                    return
                position, anchor = support
                self.snap_anchor = anchor
                surface = self._surface_for_anchor(surfaces)
                self.snap_reference_rect = self._body_visible_rect()
            if surface is not None and self.snap_anchor is not None:
                position = position_for_anchor(
                    self.snap_anchor, surface, self._body_visible_rect()
                )
                if position != (self.x(), self.y()):
                    self.move(*position)

        def _update_snap(self) -> None:
            if not self.snap_enabled or not self.isVisible() or self.isMinimized():
                return
            if self.is_dragging or self.press_position is not None:
                return
            if not self._window_on_screen():
                self._detach_snap()
                return
            surfaces = self._collect_snap_surfaces()
            surface = self._surface_for_anchor(surfaces)
            if self.snap_anchor is not None and surface is None:
                self._detach_snap()
            if self._is_sleeping_pose():
                self._maintain_sleep_support()
                return
            if self.snap_anchor is not None:
                if self._controller_is_idle():
                    reference = self._body_visible_rect()
                    self.snap_reference_rect = reference
                else:
                    reference = self.snap_reference_rect or self._body_visible_rect()
                surface = self._surface_for_anchor(surfaces)
                if surface is not None:
                    position = position_for_anchor(self.snap_anchor, surface, reference)
                    if position != (self.x(), self.y()):
                        self.move(*position)
                return
            if (
                self._controller_is_idle()
                and self.controller.pending_action is None
            ):
                self._try_snap_to_surface(surfaces)

        def showEvent(self, event) -> None:  # noqa: N802 - Qt event name
            super().showEvent(event)
            if self.snap_enabled:
                self.snap_timer.start()
                QTimer.singleShot(0, self._update_snap)

        def hideEvent(self, event) -> None:  # noqa: N802 - Qt event name
            self.snap_timer.stop()
            self._detach_snap()
            super().hideEvent(event)

        def changeEvent(self, event) -> None:  # noqa: N802 - Qt event name
            if event.type() == QEvent.Type.WindowStateChange:
                if self.isMinimized():
                    self.snap_timer.stop()
                    self._detach_snap()
                elif self.isVisible() and self.snap_enabled:
                    self.snap_timer.start()
                    QTimer.singleShot(0, self._update_snap)
            super().changeEvent(event)

        def closeEvent(self, event) -> None:  # noqa: N802 - Qt event name
            self.snap_timer.stop()
            self._detach_snap()
            if self.capture_window is not None:
                self.capture_window.close()
            super().closeEvent(event)

        def _has_name(self, name: str) -> bool:
            return any(clip.name == name for clip in self.manifest.clips.values())

        def request_action(self, action_id: str, user_initiated: bool = True) -> None:
            """Request a complete action from the controller, preserving clip sequences."""
            if user_initiated:
                self.policy.note_user_activity()
                self.single_click_timer.stop()
                self.hover_timer.stop()
                self.double_click_candidate = False
            if self.raw_mode:
                controller = ActionController(
                    self.manifest.names,
                    default_idle=self.manifest.default_animation,
                    initial_clip=self.current_name,
                )
                if action_id not in controller.actions:
                    return
                self.controller = controller
                self.raw_mode = False

            if action_id not in self.controller.actions:
                return
            step = self.controller.request(action_id)
            if step is not None:
                self._activate(step.clip, step.mode)

        def _controller_is_idle(self) -> bool:
            return (
                self.controller.active_action == "idle"
                and self.current_name == self.manifest.default_animation
                and self.current_mode == "loop"
            )

        def _policy_is_blocked(self) -> bool:
            return (
                self.is_dragging
                or self.menu_open
                or self.raw_mode
                or self.press_position is not None
                or self.double_click_candidate
                or self.single_click_timer.isActive()
                or self.hover_timer.isActive()
            )

        def _tick_policy(self) -> None:
            reaction = self.policy.tick(
                idle=self._controller_is_idle(),
                active_action=self.controller.active_action,
                pending=self.controller.pending_action is not None,
                blocked=self._policy_is_blocked(),
            )
            self._dispatch_reaction(reaction)

        def _dispatch_reaction(self, reaction) -> None:
            if reaction is None:
                return
            if reaction.action:
                # react() already recorded human events. Automatic actions must
                # preserve the policy's automatic nap ownership.
                self.request_action(reaction.action, user_initiated=False)

        def _user_reaction(self, event: str) -> None:
            if event != "pet":
                self.single_click_timer.stop()
                self.hover_timer.stop()
                self.double_click_candidate = False
            self._dispatch_reaction(self.policy.react(event))

        def _on_single_click(self) -> None:
            event = self.pending_click_event
            self.pending_click_event = "pet"
            self._user_reaction(event)

        def _on_hover_dwell(self) -> None:
            if self._controller_is_idle() and not self._policy_is_blocked():
                self.last_hover_feedback_pos = QCursor.pos()
                self._user_reaction("hover")

        def _schedule_hover(self) -> None:
            pointer = QCursor.pos()
            if self.last_hover_feedback_pos is not None:
                delta = pointer - self.last_hover_feedback_pos
                if delta.x() * delta.x() + delta.y() * delta.y() <= 9:
                    return
            if (
                self._controller_is_idle()
                and not self.raw_mode
                and not self.menu_open
                and not self.is_dragging
                and self.press_position is None
                and not self.single_click_timer.isActive()
            ):
                self.hover_timer.start(350)

        def enterEvent(self, event) -> None:  # noqa: N802 - Qt event name
            self._schedule_hover()
            super().enterEvent(event)

        def leaveEvent(self, event) -> None:  # noqa: N802 - Qt event name
            self.hover_timer.stop()
            super().leaveEvent(event)

        def preview_clip(self, name: str) -> None:
            """Play one raw manifest clip directly, bypassing action transitions."""
            if not self._has_name(name):
                return
            self.policy.note_user_activity()
            self.hover_timer.stop()
            self.raw_mode = True
            if name == "corpse" or name == "frozen":
                mode = "hold"
            elif name == self.manifest.default_animation or name.endswith("_loop"):
                mode = "loop"
            else:
                mode = "once"
            self._activate(name, mode)

        def return_to_idle(self) -> None:
            self.request_action("idle")

        def advance_frame(self) -> None:
            if not self.current_frames:
                return
            if self.current_mode == "loop":
                next_index = (self.current_index + 1) % len(self.current_frames)
                if next_index == 0 and not self.raw_mode:
                    step = self.controller.finish_clip()
                    if step is not None:
                        self._activate(step.clip, step.mode)
                        return
                self.current_index = next_index
                self._render_frame()
                self._maybe_trigger_pillow_effect()
                return
            if self.current_index + 1 < len(self.current_frames):
                self.current_index += 1
                self._render_frame()
                self._maybe_trigger_pillow_effect()
                if self.current_mode == "hold" and self.current_index + 1 == len(self.current_frames):
                    self.timer.stop()
                return
            if self.current_mode == "hold":
                self.timer.stop()
                return
            if self.raw_mode:
                self._activate(self.manifest.default_animation, "loop")
                return
            step = self.controller.finish_clip()
            if step is not None:
                self._activate(step.clip, step.mode)

        def _refresh_current_variant(self) -> None:
            if self.current_clip is None:
                return
            name = self.current_name
            mode = self.current_mode
            index = self.current_index
            self._activate(name, mode, index, preserve_effect=True)

        def set_skin(self, skin: str) -> None:
            if skin not in self.manifest.skins:
                return
            if skin != self.skin:
                self.policy.note_user_activity()
            self.skin = skin
            self._refresh_current_variant()

        def set_direction(self, direction: str) -> None:
            if direction not in {"front", "left", "right", "back"}:
                return
            if direction != self.direction:
                self.policy.note_user_activity()
            self.direction = direction
            self._refresh_current_variant()

        def set_display_size(self, size: int) -> None:
            if size not in {360, 520, 680} or size == self.display_size:
                return
            self.policy.note_user_activity()
            name, mode, index = (
                self.current_name,
                self.current_mode,
                self.current_index,
            )
            effect_name = self.current_effect
            effect_index = self.current_effect_index
            self.display_size = size
            self.setFixedSize(size, size)
            self.image_label.setGeometry(0, 0, size, size)
            self.effect_label.setGeometry(0, 0, size, size)
            self.pixmap_cache.clear()
            self.effect_cache.clear()
            if effect_name in self.manifest.effects:
                entry = self._load_effect(effect_name)
                self.current_effect_frames = entry["frames"]
                self.current_effect_index = min(
                    effect_index, len(self.current_effect_frames) - 1
                )
            self._activate(name, mode, index, preserve_effect=True)

        def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt event name
            if event.button() == Qt.MouseButton.LeftButton:
                self.hover_timer.stop()
                if self.single_click_timer.isActive():
                    self.single_click_timer.stop()
                    # Qt sends mouseDoubleClickEvent only when both timing and
                    # distance match the platform's double-click rules. A plain
                    # second press is a separate tap; commit the first one now.
                    self._on_single_click()
                self.double_click_candidate = False
                self.press_position = event.globalPosition().toPoint()
                self.window_position_at_press = self.frameGeometry().topLeft()
                self.drag_last_pos = self.press_position
                self.drag_distance = 0.0
                self.drag_axis_sign = 0
                self.drag_reversals = 0
                self.is_dragging = False
                event.accept()
                return
            if event.button() == Qt.MouseButton.RightButton:
                self.show_context_menu(event.globalPosition().toPoint())
                event.accept()
                return
            super().mousePressEvent(event)

        def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt event name
            if event.button() == Qt.MouseButton.LeftButton:
                self.hover_timer.stop()
                self.single_click_timer.stop()
                self.double_click_candidate = True
                self.press_position = event.globalPosition().toPoint()
                self.window_position_at_press = self.frameGeometry().topLeft()
                self.drag_last_pos = self.press_position
                self.drag_distance = 0.0
                self.drag_axis_sign = 0
                self.drag_reversals = 0
                self.is_dragging = False
                event.accept()
                return
            super().mouseDoubleClickEvent(event)

        def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt event name
            if (
                self.press_position is not None
                and self.window_position_at_press is not None
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                delta = event.globalPosition().toPoint() - self.press_position
                if (
                    not self.is_dragging
                    and delta.x() * delta.x() + delta.y() * delta.y()
                    >= CLICK_DRAG_THRESHOLD * CLICK_DRAG_THRESHOLD
                ):
                    self.is_dragging = True
                    self._detach_snap()
                if self.is_dragging:
                    self._record_drag_motion(event.globalPosition().toPoint())
                    self.hover_timer.stop()
                    self.move(self.window_position_at_press + delta)
                event.accept()
                return
            if not event.buttons():
                self._schedule_hover()
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt event name
            if event.button() == Qt.MouseButton.LeftButton:
                clicked = False
                if self.press_position is not None:
                    delta = event.globalPosition().toPoint() - self.press_position
                    distance_squared = delta.x() * delta.x() + delta.y() * delta.y()
                    if distance_squared >= CLICK_DRAG_THRESHOLD * CLICK_DRAG_THRESHOLD:
                        self.is_dragging = True
                    if self.is_dragging:
                        self._record_drag_motion(event.globalPosition().toPoint())
                    clicked = not self.is_dragging and distance_squared < (
                        CLICK_DRAG_THRESHOLD * CLICK_DRAG_THRESHOLD
                    )
                self.press_position = None
                self.window_position_at_press = None
                is_double_click = self.double_click_candidate
                was_dragging = self.is_dragging
                was_shake = was_dragging and self._is_shake_gesture()
                self.double_click_candidate = False
                self.is_dragging = False
                self.drag_last_pos = None
                if was_dragging:
                    if self.snap_enabled and self.isVisible() and self._window_on_screen():
                        self._try_snap_to_surface(self._collect_snap_surfaces())
                    self._user_reaction("shake" if was_shake else "drop")
                elif is_double_click and clicked:
                    self._user_reaction("double_click")
                elif clicked:
                    self.pending_click_event = self._classify_click(
                        event.globalPosition().toPoint()
                    )
                    self.single_click_timer.start(self.double_click_interval)
                event.accept()
                return
            super().mouseReleaseEvent(event)

        def show_context_menu(self, position: QPoint) -> None:
            self.menu_open = True
            self.single_click_timer.stop()
            self.hover_timer.stop()
            menu = QMenu(self)

            feed_action = menu.addAction("喂胡萝卜")
            feed_action.triggered.connect(lambda: self._user_reaction("feed"))

            capture_action = menu.addAction("直播采集窗口")
            capture_action.setCheckable(True)
            capture_action.setChecked(
                self.capture_window is not None and self.capture_window.isVisible()
            )
            capture_action.toggled.connect(self.toggle_capture_window)

            background_menu = menu.addMenu("采集背景")
            background_group = QActionGroup(background_menu)
            background_group.setExclusive(True)
            selected_background = (
                self.capture_window.background_key
                if self.capture_window is not None
                else self.capture_background
            )
            for color, label in (
                ("green", "绿幕"),
                ("blue", "蓝幕"),
                ("magenta", "品红幕"),
            ):
                background_action = background_menu.addAction(label)
                background_action.setCheckable(True)
                background_action.setChecked(color == selected_background)
                background_group.addAction(background_action)
                background_action.triggered.connect(
                    lambda _checked=False, chosen=color: self.set_capture_background(chosen)
                )
            menu.addSeparator()

            auto_action = menu.addAction("自动活动")
            auto_action.setCheckable(True)
            auto_action.setChecked(self.policy.enabled)
            auto_action.triggered.connect(self.policy.set_enabled)

            style_menu = menu.addMenu("陪伴节奏")
            style_group = QActionGroup(style_menu)
            style_group.setExclusive(True)
            for style, label in (("lively", "活泼亲人"), ("quiet", "安静陪伴")):
                style_action = style_menu.addAction(label)
                style_action.setCheckable(True)
                style_action.setChecked(self.policy.style == style)
                style_group.addAction(style_action)
                style_action.triggered.connect(
                    lambda _checked=False, selected=style: self.policy.set_style(selected)
                )
            snap_action = menu.addAction("吸附到窗口和屏幕边缘")
            snap_action.setCheckable(True)
            snap_action.setChecked(self.snap_enabled)
            snap_action.triggered.connect(self.set_snap_enabled)
            menu.addSeparator()

            appearance_menu = menu.addMenu("外观")
            for skin_id, label in self.manifest.skins.items():
                action = appearance_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(skin_id == self.skin)
                action.triggered.connect(
                    lambda _checked=False, selected_skin=skin_id: self.set_skin(
                        selected_skin
                    )
                )

            size_menu = menu.addMenu("窗口大小")
            for size in (360, 520, 680):
                action = size_menu.addAction(f"{size} 像素")
                action.setCheckable(True)
                action.setChecked(size == self.display_size)
                action.triggered.connect(
                    lambda _checked=False, selected_size=size: self.set_display_size(
                        selected_size
                    )
                )

            developer_menu = menu.addMenu("开发预览")
            categories = developer_menu.addMenu("完整动作（测试）")
            by_group: dict[str, list[tuple[str, Any]]] = {}
            for action_id, spec in self.controller.actions.items():
                if action_id.startswith("_"):
                    continue
                group = str(getattr(spec, "group", "其他"))
                by_group.setdefault(group, []).append((action_id, spec))
            for group, action_specs in by_group.items():
                group_label = GROUP_LABELS.get(group.casefold(), group)
                group_menu = categories.addMenu(group_label)
                label_counts: dict[str, int] = {}
                for _action_id, spec in action_specs:
                    label = str(getattr(spec, "label", "动作"))
                    label_counts[label] = label_counts.get(label, 0) + 1
                for action_id, spec in action_specs:
                    label = str(getattr(spec, "label", action_id))
                    if label_counts[label] > 1:
                        label = f"{label}（{action_id}）"
                    action = group_menu.addAction(label)
                    action.setCheckable(True)
                    action.setChecked(action_id == self.controller.active_action)
                    action.triggered.connect(
                        lambda _checked=False, selected=action_id: self.request_action(selected)
                    )

            all_menu = developer_menu.addMenu("原始片段（跳过动作衔接）")
            all_by_group: dict[str, list[str]] = {}
            for name in self.manifest.names:
                group = self.manifest.group_for(name)
                all_by_group.setdefault(group, []).append(name)
            for group, names in all_by_group.items():
                group_menu = all_menu.addMenu(GROUP_LABELS.get(group.casefold(), group))
                for name in names:
                    label = self.manifest.label_for(name)
                    action = group_menu.addAction(f"{label}（{name}）")
                    action.triggered.connect(
                        lambda _checked=False, selected=name: self.preview_clip(selected)
                    )

            direction_menu = developer_menu.addMenu("朝向")
            direction_labels = {
                "front": "正面", "left": "左侧", "right": "右侧", "back": "背面"
            }
            for direction, label in direction_labels.items():
                action = direction_menu.addAction(label)
                action.setCheckable(True)
                action.setChecked(direction == self.direction)
                action.triggered.connect(
                    lambda _checked=False, selected=direction: self.set_direction(selected)
                )

            menu.addSeparator()
            idle_action = developer_menu.addAction("回到待机")
            idle_action.triggered.connect(self.return_to_idle)
            quit_action = menu.addAction("退出")
            quit_action.triggered.connect(self.close)
            try:
                menu.exec(position)
            finally:
                self.menu_open = False

        def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt event name
            if event.key() == Qt.Key.Key_Escape:
                self.close()
                event.accept()
                return
            if event.key() == Qt.Key.Key_F:
                self._user_reaction("feed")
                event.accept()
                return
            super().keyPressEvent(event)

        def wheelEvent(self, event) -> None:  # noqa: N802 - Qt event name
            delta = event.angleDelta().y()
            notches = min(3, abs(delta) // 120)
            if notches:
                action = "wheel_down" if delta < 0 else "wheel_up"
                for _ in range(notches):
                    self._user_reaction(action)
                event.accept()
                return
            super().wheelEvent(event)

    return PetWindow()


def _mouse_event(button, buttons, position):
    from PySide6.QtCore import QPointF

    class MouseEvent:
        def __init__(self) -> None:
            self._button = button
            self._buttons = buttons
            self._position = QPointF(position)

        def button(self):
            return self._button

        def buttons(self):
            return self._buttons

        def globalPosition(self):
            return self._position

        def accept(self):
            pass

    return MouseEvent()


def _key_event(key):
    class KeyEvent:
        def key(self):
            return key

        def accept(self):
            pass

    return KeyEvent()


def run_smoke_test(app, window, manifest: PetManifest, frame_count: int, canvas) -> int:
    """Exercise controller flows, raw previews, input, rendering, and cache bounds."""
    from action_controller import ActionController
    from interaction_policy import InteractionPolicy
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtGui import QImage
    from snap_geometry import Anchor, Rect, Surface

    import numpy as np
    import random

    names = set(manifest.names)
    if not {"idle_loop", "idle_happy"} <= names:
        raise ValueError("smoke test 需要 idle_loop 和 idle_happy")
    if not {"idle", "happy"} <= set(window.controller.actions):
        raise ValueError("controller 缺少待机或开心完整动作")

    window.smoke_timer_interval = 1
    window.timer.setInterval(1)
    window.policy_timer.stop()
    window.policy.set_enabled(False)
    window.double_click_interval = 1
    window.snap_timer.stop()
    window.snap_enabled = False
    window.show()
    app.processEvents()
    window.snap_timer.stop()

    # The mask follows visible alpha and excludes transparent pixels.
    sample_pixmap = window.current_frames[window.current_index]
    rgba_image = sample_pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    rgba = np.frombuffer(rgba_image.constBits(), dtype=np.uint8)[
        : rgba_image.sizeInBytes()
    ].reshape(rgba_image.height(), rgba_image.bytesPerLine())[
        :, : rgba_image.width() * 4
    ].reshape(rgba_image.height(), rgba_image.width(), 4)
    opaque_pixels = np.argwhere(rgba[:, :, 3] > 200)
    transparent_pixels = np.argwhere(rgba[:, :, 3] <= 8)
    if not len(opaque_pixels) or not len(transparent_pixels):
        raise AssertionError("无法在当前帧中找到透明与不透明像素")
    offset_x = (window.display_size - sample_pixmap.width()) // 2
    offset_y = (window.display_size - sample_pixmap.height()) // 2
    opaque_y, opaque_x = opaque_pixels[len(opaque_pixels) // 2]
    transparent_y, transparent_x = transparent_pixels[0]
    mask = window.mask()
    if not mask.contains(QPoint(int(opaque_x + offset_x), int(opaque_y + offset_y))):
        raise AssertionError("不透明像素没有包含在鼠标遮罩中")
    if mask.contains(
        QPoint(int(transparent_x + offset_x), int(transparent_y + offset_y))
    ):
        raise AssertionError("透明像素仍被鼠标遮罩拦截")

    # Effect pixels extend the click mask without making transparent corners opaque.
    if {"hit", "thaw", "pillow"} <= set(manifest.effects):
        original_body = window.current_frames[window.current_index].toImage().convertToFormat(
            QImage.Format.Format_RGBA8888
        )
        window._activate("hit", "once")
        if window.current_effect != "hit":
            raise AssertionError("受击动画没有触发命中特效")
        effect_pixmap = window.current_effect_frames[window.current_effect_index]
        effect_image = effect_pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        effect_rgba = np.frombuffer(effect_image.constBits(), dtype=np.uint8)[
            : effect_image.sizeInBytes()
        ].reshape(effect_image.height(), effect_image.bytesPerLine())[
            :, : effect_image.width() * 4
        ].reshape(effect_image.height(), effect_image.width(), 4)
        effect_opaque = np.argwhere(effect_rgba[:, :, 3] > 200)
        effect_transparent = np.argwhere(
            (effect_rgba[:, :, 3] <= 8)
            & (np.asarray(original_body.constBits(), dtype=np.uint8)[
                : original_body.sizeInBytes()
            ].reshape(original_body.height(), original_body.bytesPerLine())[
                :, : original_body.width() * 4
            ].reshape(original_body.height(), original_body.width(), 4)[:, :, 3] <= 8)
        )
        if not len(effect_opaque) or not len(effect_transparent):
            raise AssertionError("受击特效没有可验证的透明与不透明区域")
        effect_y, effect_x = effect_opaque[len(effect_opaque) // 2]
        blank_y, blank_x = effect_transparent[0]
        effect_offset_x = (window.display_size - effect_pixmap.width()) // 2
        effect_offset_y = (window.display_size - effect_pixmap.height()) // 2
        effect_mask = window.mask()
        if not effect_mask.contains(
            QPoint(int(effect_x + effect_offset_x), int(effect_y + effect_offset_y))
        ):
            raise AssertionError("特效可见像素没有包含在窗口遮罩中")
        if effect_mask.contains(
            QPoint(int(blank_x + effect_offset_x), int(blank_y + effect_offset_y))
        ):
            raise AssertionError("身体和特效都透明的像素被鼠标遮罩拦截")
        for clip_name, effect_name, start_index in (
            ("frozen_loop_pst", "thaw", 0),
            ("atk_object", "pillow", 9),
        ):
            if not window._has_name(clip_name):
                continue
            window._activate(clip_name, "once", start_index)
            if window.current_effect != effect_name:
                raise AssertionError(f"{clip_name} 没有触发 {effect_name} 特效")
            window.effect_timer.stop()
            window.current_effect = None
            window.current_effect_frames = []
            window._render_effect_frame()
        window.controller = ActionController(
            manifest.names, default_idle=manifest.default_animation
        )
        window._activate(window.controller.current.clip, window.controller.current.mode)

    # The optional capture window mirrors source paths without inheriting the
    # desktop pet's size, transparency, mask, or movement.
    window.toggle_capture_window(True)
    capture = window.capture_window
    if capture is None or not capture.isVisible():
        raise AssertionError("直播采集窗口没有显示")
    if (
        capture.windowFlags() & Qt.WindowType.WindowType_Mask
    ) != Qt.WindowType.Window:
        raise AssertionError("采集窗口被标记为 Tool，无法稳定单独采集")
    if capture.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground):
        raise AssertionError("采集窗口背景不是不透明画布")
    if capture.minimumSize() != capture.maximumSize():
        raise AssertionError("采集窗口没有固定画布尺寸")

    captured_paths: list[tuple[Path, Path | None, bool]] = []
    original_set_frame_paths = capture.set_frame_paths

    def record_capture_frame(body_path: Path, effect_path: Path | None, mirror: bool):
        captured_paths.append((body_path, effect_path, mirror))
        original_set_frame_paths(body_path, effect_path, mirror)

    capture.set_frame_paths = record_capture_frame

    def expected_capture_body() -> Path:
        paths = window.current_clip.frames[window.current_skin]
        return paths[min(window.current_index, len(paths) - 1)]

    window._publish_capture_frame()
    if not captured_paths or captured_paths[-1][0] != expected_capture_body():
        raise AssertionError("采集窗口没有接收当前角色源帧路径")
    capture_size = capture.size()
    original_size = window.display_size
    original_skin = window.skin
    original_direction = window.direction
    alternate_skin = next(
        (skin_id for skin_id in manifest.skins if skin_id != original_skin),
        original_skin,
    )
    window.set_skin(alternate_skin)
    if captured_paths[-1][0] != expected_capture_body():
        raise AssertionError("切换外观没有同步到采集窗口")
    window.set_direction("left")
    if (
        captured_paths[-1][0] != expected_capture_body()
        or captured_paths[-1][2] != window.current_mirror
    ):
        raise AssertionError("切换朝向没有同步源帧或镜像状态")
    window.set_display_size(360 if original_size != 360 else 680)
    if capture.size() != capture_size:
        raise AssertionError("调整桌宠大小改变了采集画布尺寸")
    window.set_display_size(original_size)
    window.set_direction(original_direction)
    window.set_skin(original_skin)
    if capture.size() != capture_size:
        raise AssertionError("恢复桌宠大小改变了采集画布尺寸")

    for clip_name, effect_name, start_index in (
        ("hit", "hit", 0),
        ("frozen_loop_pst", "thaw", 0),
        ("atk_object", "pillow", 9),
    ):
        if effect_name not in manifest.effects or not window._has_name(clip_name):
            continue
        window._activate(clip_name, "once", start_index)
        if (
            window.current_effect != effect_name
            or captured_paths[-1][1] != manifest.effects[effect_name].frames[0]
        ):
            raise AssertionError(f"{effect_name} 特效没有同步到采集窗口")
        while window.current_effect is not None:
            window._advance_effect_frame()
        if captured_paths[-1][1] is not None:
            raise AssertionError(f"{effect_name} 特效结束后没有清除采集层")
    window.controller = ActionController(
        manifest.names, default_idle=manifest.default_animation
    )
    window._activate(window.controller.current.clip, window.controller.current.mode)

    window.set_capture_background("blue")
    if capture.background_key != "blue":
        raise AssertionError("采集背景选项没有传给采集窗口")
    window.toggle_capture_window(False)
    if capture.isVisible():
        raise AssertionError("菜单关闭采集窗后它仍然可见")
    window.toggle_capture_window(True)
    capture = window.capture_window
    if capture is None or not capture.isVisible():
        raise AssertionError("采集窗口隐藏后无法重新打开")
    capture.close()
    app.processEvents()
    if not window.isVisible():
        raise AssertionError("关闭采集副窗时意外关闭了桌宠主窗")
    window.toggle_capture_window(True)

    # Sleep docking always chooses a floor, and drag input temporarily owns position.
    smoke_screen = Surface("screen:smoke", Rect(-1000, -1000, 2000, 1200), "screen")
    window.snap_enabled = True
    window.snap_surfaces = [smoke_screen]
    window.current_name = "sleep_loop"
    window.snap_anchor = Anchor(smoke_screen.id, "left", 0.5)
    window.move(80, 80)
    window.is_dragging = True
    window.press_position = QPoint(10, 10)
    before_drag = window.pos()
    window._maintain_sleep_support()
    window._update_snap()
    if window.pos() != before_drag or window.snap_anchor.side != "left":
        raise AssertionError("拖动期间吸附逻辑抢走了窗口位置")
    window.is_dragging = False
    window.press_position = None
    window._maintain_sleep_support()
    if window.snap_anchor.side != "bottom":
        raise AssertionError("睡觉时没有从侧边吸附转换为下方支撑面")
    window.current_name = manifest.default_animation
    window.snap_enabled = False
    window.snap_surfaces = []
    window.snap_anchor = None

    # Click regions and wheel-notch routing feed the policy's discovery events.
    body_bounds = window.current_body_region.boundingRect()
    top_touch = window.mapToGlobal(QPoint(body_bounds.center().x(), body_bounds.top() + 1))
    belly_touch = window.mapToGlobal(QPoint(body_bounds.center().x(), body_bounds.bottom() - 1))
    if (
        window._classify_click(top_touch) != "ear_touch"
        or window._classify_click(belly_touch) != "belly_touch"
    ):
        raise AssertionError("可见身体的耳朵/肚子点击区域没有正确分类")
    routed_events: list[str] = []
    original_user_reaction = window._user_reaction
    window._user_reaction = routed_events.append

    class WheelEvent:
        def angleDelta(self):
            return QPoint(0, -360)

        def accept(self):
            pass

    window.wheelEvent(WheelEvent())
    window._user_reaction = original_user_reaction
    if routed_events != ["wheel_down"] * 3:
        raise AssertionError("滚轮没有按三格下滚拆成三个发现事件")
    routed_events.clear()
    window._user_reaction = routed_events.append
    window.press_position = QPoint(0, 0)
    window.window_position_at_press = window.frameGeometry().topLeft()
    window.drag_last_pos = QPoint(0, 0)
    window.drag_distance = 0.0
    window.drag_axis_sign = 0
    window.drag_reversals = 0
    window.is_dragging = True
    for point in (QPoint(110, 0), QPoint(0, 0), QPoint(110, 0)):
        window._record_drag_motion(point)
    window.mouseReleaseEvent(
        _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, QPoint(110, 0))
    )
    window._user_reaction = original_user_reaction
    if routed_events != ["shake"]:
        raise AssertionError("长距离往返拖动没有识别为摇晃")
    window.current_name = manifest.default_animation

    # Verify every raw logical clip resolves in every skin and facing.
    for name in manifest.names:
        for skin in manifest.skins:
            for direction in ("front", "left", "right", "back"):
                clip, skin_id, mirror = choose_variant(manifest, name, direction, skin)
                if not clip.frames.get(skin_id):
                    raise AssertionError(f"动作 {name} 无法解析外观 {skin}")
                if mirror != (direction == "left" and clip.facing == "5"):
                    raise AssertionError(f"动作 {name} 的侧面镜像选择不正确")

    # Every advertised complete action must refer to clips in the manifest.
    for action_id, spec in window.controller.actions.items():
        if action_id.startswith("_"):
            continue
        for step in spec.steps + spec.exit_steps:
            if step.clip not in names:
                raise AssertionError(
                    f"完整动作 {action_id} 引用了不存在的原始片段 {step.clip}"
                )

    # Loading more clips than the LRU capacity must remain bounded.
    for name in manifest.names[: PIXMAP_CACHE_SEGMENTS + 2]:
        clip, skin_id, _mirror = choose_variant(
            manifest, name, "front", manifest.default_skin
        )
        window._load_segment(clip, skin_id)
    if len(window.pixmap_cache) > PIXMAP_CACHE_SEGMENTS:
        raise AssertionError("帧缓存超过 8 个动画片段")

    has_raw_sleep_exit = all(
        name in names for name in ("sleep_loop", "sleep_pst")
    )
    has_raw_spawn_exit = all(
        name in names for name in ("spawn_pre", "spawn_loop", "spawn_pst")
    )
    raw_recovery_kind = None
    if has_raw_sleep_exit:
        raw_recovery_kind = "sleep"
        window.preview_clip("sleep_loop")
        if (
            not window.raw_mode
            or window.current_name != "sleep_loop"
            or window.current_mode != "loop"
        ):
            raise AssertionError("原始片段预览没有直接循环 sleep_loop")
        window.request_action("idle")
        if window.raw_mode or window.current_name != "sleep_loop":
            raise AssertionError("切回完整动作时没有恢复原始睡眠状态")
    elif has_raw_spawn_exit:
        raw_recovery_kind = "spawn"
        window.preview_clip("spawn_pre")
        if not window.raw_mode or window.current_name != "spawn_pre":
            raise AssertionError("原始片段预览没有直接播放 spawn_pre")
        window.preview_clip("spawn_loop")
        if (
            not window.raw_mode
            or window.current_name != "spawn_loop"
            or window.current_mode != "loop"
        ):
            raise AssertionError("原始片段预览没有直接循环 spawn_loop")
        window.request_action("idle")
        if window.raw_mode or window.current_name != "spawn_loop":
            raise AssertionError("切回完整动作时没有恢复原始片段的流程状态")
    else:
        window.controller = ActionController(
            manifest.names, default_idle=manifest.default_animation
        )
        window.raw_mode = False
        window._activate(window.controller.current.clip, window.controller.current.mode)

    result = {"code": 1, "done": False}
    timeout = QTimer()
    timeout.setSingleShot(True)

    def fail(message: str) -> None:
        if result["done"]:
            return
        result["done"] = True
        result["code"] = 1
        print(f"smoke test FAILED: {message}")
        app.exit(1)

    def finish() -> None:
        if result["done"]:
            return
        capture = window.capture_window
        window.close()
        if window.isVisible() or (capture is not None and capture.isVisible()):
            fail("关闭桌宠主窗时没有同时关闭采集副窗")
            return
        result["done"] = True
        result["code"] = 0
        action_count = sum(
            not action_id.startswith("_")
            for action_id in window.controller.actions
        )
        print(
            f"smoke test OK: {len(manifest.clips)} clips, {len(manifest.names)} names, "
            f"{action_count} complete actions, {frame_count} animation/effect frames at "
            f"{canvas[0]}x{canvas[1]}; controller flows, raw preview, "
            "skin/direction, click/double-click/hover/feed/drop, ear/belly taps, "
            "wheel/shake, manual sleep, floor docking, capture-window sync/lifecycle, "
            "effect mask, and 8-clip LRU verified"
        )
        app.quit()

    def wait_until(predicate, callback, message: str) -> None:
        def check() -> None:
            if result["done"]:
                return
            try:
                ready = predicate()
            except Exception as exc:
                fail(f"{message}: {exc}")
                return
            if ready:
                callback()
                return
            QTimer.singleShot(2, check)

        check()

    idle_ready = lambda: (
        window.controller.active_action == "idle"
        and window.current_name == manifest.default_animation
        and window.current_mode == "loop"
    )

    def gesture_point(x_offset: int = 0, y_fraction: float = 0.5) -> QPoint:
        bounds = window.mask().boundingRect()
        return window.mapToGlobal(
            QPoint(
                bounds.center().x() + x_offset,
                bounds.top() + round(bounds.height() * y_fraction),
            )
        )

    def exercise_input() -> None:
        # Dragging responds on release, and crossing the threshold never becomes a click.
        window.mousePressEvent(
            _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, QPoint(100, 100))
        )
        window.mouseMoveEvent(
            _mouse_event(Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, QPoint(108, 100))
        )
        window.mouseMoveEvent(
            _mouse_event(Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, QPoint(101, 100))
        )
        window.mouseReleaseEvent(
            _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, QPoint(101, 100))
        )
        if window.controller.active_action not in {"happy", "earrub"}:
            fail("拖动放下没有触发回应动作")
            return
        def test_boundary_drop() -> None:
            # Exactly five pixels crosses the threshold and remains a drop, not a click.
            events: list[str] = []
            original_reaction = window._user_reaction
            window._user_reaction = events.append
            window.mousePressEvent(
                _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, QPoint(100, 100))
            )
            window.mouseReleaseEvent(
                _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, QPoint(103, 104))
            )
            window._user_reaction = original_reaction
            if events != ["drop"]:
                fail(f"5 像素边界没有作为拖动放下处理：{events}")
                return

            # A second press within the OS double-click interval cancels the pending pet.
            start = len(window.play_history)
            point = gesture_point()
            window.mousePressEvent(
                _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, point)
            )
            window.mouseReleaseEvent(
                _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, point)
            )
            if not window.single_click_timer.isActive():
                fail("单击没有等待双击识别窗口")
                return
            window.mouseDoubleClickEvent(
                _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, point)
            )
            window.mouseReleaseEvent(
                _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, point)
            )
            if (
                window.controller.active_action != "dance"
                or "idle_happy" in window.play_history[start:]
            ):
                fail("双击没有只触发跳舞，或先误发了单击摸摸")
                return
            wait_until(
                idle_ready,
                test_distinct_fast_taps,
                "双击跳舞没有回到待机",
            )

        wait_until(idle_ready, test_boundary_drop, "放下回应没有回到待机")

    def test_distinct_fast_taps() -> None:
        # A normal press at a different position is not Qt's double-click event.
        start = len(window.play_history)
        first = gesture_point(-20)
        second = gesture_point(20)
        window.mousePressEvent(
            _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, first)
        )
        window.mouseReleaseEvent(
            _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, first)
        )
        window.mousePressEvent(
            _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, second)
        )
        if window.single_click_timer.isActive():
            fail("第二次普通点击没有提交前一个单击")
            return
        window.mouseReleaseEvent(
            _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, second)
        )
        if (
            window.controller.active_action != "happy"
            or "dance" in window.play_history[start:]
        ):
            fail("不同位置的快速单击被误判成双击")
            return
        if not window.single_click_timer.isActive():
            fail("第二个普通单击没有启动独立的识别计时")
            return

        def after_taps() -> None:
            # Let the pet cooldown expire before testing another single click.
            QTimer.singleShot(800, begin_single_click)

        wait_until(idle_ready, after_taps, "快速单击回应没有回到待机")

    def begin_single_click() -> None:
        start = len(window.play_history)
        point = gesture_point()
        window.mousePressEvent(
            _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, point)
        )
        window.mouseReleaseEvent(
            _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, point)
        )
        if window.controller.active_action != "idle":
            fail("延迟单击在双击窗口结束前提前触发")
            return

        def verify_single_click() -> None:
            if (
                window.controller.active_action != "happy"
                or window.current_name != "idle_happy"
                or window.current_mode != "once"
                or "idle_happy" not in window.play_history[start:]
            ):
                fail("单击摸摸没有在双击窗口后启动一次开心动作")
                return

            # Skin and facing refresh the renderer without resetting controller progress.
            window.current_index = min(1, len(window.current_frames) - 1)
            saved_index = window.current_index
            saved_current = window.controller.current
            alternate_skin = next(
                (skin for skin in manifest.skins if skin != window.skin), window.skin
            )
            window.set_skin(alternate_skin)
            if (
                window.controller.active_action != "happy"
                or window.controller.current != saved_current
                or window.current_index != saved_index
            ):
                fail("切换外观重置了动作流程或播放进度")
                return
            window.set_direction("left")
            if (
                window.controller.active_action != "happy"
                or window.controller.current != saved_current
                or window.current_index != saved_index
            ):
                fail("切换朝向重置了动作流程或播放进度")
                return
            window.set_direction("front")
            window.set_skin(manifest.default_skin)
            wait_until(idle_ready, test_hover_dwell, "单击摸摸没有回到待机")

        wait_until(
            lambda: window.controller.active_action == "happy",
            verify_single_click,
            "延迟单击没有触发摸摸回应",
        )

    def test_hover_dwell() -> None:
        window.last_hover_feedback_pos = None
        window._schedule_hover()
        if not window.hover_timer.isActive():
            fail("静止靠近没有启动 350 毫秒停留计时")
            return

        def verify_hover() -> None:
            if (
                window.controller.active_action != "happy"
            ):
                fail("靠近停留没有触发动作回应")
                return
            window._schedule_hover()
            if window.hover_timer.isActive():
                fail("鼠标未移动时重复触发了靠近计时")
                return
            wait_until(idle_ready, test_feed_key, "靠近回应没有回到待机")

        wait_until(
            lambda: window.controller.active_action == "happy",
            verify_hover,
            "350 毫秒停留后没有触发靠近回应",
        )

    def test_feed_key() -> None:
        # An explicit feed should cancel a pending single-click gesture.
        point = gesture_point()
        window.mousePressEvent(
            _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, point)
        )
        window.mouseReleaseEvent(
            _mouse_event(Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, point)
        )
        if not window.single_click_timer.isActive():
            fail("喂食优先级测试没有启动待判单击")
            return
        window.keyPressEvent(_key_event(Qt.Key.Key_F))
        if window.single_click_timer.isActive():
            fail("F 键喂食没有取消待判单击")
            return
        if window.controller.active_action != "eat" or window.current_name not in {
            "eat",
            "eat_carrot",
        }:
            fail("F 键没有喂食并播放吃东西动作")
            return
        first_feed_history_size = len(window.play_history)
        window.keyPressEvent(_key_event(Qt.Key.Key_F))
        if (
            window.controller.active_action != "eat"
            or len(window.play_history) != first_feed_history_size
        ):
            fail("喂食冷却期间重复启动了吃东西动作")
            return
        wait_until(idle_ready, exercise_sleep, "吃东西动作没有回到待机")

    def exercise_sleep() -> None:
        if "sleep" not in window.controller.actions:
            exercise_dig()
            return
        start = len(window.play_history)
        window.request_action("sleep")
        if window.current_name != "sleep_pre":
            fail("选择睡觉没有进入睡前动作")
            return

        def verify_sleep() -> None:
            expected = [
                "sleep_pre",
                "sleep_loop",
                "sleep_pst",
                manifest.default_animation,
            ]
            history = window.play_history[start:]
            found = any(
                history[index : index + len(expected)] == expected
                for index in range(len(history) - len(expected) + 1)
            )
            if not found:
                fail("睡觉流程缺少醒来阶段或顺序错误")
                return
            exercise_latest_target()

        def wait_for_sleep_loop() -> None:
            if window.current_name == "sleep_loop" and window.current_mode == "loop":
                window.request_action("idle")
                wait_until(idle_ready, verify_sleep, "睡觉没有醒来并回待机")
                return
            QTimer.singleShot(2, wait_for_sleep_loop)

        QTimer.singleShot(2, wait_for_sleep_loop)

    def exercise_latest_target() -> None:
        if not {"sleep", "walk", "dance"} <= set(window.controller.actions):
            exercise_dig()
            return
        start = len(window.play_history)
        window.request_action("sleep")
        if window.current_name != "sleep_pre":
            fail("测试连续选择时没有进入睡前动作")
            return

        def verify_latest_target() -> None:
            history = window.play_history[start:]
            expected = [
                "sleep_pre",
                "sleep_loop",
                "sleep_pst",
                "dance",
                manifest.default_animation,
            ]
            found = any(
                history[index : index + len(expected)] == expected
                for index in range(len(history) - len(expected) + 1)
            )
            if not found or "walk_pre" in history:
                fail("连续选择没有保留最后目标，或跳过了睡醒收尾")
                return
            exercise_dig()

        def wait_for_sleep_loop() -> None:
            if window.current_name == "sleep_loop" and window.current_mode == "loop":
                window.request_action("walk")
                window.request_action("dance")
                if window.controller.pending_action != "dance":
                    fail("连续选择没有把最新目标保留为跳舞")
                    return
                wait_until(
                    idle_ready,
                    verify_latest_target,
                    "中断睡觉后没有醒来并播放最后选择的动作",
                )
                return
            QTimer.singleShot(2, wait_for_sleep_loop)

        QTimer.singleShot(2, wait_for_sleep_loop)

    def exercise_dig() -> None:
        if "dig" not in window.controller.actions:
            exercise_manual_sleep()
            return
        start = len(window.play_history)
        window.request_action("dig")
        if window.current_name != "despawn":
            fail("选择钻地没有进入退场/钻地阶段")
            return

        def verify_dig() -> None:
            expected = [
                "despawn",
                "spawn_pre",
                "spawn_loop",
                "spawn_pst",
                manifest.default_animation,
            ]
            history = window.play_history[start:]
            found = any(
                history[index : index + len(expected)] == expected
                for index in range(len(history) - len(expected) + 1)
            )
            if not found:
                fail("钻地流程缺少钻出阶段或片段顺序错误")
                return
            exercise_manual_sleep()

        def wait_for_spawn_loop() -> None:
            if window.current_name == "spawn_loop":
                window.request_action("idle")
                wait_until(idle_ready, verify_dig, "钻地动作没有钻出并回待机")
                return
            QTimer.singleShot(2, wait_for_spawn_loop)

        QTimer.singleShot(2, wait_for_spawn_loop)

    def exercise_manual_sleep() -> None:
        if "sleep" not in window.controller.actions or "wake" not in window.controller.actions:
            finish()
            return

        class FakeClock:
            now = 0.0

            def __call__(self):
                return self.now

        fake_clock = FakeClock()
        original_policy = window.policy
        manual_policy = InteractionPolicy(
            style="lively", clock=fake_clock, rng=random.Random(0)
        )
        window.policy = manual_policy
        window._user_reaction("sleep")
        if (
            window.controller.active_action != "sleep"
            or manual_policy.auto_sleep_started is not None
        ):
            fail("手动睡觉没有保留手动睡眠归属")
            window.policy = original_policy
            return

        def restore_policy_and_finish() -> None:
            window.policy = original_policy
            finish()

        def verify_manual_sleep() -> None:
            if window.current_name != "sleep_loop":
                fail("手动睡觉没有进入循环阶段")
                window.policy = original_policy
                return
            fake_clock.now += 1000
            window._tick_policy()
            if (
                window.controller.active_action != "sleep"
                or window.controller.pending_action is not None
                or manual_policy.auto_sleep_started is not None
            ):
                fail("自动活动错误地唤醒了手动睡眠")
                window.policy = original_policy
                return
            window._user_reaction("wake")
            wait_until(
                idle_ready,
                restore_policy_and_finish,
                "手动唤醒没有回到待机",
            )

        wait_until(
            lambda: window.current_name == "sleep_loop",
            verify_manual_sleep,
            "手动睡觉没有进入循环阶段",
        )

    def verify_raw_recovery_then_input() -> None:
        history = window.play_history
        if raw_recovery_kind == "sleep":
            expected = ["sleep_loop", "sleep_pst", manifest.default_animation]
        else:
            expected = ["spawn_loop", "spawn_pst", manifest.default_animation]
        found = any(
            history[index : index + len(expected)] == expected
            for index in range(len(history) - len(expected) + 1)
        )
        if not found:
            fail("原始片段切回完整动作时没有完成对应收尾阶段")
            return
        if raw_recovery_kind == "sleep" and has_raw_spawn_exit:
            raw_spawn_start = len(window.play_history)
            window.preview_clip("spawn_pre")
            window.preview_clip("spawn_loop")
            window.request_action("idle")
            if window.raw_mode:
                fail("钻地原始预览没有切回动作控制器")
                return

            def verify_raw_spawn() -> None:
                raw_history = window.play_history[raw_spawn_start:]
                expected_spawn = [
                    "spawn_loop",
                    "spawn_pst",
                    manifest.default_animation,
                ]
                if not any(
                    raw_history[index : index + len(expected_spawn)] == expected_spawn
                    for index in range(len(raw_history) - len(expected_spawn) + 1)
                ):
                    fail("原始钻地片段切回完整动作时跳过了钻出阶段")
                    return
                exercise_input()

            wait_until(
                idle_ready,
                verify_raw_spawn,
                "原始钻地片段没有钻出并回待机",
            )
            return
        exercise_input()

    timeout.timeout.connect(lambda: fail("等待动作流程完成超时"))
    timeout.start(30000)

    if raw_recovery_kind is not None:
        wait_until(
            idle_ready,
            verify_raw_recovery_then_input,
            "原始片段切回动作后没有完成钻出",
        )
    else:
        wait_until(idle_ready, exercise_input, "桌宠没有进入初始待机")

    if window.current_mode != "hold":
        window.timer.start(1)
    app.exec()
    timeout.stop()
    return result["code"]

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DST 兔人动画桌宠")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="动画清单路径（默认从程序数据目录读取）",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="动画资源目录（预期包含 manifest.json 与 frames/）",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="使用 Qt offscreen 验证动画资源和播放逻辑，然后退出",
    )
    args = parser.parse_args(argv)
    if args.smoke_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QIcon

        app = QApplication([sys.argv[0]])
        app.setQuitOnLastWindowClosed(True)
        if args.manifest is not None:
            manifest_path = args.manifest
        else:
            if args.data_dir is not None:
                data_dir = args.data_dir
            elif getattr(sys, "frozen", False):
                data_dir = Path(sys.executable).resolve().parent
            else:
                data_dir = Path(__file__).resolve().parent
            manifest_path = data_dir / "manifest.json"
        manifest = load_manifest(manifest_path)
        icon_path = manifest.path.parent / "app.ico"
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
        window = make_window(manifest)
        if args.smoke_test:
            frame_count, canvas = validate_manifest_frames(manifest)
            for name in manifest.names:
                for direction in ("front", "left", "right", "back"):
                    choose_variant(manifest, name, direction, manifest.default_skin)
            return run_smoke_test(app, window, manifest, frame_count, canvas)

        screen = app.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            body = window._body_visible_rect()
            desired_center_x = available.x() + available.width() - 160
            desired_bottom_y = available.y() + available.height() - 12
            window.move(
                round(desired_center_x - body.center_x),
                round(desired_bottom_y - body.bottom),
            )
        window.show()
        return app.exec()
    except Exception as exc:
        print(f"桌宠启动失败: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
