"""E-commerce Modular Cabinet Combiner, 3D Room Scene Builder, and Matrix Batch Renderer.

Compiles multi-unit modular cabinets and user-authored 3D room layouts directly into
the canonical `FURNISHED_SCENE_V1` contract consumed by `scripts/blender_job.py` and
`scripts/furnished_scene.py`.
"""
from __future__ import annotations

import io
import json
import math
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fox3d.ids import new_id, stable_hash
from fox3d.photoreal_assets import (
    AI_STYLE_PRESETS,
    POLYHAVEN_CURATED_MODELS,
    build_ai_photoreal_composite,
    ensure_pbr_texture_assets,
    ensure_polyhaven_models,
)
from fox3d.recipe_3d import atomic_json, read_json
from fox3d.recipe_workbench import timestamp


def hex_to_rgb(hex_str: str, default: tuple[float, float, float] = (0.75, 0.70, 0.62)) -> list[float]:
    s = str(hex_str or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return list(default)
    try:
        return [round(int(s[0:2], 16) / 255.0, 4), round(int(s[2:4], 16) / 255.0, 4), round(int(s[4:6], 16) / 255.0, 4)]
    except ValueError:
        return list(default)


STYLE_THEMES: dict[str, dict[str, Any]] = {
    "THEME_NORDIC_OAK": {
        "id": "THEME_NORDIC_OAK",
        "label": "北歐原木 × 暖白門片",
        "carcassHex": "#c89d66",
        "backHex": "#f3efe6",
        "doorPaletteHex": ["#f7f4ee", "#e8dfd1", "#f7f4ee"],
        "drawerHex": "#ede5d8",
    },
    "THEME_MORANDI_SAGE": {
        "id": "THEME_MORANDI_SAGE",
        "label": "莫蘭迪鼠尾草綠 × 淺橡木",
        "carcassHex": "#d2b48c",
        "backHex": "#eef2ee",
        "doorPaletteHex": ["#7d9685", "#f4f1ea", "#5f7a69"],
        "drawerHex": "#d8e0d9",
    },
    "THEME_JAPANDI_LATTE": {
        "id": "THEME_JAPANDI_LATTE",
        "label": "日系太妃奶茶 × 亞麻米白",
        "carcassHex": "#b88b5a",
        "backHex": "#f5efe6",
        "doorPaletteHex": ["#d8c3a5", "#f6f2eb", "#c4a77d"],
        "drawerHex": "#e6d7c3",
    },
    "THEME_MISTY_BLUE": {
        "id": "THEME_MISTY_BLUE",
        "label": "北歐迷霧藍 × 晨霧白",
        "carcassHex": "#cbb08a",
        "backHex": "#edf2f6",
        "doorPaletteHex": ["#6d8ea0", "#f4f6f8", "#4d6d80"],
        "drawerHex": "#dce5ec",
    },
    "THEME_BLUSH_KIDS": {
        "id": "THEME_BLUSH_KIDS",
        "label": "馬卡龍櫻花粉 × 奶油黃",
        "carcassHex": "#e5c99f",
        "backHex": "#fffaf0",
        "doorPaletteHex": ["#e8a598", "#f9e498", "#9ec5ab"],
        "drawerHex": "#fce8e4",
    },
    "THEME_WALNUT_LUXE": {
        "id": "THEME_WALNUT_LUXE",
        "label": "現代胡桃深木 × 霧黑石墨",
        "carcassHex": "#6e472b",
        "backHex": "#3d2b1f",
        "doorPaletteHex": ["#2f3438", "#4a4e52", "#2f3438"],
        "drawerHex": "#3b4045",
    },
}

CABINET_PRESETS: list[dict[str, Any]] = [
    {
        "id": "MOD_SINGLE_3TIER",
        "label": "經典單座三層櫃 (424×295×900mm)",
        "description": "標準電商熱銷單座三層門櫃，適合擺放於任何角落。",
        "depthMm": 295,
        "panelMm": 15,
        "backMm": 3,
        "doorMm": 15,
        "gapMm": 2,
        "themeId": "THEME_NORDIC_OAK",
        "columns": [
            {
                "widthMm": 424,
                "heightMm": 900,
                "rows": 3,
                "cells": [{"mode": "DOOR"}, {"mode": "DOOR"}, {"mode": "DOOR"}],
            }
        ],
    },
    {
        "id": "MOD_DOUBLE_6GRID",
        "label": "雙併六格對開組合櫃 (848×295×900mm)",
        "description": "兩座三層櫃左右無縫並排，雙倍收納容量，適合客廳與臥室。",
        "depthMm": 295,
        "panelMm": 15,
        "backMm": 3,
        "doorMm": 15,
        "gapMm": 2,
        "themeId": "THEME_MORANDI_SAGE",
        "columns": [
            {
                "widthMm": 424,
                "heightMm": 900,
                "rows": 3,
                "cells": [{"mode": "DOOR"}, {"mode": "OPEN"}, {"mode": "DOOR"}],
            },
            {
                "widthMm": 424,
                "heightMm": 900,
                "rows": 3,
                "cells": [{"mode": "OPEN"}, {"mode": "DOOR"}, {"mode": "DOOR"}],
            },
        ],
    },
    {
        "id": "MOD_TRIPLE_MIX_9GRID",
        "label": "三併九格展示收納牆 (1272×295×900mm)",
        "description": "三欄九格黃金比例，結合門片防塵、開放展示格與底層抽屜。",
        "depthMm": 295,
        "panelMm": 15,
        "backMm": 3,
        "doorMm": 15,
        "gapMm": 2,
        "themeId": "THEME_JAPANDI_LATTE",
        "columns": [
            {
                "widthMm": 424,
                "heightMm": 900,
                "rows": 3,
                "cells": [{"mode": "DOOR"}, {"mode": "OPEN"}, {"mode": "DOOR"}],
            },
            {
                "widthMm": 424,
                "heightMm": 900,
                "rows": 3,
                "cells": [{"mode": "DRAWER"}, {"mode": "OPEN"}, {"mode": "OPEN"}],
            },
            {
                "widthMm": 424,
                "heightMm": 900,
                "rows": 3,
                "cells": [{"mode": "DOOR"}, {"mode": "OPEN"}, {"mode": "DOOR"}],
            },
        ],
    },
    {
        "id": "MOD_STEP_STAIR_3COL",
        "label": "步步高升階梯組合櫃 (1272×295×300~900mm)",
        "description": "一格矮櫃＋二格中櫃＋三格高櫃階梯造型，兒童房與窗邊最愛。",
        "depthMm": 295,
        "panelMm": 15,
        "backMm": 3,
        "doorMm": 15,
        "gapMm": 2,
        "themeId": "THEME_BLUSH_KIDS",
        "columns": [
            {
                "widthMm": 424,
                "heightMm": 300,
                "rows": 1,
                "cells": [{"mode": "DRAWER"}],
            },
            {
                "widthMm": 424,
                "heightMm": 600,
                "rows": 2,
                "cells": [{"mode": "DOOR"}, {"mode": "OPEN"}],
            },
            {
                "widthMm": 424,
                "heightMm": 900,
                "rows": 3,
                "cells": [{"mode": "DOOR"}, {"mode": "DOOR"}, {"mode": "OPEN"}],
            },
        ],
    },
    {
        "id": "MOD_FOYER_BENCH_COMBO",
        "label": "玄關穿鞋矮櫃＋高櫃組 (848×295×450/900mm)",
        "description": "左側 450mm 穿鞋矮櫃搭配右側 900mm 三層鞋物收納櫃。",
        "depthMm": 295,
        "panelMm": 15,
        "backMm": 3,
        "doorMm": 15,
        "gapMm": 2,
        "themeId": "THEME_MISTY_BLUE",
        "columns": [
            {
                "widthMm": 424,
                "heightMm": 450,
                "rows": 1,
                "cells": [{"mode": "DOOR"}],
            },
            {
                "widthMm": 424,
                "heightMm": 900,
                "rows": 3,
                "cells": [{"mode": "DOOR"}, {"mode": "OPEN"}, {"mode": "DOOR"}],
            },
        ],
    },
]

PROP_CATALOG: list[dict[str, Any]] = [
    {"type": "SOFA", "label": "🛋️ 雙人沙發", "widthM": 1.75, "depthM": 0.78, "heightM": 0.78, "colorHex": "#2b5b56", "accentColorHex": "#5a3821"},
    {"type": "COFFEE_TABLE", "label": "☕ 木質茶几", "widthM": 1.0, "depthM": 0.60, "heightM": 0.44, "colorHex": "#8a5a36", "accentColorHex": "#4a301c"},
    {"type": "RUG", "label": "🧶 編織地毯", "widthM": 2.2, "depthM": 1.5, "heightM": 0.015, "colorHex": "#dfd6c7", "accentColorHex": "#c7baa5"},
    {"type": "FLOOR_LAMP", "label": "💡 北歐立燈", "widthM": 0.38, "depthM": 0.38, "heightM": 1.55, "colorHex": "#e6c786", "accentColorHex": "#332c23"},
    {"type": "WALL_ART", "label": "🖼️ 牆面掛畫", "widthM": 0.75, "depthM": 0.05, "heightM": 0.85, "colorHex": "#b56c3a", "accentColorHex": "#5b381d", "defaultZ": 1.45},
    {"type": "PLANT", "label": "🪴 室內植栽", "widthM": 0.42, "depthM": 0.42, "heightM": 0.95, "colorHex": "#2e6b47", "accentColorHex": "#c87d55"},
    {"type": "BED", "label": "🛏️ 雙人床組", "widthM": 1.65, "depthM": 2.0, "heightM": 0.92, "colorHex": "#e8e2d5", "accentColorHex": "#7c5836"},
    {"type": "DESK", "label": "🖥️ 工作書桌", "widthM": 1.35, "depthM": 0.65, "heightM": 0.75, "colorHex": "#9c6b3f", "accentColorHex": "#2c2f33"},
    {"type": "BENCH", "label": "🪑 穿鞋長凳", "widthM": 0.95, "depthM": 0.38, "heightM": 0.45, "colorHex": "#a67545", "accentColorHex": "#d8cfc2"},
    {"type": "KITCHEN_COUNTER", "label": "🍽️ 餐廚流理台", "widthM": 2.2, "depthM": 0.65, "heightM": 0.88, "colorHex": "#3d5a54", "accentColorHex": "#ded6c6"},
    {"type": "WINDOW_FRAME", "label": "🪟 採光落地窗", "widthM": 1.4, "depthM": 0.06, "heightM": 1.6, "colorHex": "#eef6ff", "accentColorHex": "#f4f1ea", "defaultZ": 0.65},
    {"type": "SHEER_CURTAIN", "label": "🎐 透光亞麻落地紗簾", "widthM": 0.85, "depthM": 0.14, "heightM": 2.65, "colorHex": "#f5f1e8", "accentColorHex": "#d8cfc2"},
    {"type": "CUSTOM_BOX", "label": "📦 自訂裝飾台 / 外部 GLB", "widthM": 0.6, "depthM": 0.4, "heightM": 0.5, "colorHex": "#c4b6a6", "accentColorHex": "#8c7a6b"},
]

LIGHTING_PRESETS: dict[str, dict[str, Any]] = {
    "WARM_SUNLIGHT": {
        "label": "☀️ 午後暖陽窗光",
        "worldColor": [0.76, 0.79, 0.84],
        "worldStrength": 0.24,
        "keyColor": [1.0, 0.92, 0.80],
        "keyEnergy": 220.0,
        "fillColor": [0.82, 0.90, 1.0],
        "fillEnergy": 85.0,
    },
    "NORDIC_BRIGHT": {
        "label": "🌤️ 北歐明亮自然光",
        "worldColor": [0.84, 0.87, 0.91],
        "worldStrength": 0.30,
        "keyColor": [0.98, 0.97, 0.95],
        "keyEnergy": 250.0,
        "fillColor": [0.88, 0.93, 1.0],
        "fillEnergy": 105.0,
    },
    "COZY_EVENING": {
        "label": "🕯️ 溫馨居家暖黃光",
        "worldColor": [0.58, 0.54, 0.60],
        "worldStrength": 0.18,
        "keyColor": [1.0, 0.84, 0.64],
        "keyEnergy": 195.0,
        "fillColor": [0.95, 0.82, 0.72],
        "fillEnergy": 68.0,
    },
    "STUDIO_CLEAN": {
        "label": "📸 商業型錄高對比棚光",
        "worldColor": [0.88, 0.88, 0.90],
        "worldStrength": 0.32,
        "keyColor": [1.0, 0.99, 0.97],
        "keyEnergy": 265.0,
        "fillColor": [0.92, 0.95, 1.0],
        "fillEnergy": 115.0,
    },
}

CAMERA_VIEWS: dict[str, dict[str, Any]] = {
    "THREE_QUARTER": {"id": "THREE_QUARTER", "label": "右前 45° 黃金主圖", "side": 0.58, "distMult": 2.45, "elev": 0.34, "lens": 46.0},
    "LEFT": {"id": "LEFT", "label": "左前 45° 空間視角", "side": -0.58, "distMult": 2.45, "elev": 0.34, "lens": 46.0},
    "FRONT": {"id": "FRONT", "label": "正面平視型錄圖", "side": 0.0, "distMult": 2.30, "elev": 0.24, "lens": 50.0},
    "WIDE": {"id": "WIDE", "label": "廣角房間全景圖", "side": 0.42, "distMult": 3.25, "elev": 0.42, "lens": 35.0},
    "CLOSEUP": {"id": "CLOSEUP", "label": "櫃體細節近景圖", "side": 0.35, "distMult": 1.65, "elev": 0.22, "lens": 58.0},
}

BUILTIN_SCENES: list[dict[str, Any]] = [
    {
        "id": "SCENE_NORDIC_LIVING",
        "name": "北歐採光客廳（沙發＋茶几＋立燈）",
        "category": "客廳空間",
        "builtin": True,
        "roomWidthM": 5.6,
        "roomDepthM": 4.2,
        "roomHeightM": 3.0,
        "wallColorHex": "#b8ab96",
        "sideWallColorHex": "#a3a89c",
        "floorColorHex": "#78583a",
        "lightingPreset": "WARM_SUNLIGHT",
        "productPose": {"x": 0.15, "y": 1.15, "z": 0.0, "rotationDeg": 0.0},
        "props": [
            {"id": "p_sofa", "type": "SOFA", "label": "雙人沙發", "x": -1.45, "y": 1.05, "z": 0.0, "widthM": 1.75, "depthM": 0.76, "heightM": 0.78, "rotationDeg": 0, "colorHex": "#26534e", "accentColorHex": "#664024"},
            {"id": "p_rug", "type": "RUG", "label": "客廳編織毯", "x": -0.65, "y": 0.35, "z": 0.0, "widthM": 2.6, "depthM": 1.6, "heightM": 0.015, "rotationDeg": 0, "colorHex": "#e2d9c8", "accentColorHex": "#cabba4"},
            {"id": "p_table", "type": "COFFEE_TABLE", "label": "原木茶几", "x": -1.35, "y": -0.05, "z": 0.0, "widthM": 0.98, "depthM": 0.58, "heightM": 0.43, "rotationDeg": 0, "colorHex": "#7b4c29", "accentColorHex": "#4d2f18"},
            {"id": "p_lamp", "type": "FLOOR_LAMP", "label": "北歐立燈", "x": 1.55, "y": 1.15, "z": 0.0, "widthM": 0.38, "depthM": 0.38, "heightM": 1.52, "rotationDeg": 0, "colorHex": "#dec183", "accentColorHex": "#332a22"},
            {"id": "p_art", "type": "WALL_ART", "label": "抽象掛畫", "x": -1.45, "y": 1.52, "z": 1.45, "widthM": 0.78, "depthM": 0.05, "heightM": 0.85, "rotationDeg": 0, "colorHex": "#b56935", "accentColorHex": "#5c361a"},
            {"id": "p_plant", "type": "PLANT", "label": "琴葉榕盆栽", "x": 1.18, "y": 1.10, "z": 0.0, "widthM": 0.42, "depthM": 0.42, "heightM": 0.92, "rotationDeg": 0, "colorHex": "#2f6b48", "accentColorHex": "#c27a52"},
            {"id": "p_curtain", "type": "SHEER_CURTAIN", "label": "透光落地紗簾", "x": -2.35, "y": 1.46, "z": 0.0, "widthM": 0.76, "depthM": 0.14, "heightM": 2.85, "rotationDeg": 0, "colorHex": "#f4efe6", "accentColorHex": "#d8cfc2"},
        ],
    },
    {
        "id": "SCENE_JAPANDI_BEDROOM",
        "name": "日系原木臥室（床頭收納櫃情境）",
        "category": "臥室空間",
        "builtin": True,
        "roomWidthM": 5.2,
        "roomDepthM": 4.0,
        "roomHeightM": 2.9,
        "wallColorHex": "#cfc5b4",
        "sideWallColorHex": "#bfb4a2",
        "floorColorHex": "#8c6744",
        "lightingPreset": "COZY_EVENING",
        "productPose": {"x": 0.45, "y": 1.12, "z": 0.0, "rotationDeg": 0.0},
        "props": [
            {"id": "p_bed", "type": "BED", "label": "日系雙人床", "x": -1.25, "y": 0.62, "z": 0.0, "widthM": 1.62, "depthM": 1.95, "heightM": 0.88, "rotationDeg": 0, "colorHex": "#ede6da", "accentColorHex": "#7d5636"},
            {"id": "p_rug", "type": "RUG", "label": "亞麻床邊毯", "x": -0.4, "y": 0.25, "z": 0.0, "widthM": 2.4, "depthM": 1.5, "heightM": 0.015, "rotationDeg": 0, "colorHex": "#e7dfd1", "accentColorHex": "#cfc2ae"},
            {"id": "p_lamp", "type": "FLOOR_LAMP", "label": "暖光立燈", "x": 1.48, "y": 1.10, "z": 0.0, "widthM": 0.36, "depthM": 0.36, "heightM": 1.48, "rotationDeg": 0, "colorHex": "#edd29a", "accentColorHex": "#4a3728"},
            {"id": "p_art", "type": "WALL_ART", "label": "侘寂風掛畫", "x": 0.45, "y": 1.52, "z": 1.42, "widthM": 0.82, "depthM": 0.05, "heightM": 0.72, "rotationDeg": 0, "colorHex": "#cbbba4", "accentColorHex": "#6e5239"},
        ],
    },
    {
        "id": "SCENE_ENTRYWAY_FOYER",
        "name": "現代玄關落塵區（穿鞋凳＋鞋櫃情境）",
        "category": "玄關走廊",
        "builtin": True,
        "roomWidthM": 4.8,
        "roomDepthM": 3.6,
        "roomHeightM": 2.9,
        "wallColorHex": "#c2beb6",
        "sideWallColorHex": "#aeb3ad",
        "floorColorHex": "#6e655c",
        "lightingPreset": "NORDIC_BRIGHT",
        "productPose": {"x": -0.15, "y": 1.12, "z": 0.0, "rotationDeg": 0.0},
        "props": [
            {"id": "p_bench", "type": "BENCH", "label": "原木穿鞋凳", "x": -1.25, "y": 0.95, "z": 0.0, "widthM": 0.92, "depthM": 0.38, "heightM": 0.44, "rotationDeg": 0, "colorHex": "#9a6b3e", "accentColorHex": "#e3dcd0"},
            {"id": "p_plant", "type": "PLANT", "label": "迎賓植栽", "x": 1.05, "y": 0.95, "z": 0.0, "widthM": 0.44, "depthM": 0.44, "heightM": 0.98, "rotationDeg": 0, "colorHex": "#336948", "accentColorHex": "#b8734b"},
            {"id": "p_art", "type": "WALL_ART", "label": "玄關裝飾畫", "x": -1.25, "y": 1.52, "z": 1.38, "widthM": 0.65, "depthM": 0.05, "heightM": 0.88, "rotationDeg": 0, "colorHex": "#6c848c", "accentColorHex": "#3d4b52"},
            {"id": "p_rug", "type": "RUG", "label": "玄關落塵墊", "x": -0.15, "y": 0.35, "z": 0.0, "widthM": 1.8, "depthM": 0.95, "heightM": 0.015, "rotationDeg": 0, "colorHex": "#9c9488", "accentColorHex": "#7d756b"},
        ],
    },
    {
        "id": "SCENE_KIDS_PLAYROOM",
        "name": "馬卡龍兒童遊戲房（玩具繪本收納情境）",
        "category": "兒童房",
        "builtin": True,
        "roomWidthM": 5.2,
        "roomDepthM": 4.0,
        "roomHeightM": 2.9,
        "wallColorHex": "#e8dfd5",
        "sideWallColorHex": "#d4e0db",
        "floorColorHex": "#b89369",
        "lightingPreset": "NORDIC_BRIGHT",
        "productPose": {"x": 0.0, "y": 1.12, "z": 0.0, "rotationDeg": 0.0},
        "props": [
            {"id": "p_rug", "type": "RUG", "label": "雲朵遊戲墊", "x": 0.0, "y": 0.15, "z": 0.0, "widthM": 2.3, "depthM": 1.45, "heightM": 0.02, "rotationDeg": 0, "colorHex": "#f4e5d2", "accentColorHex": "#e5c1b8"},
            {"id": "p_table", "type": "COFFEE_TABLE", "label": "兒童積木桌", "x": -1.15, "y": 0.15, "z": 0.0, "widthM": 0.78, "depthM": 0.55, "heightM": 0.38, "rotationDeg": 0, "colorHex": "#e6b87d", "accentColorHex": "#f5f0e6"},
            {"id": "p_art1", "type": "WALL_ART", "label": "童趣插畫 A", "x": -0.95, "y": 1.52, "z": 1.45, "widthM": 0.55, "depthM": 0.04, "heightM": 0.65, "rotationDeg": 0, "colorHex": "#e39b8f", "accentColorHex": "#f2dec4"},
            {"id": "p_art2", "type": "WALL_ART", "label": "童趣插畫 B", "x": 0.95, "y": 1.52, "z": 1.45, "widthM": 0.55, "depthM": 0.04, "heightM": 0.65, "rotationDeg": 0, "colorHex": "#8fb8a8", "accentColorHex": "#f2dec4"},
        ],
    },
    {
        "id": "SCENE_HOME_STUDY",
        "name": "極簡居家書房（書桌＋收納邊櫃情境）",
        "category": "書房工作室",
        "builtin": True,
        "roomWidthM": 5.4,
        "roomDepthM": 4.0,
        "roomHeightM": 3.0,
        "wallColorHex": "#b5b9b4",
        "sideWallColorHex": "#9ea49e",
        "floorColorHex": "#694c33",
        "lightingPreset": "STUDIO_CLEAN",
        "productPose": {"x": 0.35, "y": 1.12, "z": 0.0, "rotationDeg": 0.0},
        "props": [
            {"id": "p_desk", "type": "DESK", "label": "胡桃木書桌", "x": -1.25, "y": 0.95, "z": 0.0, "widthM": 1.35, "depthM": 0.65, "heightM": 0.75, "rotationDeg": 0, "colorHex": "#825534", "accentColorHex": "#2b2e33"},
            {"id": "p_window", "type": "WINDOW_FRAME", "label": "書房採光窗", "x": -1.25, "y": 1.53, "z": 0.85, "widthM": 1.35, "depthM": 0.05, "heightM": 1.35, "rotationDeg": 0, "colorHex": "#e8f3fc", "accentColorHex": "#f0ede6"},
            {"id": "p_plant", "type": "PLANT", "label": "書房綠植", "x": 1.35, "y": 0.95, "z": 0.0, "widthM": 0.40, "depthM": 0.40, "heightM": 0.88, "rotationDeg": 0, "colorHex": "#2d6342", "accentColorHex": "#9e6847"},
        ],
    },
    {
        "id": "SCENE_DINING_KITCHEN",
        "name": "奶油風餐廚空間（餐邊櫃＋流理台情境）",
        "category": "餐廚空間",
        "builtin": True,
        "roomWidthM": 5.8,
        "roomDepthM": 4.2,
        "roomHeightM": 3.0,
        "wallColorHex": "#d8cfc0",
        "sideWallColorHex": "#c7bdb0",
        "floorColorHex": "#967656",
        "lightingPreset": "WARM_SUNLIGHT",
        "productPose": {"x": 0.25, "y": 1.08, "z": 0.0, "rotationDeg": 0.0},
        "props": [
            {"id": "p_kitchen", "type": "KITCHEN_COUNTER", "label": "餐廚流理台", "x": -1.45, "y": 1.15, "z": 0.0, "widthM": 1.9, "depthM": 0.62, "heightM": 0.86, "rotationDeg": 0, "colorHex": "#435e57", "accentColorHex": "#e3dbd0"},
            {"id": "p_plant", "type": "PLANT", "label": "餐邊植栽", "x": 1.35, "y": 0.95, "z": 0.0, "widthM": 0.40, "depthM": 0.40, "heightM": 0.86, "rotationDeg": 0, "colorHex": "#366e4c", "accentColorHex": "#c7855c"},
        ],
    },
]


class CellSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mode: Literal["DOOR", "OPEN", "DRAWER"] = "DOOR"
    colorHex: str | None = None
    artworkAssetId: str | None = None


class ColumnSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    widthMm: float = Field(default=424.0, ge=200.0, le=1200.0)
    heightMm: float = Field(default=900.0, ge=250.0, le=2400.0)
    rows: int = Field(default=3, ge=1, le=8)
    cells: list[CellSpec] = Field(default_factory=list)


class ModularCabinetRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(default="收納王妃組合櫃", min_length=1, max_length=200)
    sku: str = Field(default="SQ-MOD-CABINET", min_length=1, max_length=120)
    depthMm: float = Field(default=295.0, ge=180.0, le=800.0)
    panelMm: float = Field(default=15.0, ge=9.0, le=36.0)
    backMm: float = Field(default=3.0, ge=2.0, le=18.0)
    doorMm: float = Field(default=15.0, ge=9.0, le=30.0)
    gapMm: float = Field(default=2.0, ge=0.5, le=10.0)
    themeId: str = "THEME_NORDIC_OAK"
    carcassHex: str | None = None
    columns: list[ColumnSpec] = Field(default_factory=list, min_length=1, max_length=6)


def build_modular_cabinet_spec(payload: dict[str, Any], *, tenant_id: str = "sonaqueen-home") -> dict[str, Any]:
    req = ModularCabinetRequest.model_validate(payload)
    theme = STYLE_THEMES.get(req.themeId) or STYLE_THEMES["THEME_NORDIC_OAK"]
    carcass_rgb = hex_to_rgb(req.carcassHex or theme["carcassHex"], (0.78, 0.62, 0.40))
    back_rgb = hex_to_rgb(theme["backHex"], (0.95, 0.93, 0.89))
    door_palette = [hex_to_rgb(h, (0.96, 0.95, 0.92)) for h in theme["doorPaletteHex"]]
    drawer_rgb = hex_to_rgb(theme["drawerHex"], (0.92, 0.89, 0.84))

    total_w = sum(col.widthMm for col in req.columns)
    max_h = max(col.heightMm for col in req.columns)
    d = req.depthMm
    t = req.panelMm
    b = req.backMm
    door_t = req.doorMm
    gap = req.gapMm

    parts: list[dict[str, Any]] = []
    surfaces: list[dict[str, Any]] = []

    def add_part(pid: str, role: str, size_mm: list[float], loc_mm: list[float], color_rgb: list[float]) -> None:
        if min(size_mm) <= 0:
            raise ValueError(f"組件 {pid} 尺寸無效，請確認櫃寬、高度與板厚設定")
        parts.append(
            {
                "componentId": pid,
                "partName": pid,
                "role": role,
                "size": [round(v / 1000.0, 6) for v in size_mm],
                "location": [round(v / 1000.0, 6) for v in loc_mm],
                "sizeMm": [round(v, 3) for v in size_mm],
                "locationMm": [round(v, 3) for v in loc_mm],
                "length": round(max(size_mm), 3),
                "width": round(sorted(size_mm)[1], 3),
                "thickness": round(min(size_mm), 3),
                "colorRgb": color_rgb,
            }
        )

    cursor_x = -total_w / 2.0
    for c_idx, col in enumerate(req.columns, start=1):
        cw = col.widthMm
        ch = col.heightMm
        rows = col.rows
        cx = cursor_x + cw / 2.0
        cursor_x += cw

        front_inset = door_t + gap
        inner_w = cw - 2.0 * t
        inner_d = d - b - front_inset
        opening_h = (ch - (rows + 1) * t) / rows
        if min(inner_w, inner_d, opening_h) <= 0:
            raise ValueError(f"第 {c_idx} 欄櫃體內部空間不足，請增加寬高或減少層數")

        add_part(f"c{c_idx}_left", "left", [t, d, ch], [cx - cw / 2.0 + t / 2.0, 0.0, ch / 2.0], carcass_rgb)
        add_part(f"c{c_idx}_right", "right", [t, d, ch], [cx + cw / 2.0 - t / 2.0, 0.0, ch / 2.0], carcass_rgb)
        add_part(f"c{c_idx}_top", "top", [inner_w, d, t], [cx, 0.0, ch - t / 2.0], carcass_rgb)
        add_part(f"c{c_idx}_bottom", "bottom", [inner_w, d, t], [cx, 0.0, t / 2.0], carcass_rgb)
        add_part(f"c{c_idx}_back", "back", [inner_w, b, ch - 2.0 * t], [cx, d / 2.0 - b / 2.0, ch / 2.0], back_rgb)

        for r_idx in range(rows):
            cell_num = r_idx + 1
            z_center = t + r_idx * (opening_h + t) + opening_h / 2.0
            if r_idx < rows - 1:
                add_part(
                    f"c{c_idx}_shelf_{cell_num}",
                    "shelf",
                    [inner_w, inner_d, t],
                    [cx, (front_inset - b) / 2.0, z_center + opening_h / 2.0 + t / 2.0],
                    carcass_rgb,
                )
            cell_cfg = col.cells[r_idx] if r_idx < len(col.cells) else CellSpec(mode="DOOR")
            mode = cell_cfg.mode
            custom_rgb = hex_to_rgb(cell_cfg.colorHex, tuple(door_palette[(c_idx + r_idx) % len(door_palette)])) if cell_cfg.colorHex else door_palette[(c_idx + r_idx) % len(door_palette)]
            if mode == "DOOR":
                pid = f"door_c{c_idx}_r{cell_num}"
                dw = inner_w - 2.0 * gap
                dh = opening_h - 2.0 * gap
                add_part(pid, "door", [dw, door_t, dh], [cx, -d / 2.0 + door_t / 2.0, z_center], custom_rgb)
                surfaces.append({"componentId": pid, "label": f"第 {c_idx} 欄 · 第 {cell_num} 層門片", "widthMm": round(dw, 1), "heightMm": round(dh, 1)})
            elif mode == "DRAWER":
                dw = inner_w - 2.0 * gap
                dh = (opening_h - 3.0 * gap) / 2.0
                for d_sub in (1, 2):
                    pid = f"drawer_c{c_idx}_r{cell_num}_{d_sub}"
                    dz = z_center + (dh / 2.0 + gap / 2.0 if d_sub == 2 else -(dh / 2.0 + gap / 2.0))
                    add_part(pid, "door", [dw, door_t, dh], [cx, -d / 2.0 + door_t / 2.0, dz], cell_cfg.colorHex and custom_rgb or drawer_rgb)

    spec = {
        "productId": "mod_" + stable_hash({"req": req.model_dump(), "theme": req.themeId})[:20],
        "sku": req.sku,
        "tenantId": tenant_id,
        "name": req.name,
        "kind": "MODULAR_CABINET",
        "family": "cabinet",
        "width": round(total_w, 2),
        "depth": round(d, 2),
        "height": round(max_h, 2),
        "thickness": t,
        "themeId": req.themeId,
        "themeLabel": theme["label"],
        "material": "white_wood",
        "components": parts,
        "surfaces": surfaces,
        "previewAssumptions": [
            f"組合櫃總外尺寸：{round(total_w)} × {round(d)} × {round(max_h)} mm（共 {len(req.columns)} 欄並排）。",
            f"配色方案：{theme['label']}；板厚 {t} mm、背板 {b} mm、門縫 {gap} mm。",
            "此為電商情境與結構視覺預覽，未含五金孔位與工廠刀模放行。",
        ],
        "recipePreview": True,
        "goldenRecipe": True,
        "adapterVersion": "ECOMMERCE_MODULAR_V1",
        "engineeringReady": False,
        "productionReady": False,
    }
    spec["engineeringHash"] = stable_hash({"components": parts, "width": total_w, "depth": d, "height": max_h})
    spec["previewHash"] = stable_hash(spec)
    return spec


def _rotate_xy(dx: float, dy: float, deg: float) -> tuple[float, float]:
    rad = math.radians(deg or 0.0)
    c, s = math.cos(rad), math.sin(rad)
    return dx * c - dy * s, dx * s + dy * c


def _expand_prop_boxes(prop: dict[str, Any], index: int) -> list[dict[str, Any]]:
    ptype = str(prop.get("type") or "CUSTOM_BOX").upper()
    px = float(prop.get("x") or 0.0)
    py = float(prop.get("y") or 0.0)
    pz = float(prop.get("z") or 0.0)
    w = max(0.05, float(prop.get("widthM") or 0.6))
    d = max(0.05, float(prop.get("depthM") or 0.6))
    h = max(0.01, float(prop.get("heightM") or 0.5))
    rot = float(prop.get("rotationDeg") or 0.0) % 360.0
    if rot in (90.0, 270.0):
        w, d = d, w
    main_rgb = hex_to_rgb(prop.get("colorHex") or "#8a6b4e")
    acc_rgb = hex_to_rgb(prop.get("accentColorHex") or "#4a3520")
    prefix = f"Prop{index}_{ptype}"
    boxes: list[dict[str, Any]] = []

    def add(sub: str, sx: float, sy: float, sz: float, lx: float, ly: float, lz: float, col: list[float], bevel: float = 0.015) -> None:
        boxes.append(
            {
                "name": f"{prefix}_{sub}",
                "size": [round(max(0.01, sx), 4), round(max(0.01, sy), 4), round(max(0.008, sz), 4)],
                "location": [round(px + lx, 4), round(py + ly, 4), round(pz + lz, 4)],
                "color": col,
                "bevel": bevel,
            }
        )

    if ptype == "SOFA":
        add("FrameBase", w * 0.98, d * 0.94, h * 0.16, 0, 0, h * 0.18, main_rgb, 0.03)
        cw_seat = (w * 0.80) / 2.0 - 0.006
        add("CushionSeatL", cw_seat, d * 0.78, h * 0.21, -cw_seat / 2.0 - 0.004, -d * 0.05, h * 0.34, main_rgb, 0.055)
        add("CushionSeatR", cw_seat, d * 0.78, h * 0.21, cw_seat / 2.0 + 0.004, -d * 0.05, h * 0.34, main_rgb, 0.055)
        add("BackFrame", w * 0.98, d * 0.15, h * 0.62, 0, d * 0.40, h * 0.56, main_rgb, 0.04)
        add("CushionBackL", cw_seat * 0.97, d * 0.22, h * 0.45, -cw_seat / 2.0 - 0.004, d * 0.23, h * 0.64, main_rgb, 0.06)
        add("CushionBackR", cw_seat * 0.97, d * 0.22, h * 0.45, cw_seat / 2.0 + 0.004, d * 0.23, h * 0.64, main_rgb, 0.06)
        add("ArmL", w * 0.11, d * 0.92, h * 0.48, -w * 0.45, 0, h * 0.44, main_rgb, 0.045)
        add("ArmR", w * 0.11, d * 0.92, h * 0.48, w * 0.45, 0, h * 0.44, main_rgb, 0.045)
        add("PillowThrowL", 0.38, 0.17, 0.36, -w * 0.30, d * 0.08, h * 0.57, [0.91, 0.87, 0.80], 0.06)
        add("PillowThrowR", 0.35, 0.16, 0.33, w * 0.29, d * 0.09, h * 0.55, [0.76, 0.46, 0.32], 0.055)
        add("PillowLumbar", 0.42, 0.15, 0.24, -w * 0.12, d * 0.03, h * 0.51, [0.80, 0.72, 0.60], 0.05)
        for sx in (-w * 0.40, w * 0.40):
            for sy in (-d * 0.34, d * 0.34):
                add(f"Leg_{sx:.2f}_{sy:.2f}", 0.05, 0.05, h * 0.12, sx, sy, h * 0.06, acc_rgb, 0.012)
    elif ptype == "COFFEE_TABLE":
        add("Top", w, d, 0.042, 0, 0, h - 0.021, main_rgb, 0.02)
        for sx in (-w * 0.38, w * 0.38):
            for sy in (-d * 0.34, d * 0.34):
                add(f"Leg_{sx:.2f}_{sy:.2f}", 0.045, 0.045, h - 0.042, sx, sy, (h - 0.042) / 2.0, acc_rgb, 0.015)
        add("DecorBook1", 0.24, 0.18, 0.026, -w * 0.16, 0.02, h + 0.013, [0.90, 0.87, 0.81], 0.004)
        add("DecorBook2", 0.20, 0.15, 0.022, -w * 0.16, 0.02, h + 0.037, [0.36, 0.48, 0.44], 0.004)
        add("DecorVase_POT", 0.11, 0.11, 0.16, w * 0.18, -0.03, h + 0.08, [0.84, 0.78, 0.70], 0.02)
    elif ptype == "RUG":
        add("Mat", w, d, 0.012, 0, 0, 0.006, main_rgb, 0.005)
        add("Border", w * 0.90, d * 0.86, 0.014, 0, 0, 0.008, acc_rgb, 0.004)
    elif ptype == "FLOOR_LAMP":
        add("Base", w * 0.72, d * 0.72, 0.035, 0, 0, 0.018, acc_rgb, 0.01)
        add("Stem", 0.028, 0.028, h * 0.82, 0, 0, h * 0.42, acc_rgb, 0.005)
        add("Shade", w * 0.95, d * 0.95, h * 0.22, 0, 0, h * 0.86, main_rgb, 0.04)
    elif ptype == "WALL_ART":
        z_art = pz if pz > 0.2 else 1.45
        boxes.append({"name": f"{prefix}_Frame", "size": [round(w, 4), round(max(0.038, d), 4), round(h, 4)], "location": [round(px, 4), round(py, 4), round(z_art, 4)], "color": acc_rgb, "bevel": 0.006})
        boxes.append({"name": f"{prefix}_MatBoard", "size": [round(w * 0.90, 4), 0.018, round(h * 0.90, 4)], "location": [round(px, 4), round(py - 0.016, 4), round(z_art, 4)], "color": [0.93, 0.90, 0.85], "bevel": 0.002})
        boxes.append({"name": f"{prefix}_Canvas", "size": [round(w * 0.78, 4), 0.016, round(h * 0.78, 4)], "location": [round(px, 4), round(py - 0.022, 4), round(z_art, 4)], "color": main_rgb, "bevel": 0.002})
    elif ptype == "PLANT":
        add("Pot", w * 0.62, d * 0.62, h * 0.34, 0, 0, h * 0.17, acc_rgb, 0.03)
        add("FoliageMain", w * 0.92, d * 0.92, h * 0.62, 0, 0, h * 0.62, main_rgb, 0.08)
    elif ptype == "BED":
        add("Frame", w, d, h * 0.26, 0, 0, h * 0.13, acc_rgb, 0.015)
        add("Headboard", w, 0.10, h, 0, d * 0.46, h * 0.50, acc_rgb, 0.02)
        add("Mattress", w * 0.94, d * 0.90, h * 0.24, 0, -0.02, h * 0.36, main_rgb, 0.04)
        add("PillowL", w * 0.36, 0.28, 0.11, -w * 0.22, d * 0.28, h * 0.52, [0.96, 0.95, 0.92], 0.03)
        add("PillowR", w * 0.36, 0.28, 0.11, w * 0.22, d * 0.28, h * 0.52, [0.96, 0.95, 0.92], 0.03)
    elif ptype == "DESK":
        add("Top", w, d, 0.045, 0, 0, h - 0.0225, main_rgb, 0.012)
        add("LegL", 0.05, d * 0.86, h - 0.045, -w * 0.44, 0, (h - 0.045) / 2.0, acc_rgb, 0.006)
        add("LegR", 0.05, d * 0.86, h - 0.045, w * 0.44, 0, (h - 0.045) / 2.0, acc_rgb, 0.006)
    elif ptype == "BENCH":
        add("Seat", w, d, 0.06, 0, 0, h - 0.03, main_rgb, 0.02)
        add("Cushion", w * 0.92, d * 0.88, 0.05, 0, 0, h + 0.02, acc_rgb, 0.02)
        for sx in (-w * 0.38, w * 0.38):
            add(f"Leg_{sx:.2f}", 0.06, d * 0.78, h - 0.06, sx, 0, (h - 0.06) / 2.0, main_rgb, 0.008)
    elif ptype == "KITCHEN_COUNTER":
        add("Base", w, d, h * 0.92, 0, 0, h * 0.46, main_rgb, 0.012)
        add("Worktop", w * 1.03, d * 1.05, 0.05, 0, 0, h * 0.95, acc_rgb, 0.012)
    elif ptype == "WINDOW_FRAME":
        z_win = pz if pz > 0.1 else 0.75
        boxes.append({"name": f"{prefix}_Frame", "size": [round(w, 4), 0.06, round(h, 4)], "location": [round(px, 4), round(py, 4), round(z_win + h / 2.0, 4)], "color": acc_rgb, "bevel": 0.008})
        boxes.append({"name": f"{prefix}_Glass", "size": [round(w * 0.90, 4), 0.02, round(h * 0.90, 4)], "location": [round(px, 4), round(py - 0.02, 4), round(z_win + h / 2.0, 4)], "color": main_rgb, "bevel": 0.002})
    elif ptype == "SHEER_CURTAIN":
        boxes.append({"name": f"{prefix}_SheerCurtain", "size": [round(w, 4), round(d, 4), round(h, 4)], "location": [round(px, 4), round(py, 4), round(pz + h / 2.0, 4)], "color": main_rgb, "bevel": 0.01})
    else:
        entry: dict[str, Any] = {
            "name": f"{prefix}_Box",
            "size": [round(max(0.01, w), 4), round(max(0.01, d), 4), round(max(0.008, h), 4)],
            "location": [round(px, 4), round(py, 4), round(pz + h / 2.0, 4)],
            "color": main_rgb,
            "bevel": 0.015,
        }
        boxes.append(entry)

    if boxes and prop.get("glbPath"):
        boxes[0]["glbPath"] = str(prop["glbPath"])
        boxes[0]["propBounds"] = [round(px, 4), round(py, 4), round(pz, 4), round(w, 4), round(d, 4), round(h, 4)]

    return boxes


def compile_custom_scene(
    scene_cfg: dict[str, Any],
    cabinet_spec: dict[str, Any],
    *,
    view: str = "THREE_QUARTER",
) -> tuple[dict[str, Any], str]:
    """Compile a user-designed 3D scene + cabinet spec into a deterministic `FURNISHED_SCENE_V1` dict."""
    view_cfg = CAMERA_VIEWS.get(view) or CAMERA_VIEWS["THREE_QUARTER"]
    rw = max(2.8, min(10.0, float(scene_cfg.get("roomWidthM") or 5.4)))
    rd = max(2.4, min(8.0, float(scene_cfg.get("roomDepthM") or 4.0)))
    rh = max(2.2, min(4.5, float(scene_cfg.get("roomHeightM") or 3.0)))

    wall_rgb = hex_to_rgb(scene_cfg.get("wallColorHex") or "#b8ab96")
    side_rgb = hex_to_rgb(scene_cfg.get("sideWallColorHex") or "#a3a89c")
    floor_rgb = hex_to_rgb(scene_cfg.get("floorColorHex") or "#78583a")
    light_cfg = LIGHTING_PRESETS.get(str(scene_cfg.get("lightingPreset") or "WARM_SUNLIGHT")) or LIGHTING_PRESETS["WARM_SUNLIGHT"]

    pose_cfg = scene_cfg.get("productPose") or {}
    px = float(pose_cfg.get("x") or 0.0)
    py = float(pose_cfg.get("y") or 1.05)
    pz = float(pose_cfg.get("z") or 0.0)
    rot_deg = float(pose_cfg.get("rotationDeg") or 0.0)
    rad = math.radians(rot_deg)
    cos_r = round(math.cos(rad), 6)
    sin_r = round(math.sin(rad), 6)

    product_matrix = [
        [cos_r, -sin_r, 0.0, round(px, 4)],
        [sin_r, cos_r, 0.0, round(py, 4)],
        [0.0, 0.0, 1.0, round(pz, 4)],
        [0.0, 0.0, 0.0, 1.0],
    ]

    back_wall_y = 1.65
    boxes: list[dict[str, Any]] = [
        {"name": "Floor", "size": [round(rw + 1.2, 3), round(rd + 1.5, 3), 0.12], "location": [0.0, 0.0, -0.06], "color": floor_rgb, "bevel": 0.0},
        {"name": "BackWall", "size": [round(rw + 1.2, 3), 0.12, round(rh, 3)], "location": [0.0, back_wall_y, round(rh / 2.0, 3)], "color": wall_rgb, "bevel": 0.0},
        {"name": "Skirting", "size": [round(rw + 1.2, 3), 0.035, 0.09], "location": [0.0, round(back_wall_y - 0.075, 4), 0.045], "color": [0.86, 0.85, 0.80], "bevel": 0.002},
        {"name": "SideWall", "size": [0.12, round(rd + 1.5, 3), round(rh, 3)], "location": [round(-rw / 2.0, 3), 0.0, round(rh / 2.0, 3)], "color": side_rgb, "bevel": 0.0},
    ]

    for idx, prop in enumerate(scene_cfg.get("props") or [], start=1):
        boxes.extend(_expand_prop_boxes(prop, idx))

    # Add sleek brushed-metal handles on cabinet doors/drawers + interior decor in open shelves
    comps = cabinet_spec.get("components") or []
    comp_ids = {str(p.get("componentId") or "") for p in comps}
    for h_idx, part in enumerate(comps, start=1):
        if part.get("role") != "door":
            continue
        lx, ly, lz = [float(v) for v in part.get("location") or [0, 0, 0]]
        sx, sy, sz = [float(v) for v in part.get("size") or [0.4, 0.015, 0.3]]
        is_drawer = str(part.get("componentId") or "").startswith("drawer_")
        local_hx = lx if is_drawer else (lx + sx * 0.36)
        local_hy = ly - sy * 0.5 - 0.008
        local_hz = lz + (0.02 if is_drawer else 0.0)
        wx = px + (local_hx * cos_r - local_hy * sin_r)
        wy = py + (local_hx * sin_r + local_hy * cos_r)
        wz = pz + local_hz
        h_size = [0.11, 0.016, 0.014] if is_drawer else [0.014, 0.016, 0.11]
        if abs(sin_r) > 0.7:
            h_size = [h_size[1], h_size[0], h_size[2]]
        boxes.append({
            "name": f"CabinetHandle_{h_idx}_METAL",
            "size": h_size,
            "location": [round(wx, 4), round(wy, 4), round(wz, 4)],
            "color": [0.22, 0.20, 0.18],
            "bevel": 0.003,
        })

    # Automatically style open cabinet compartments with books & ceramic vessels
    open_idx = 0
    for part in comps:
        pid = str(part.get("componentId") or "")
        role = part.get("role")
        if role not in ("bottom", "shelf"):
            continue
        if role == "bottom" and pid.startswith("c") and pid.endswith("_bottom"):
            c_num = pid.split("_")[0][1:]
            r_num = "1"
        elif role == "shelf" and "_shelf_" in pid:
            c_part, s_num = pid.split("_shelf_")
            c_num = c_part[1:]
            r_num = str(int(s_num) + 1)
        else:
            continue
        if f"door_c{c_num}_r{r_num}" in comp_ids or f"drawer_c{c_num}_r{r_num}_1" in comp_ids:
            continue
        open_idx += 1
        lx, ly, lz = [float(v) for v in part.get("location") or [0, 0, 0]]
        sx, sy, sz = [float(v) for v in part.get("size") or [0.35, 0.26, 0.015]]
        surf_z = pz + lz + sz * 0.5
        if open_idx % 2 == 1:
            # Stacked hardcover books + ceramic bowl inside open shelf
            b1_lx, b1_ly = lx - sx * 0.14, ly - sy * 0.05
            wx1 = px + (b1_lx * cos_r - b1_ly * sin_r)
            wy1 = py + (b1_lx * sin_r + b1_ly * cos_r)
            boxes.append({"name": f"CabinetDecorBookA_{open_idx}", "size": [round(min(0.18, sx * 0.52), 4), round(min(0.15, sy * 0.62), 4), 0.024], "location": [round(wx1, 4), round(wy1, 4), round(surf_z + 0.012, 4)], "color": [0.88, 0.84, 0.77], "bevel": 0.003})
            boxes.append({"name": f"CabinetDecorBookB_{open_idx}", "size": [round(min(0.16, sx * 0.46), 4), round(min(0.13, sy * 0.56), 4), 0.022], "location": [round(wx1, 4), round(wy1, 4), round(surf_z + 0.035, 4)], "color": [0.68, 0.44, 0.32], "bevel": 0.003})
            v_lx, v_ly = lx + sx * 0.22, ly - sy * 0.04
            wx2 = px + (v_lx * cos_r - v_ly * sin_r)
            wy2 = py + (v_lx * sin_r + v_ly * cos_r)
            boxes.append({"name": f"CabinetDecorVase_{open_idx}_POT", "size": [0.085, 0.085, 0.12], "location": [round(wx2, 4), round(wy2, 4), round(surf_z + 0.06, 4)], "color": [0.85, 0.81, 0.75], "bevel": 0.015})
        else:
            # Woven storage basket inside open shelf
            wx1 = px + (lx * cos_r - ly * sin_r)
            wy1 = py + (lx * sin_r + ly * cos_r)
            boxes.append({"name": f"CabinetDecorBasket_{open_idx}_RUG", "size": [round(sx * 0.76, 4), round(sy * 0.78, 4), 0.14], "location": [round(wx1, 4), round(wy1, 4), round(surf_z + 0.07, 4)], "color": [0.78, 0.70, 0.58], "bevel": 0.018})

    # Off-camera window blind slats to cast natural sunlight stripes onto the upper wall
    for b_idx in range(6):
        boxes.append({
            "name": f"WindowBlindSlat_{b_idx}",
            "size": [1.8, 0.14, 0.012],
            "location": [-1.35, -1.35 + b_idx * 0.22, 2.55 + b_idx * 0.12],
            "color": [0.92, 0.90, 0.86],
            "bevel": 0.001,
        })

    w_m = float(cabinet_spec.get("width") or 424.0) / 1000.0
    d_m = float(cabinet_spec.get("depth") or 295.0) / 1000.0
    h_m = float(cabinet_spec.get("height") or 900.0) / 1000.0
    extent = max(w_m, d_m, h_m)
    dist = max(extent * float(view_cfg["distMult"]), 1.85 if view == "CLOSEUP" else 2.25)
    side = float(view_cfg["side"])
    target = [round(px * 0.65, 4), round(py * 0.55, 4), round(pz + h_m * 0.48, 4)]
    camera = {
        "location": [
            round(target[0] + dist * side, 4),
            round(target[1] - dist, 4),
            round(target[2] + dist * float(view_cfg["elev"]), 4),
        ],
        "lookAt": target,
        "focalLengthMm": float(view_cfg["lens"]),
    }

    definition = {
        "templateId": str(scene_cfg.get("id") or "CUSTOM_SCENE"),
        "sceneName": str(scene_cfg.get("name") or "自訂 3D 場景"),
        "version": 1,
        "rendererContract": "FURNISHED_SCENE_V1",
        "photorealMode": True,
        "slot": "FLOOR",
        "view": view_cfg["id"],
        "supportHeightM": round(pz, 4),
        "productMatrix": product_matrix,
        "camera": camera,
        "boxes": boxes,
        "worldColor": light_cfg["worldColor"],
        "worldStrength": light_cfg["worldStrength"],
        "lights": [
            {"name": "WindowKey", "type": "AREA", "location": [-1.8, -2.1, 3.1], "target": target, "energy": light_cfg["keyEnergy"], "size": 2.8, "color": light_cfg["keyColor"]},
            {"name": "RoomFill", "type": "AREA", "location": [2.1, -0.5, 2.4], "target": target, "energy": light_cfg["fillEnergy"], "size": 2.2, "color": light_cfg["fillColor"]},
            {"name": "SunBeam", "type": "SUN", "location": [-2.2, -2.5, 3.8], "target": target, "energy": 1.35, "angle": 0.038, "color": light_cfg["keyColor"]},
        ],
        "productScale": 1.0,
        "physicalRoomTruth": False,
    }
    scene_hash = stable_hash(definition)
    return definition, scene_hash


class EcommerceSceneStore:
    """Persistent store for user-created 3D room scenes and matrix render batches."""

    def __init__(self, platform: Any) -> None:
        self.platform = platform
        self.root = Path(platform.root).resolve() / "ecommerce-scene-studio"
        self.lock = RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ecom-scene-matrix")
        self.tasks: dict[str, Any] = {}
        try:
            ensure_pbr_texture_assets()
        except Exception:
            pass

    def _tenant_dir(self, tenant_id: str) -> Path:
        safe = "".join(c for c in tenant_id if c.isalnum() or c in ("-", "_")) or "default"
        d = self.root / safe
        d.mkdir(parents=True, exist_ok=True)
        return d

    def upload_glb_prop(self, tenant_id: str, filename: str, raw_bytes: bytes) -> dict[str, Any]:
        if not raw_bytes or len(raw_bytes) < 16:
            raise ValueError("上傳的 .glb 檔案內容為空")
        safe_name = "".join(c for c in Path(filename or "custom_prop.glb").stem if c.isalnum() or c in ("-", "_")) or "custom_prop"
        prop_id = f"glb_{safe_name}_{new_id().split('-')[0]}"
        gdir = self._tenant_dir(tenant_id) / "glb-props"
        gdir.mkdir(parents=True, exist_ok=True)
        target = gdir / f"{prop_id}.glb"
        target.write_bytes(raw_bytes)
        return {
            "propId": prop_id,
            "filename": f"{prop_id}.glb",
            "label": f"📦 3D 模型：{safe_name}",
            "glbPath": str(target.resolve()),
            "sizeBytes": len(raw_bytes),
        }

    def list_scenes(self, tenant_id: str) -> list[dict[str, Any]]:
        path = self._tenant_dir(tenant_id) / "scenes.json"
        with self.lock:
            stored = read_json(path)
            custom = stored.get("items", []) if isinstance(stored, dict) else []
            by_id = {s["id"]: dict(s) for s in BUILTIN_SCENES}
            for item in custom:
                if isinstance(item, dict) and item.get("id"):
                    by_id[item["id"]] = item
            return list(by_id.values())

    def save_scene(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        path = self._tenant_dir(tenant_id) / "scenes.json"
        scene_id = str(payload.get("id") or "").strip() or ("SCENE_CUSTOM_" + new_id().split("-")[0].upper())
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("請輸入 3D 場景名稱")
        record = {
            "id": scene_id,
            "name": name,
            "category": str(payload.get("category") or "自訂場景"),
            "builtin": any(b["id"] == scene_id for b in BUILTIN_SCENES),
            "roomWidthM": max(2.8, min(10.0, float(payload.get("roomWidthM") or 5.4))),
            "roomDepthM": max(2.4, min(8.0, float(payload.get("roomDepthM") or 4.0))),
            "roomHeightM": max(2.2, min(4.5, float(payload.get("roomHeightM") or 3.0))),
            "wallColorHex": str(payload.get("wallColorHex") or "#b8ab96"),
            "sideWallColorHex": str(payload.get("sideWallColorHex") or "#a3a89c"),
            "floorColorHex": str(payload.get("floorColorHex") or "#78583a"),
            "lightingPreset": str(payload.get("lightingPreset") or "WARM_SUNLIGHT"),
            "productPose": payload.get("productPose") or {"x": 0.0, "y": 1.10, "z": 0.0, "rotationDeg": 0.0},
            "props": list(payload.get("props") or []),
            "updatedAt": timestamp(),
        }
        with self.lock:
            stored = read_json(path)
            custom = [x for x in (stored.get("items", []) if isinstance(stored, dict) else []) if x.get("id") != scene_id]
            custom.append(record)
            atomic_json(path, {"items": custom, "updatedAt": timestamp()})
        return record

    def delete_scene(self, tenant_id: str, scene_id: str) -> dict[str, Any]:
        if any(b["id"] == scene_id for b in BUILTIN_SCENES):
            raise ValueError("內建範例場景可修改，但不可刪除；您可以另存新場景")
        path = self._tenant_dir(tenant_id) / "scenes.json"
        with self.lock:
            stored = read_json(path)
            custom = [x for x in (stored.get("items", []) if isinstance(stored, dict) else []) if x.get("id") != scene_id]
            atomic_json(path, {"items": custom, "updatedAt": timestamp()})
        return {"deleted": scene_id}

    def overview(self, tenant_id: str) -> dict[str, Any]:
        blender_ok = bool(
            not getattr(self.platform, "mock_blender", True)
            and getattr(self.platform, "runtime", None)
            and self.platform.runtime.available()
        )
        ph_root = Path(__file__).resolve().parents[2] / "assets" / "models" / "polyhaven"
        ph_list = []
        for aid, cfg in POLYHAVEN_CURATED_MODELS.items():
            res = cfg.get("resolution", "2k")
            gpath = ph_root / aid / f"{aid}_{res}.gltf"
            ph_list.append({
                **cfg,
                "glbPath": str(gpath.resolve()),
                "thumbUrl": f"/api/ecommerce-scenes/polyhaven-thumb/{aid}",
                "installed": gpath.exists(),
            })
        return {
            "blenderAvailable": blender_ok,
            "cabinetPresets": CABINET_PRESETS,
            "styleThemes": list(STYLE_THEMES.values()),
            "propCatalog": PROP_CATALOG,
            "polyhavenModels": ph_list,
            "lightingPresets": [{"id": k, **v} for k, v in LIGHTING_PRESETS.items()],
            "aiStylePresets": list(AI_STYLE_PRESETS.values()),
            "cameraViews": list(CAMERA_VIEWS.values()),
            "scenes": self.list_scenes(tenant_id),
            "batches": self.list_batches(tenant_id),
        }

    def preview_plan(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        cabinet_cfg = payload.get("cabinet") or CABINET_PRESETS[0]
        cabinet_spec = build_modular_cabinet_spec(cabinet_cfg, tenant_id=tenant_id)
        scenes = {s["id"]: s for s in self.list_scenes(tenant_id)}
        scene_cfg = payload.get("scene")
        if not isinstance(scene_cfg, dict):
            sid = str(payload.get("sceneId") or "SCENE_NORDIC_LIVING")
            scene_cfg = scenes.get(sid) or BUILTIN_SCENES[0]
        view = str(payload.get("view") or "THREE_QUARTER")
        scene_def, scene_hash = compile_custom_scene(scene_cfg, cabinet_spec, view=view)
        return {
            "cabinetSpec": cabinet_spec,
            "sceneConfig": scene_cfg,
            "sceneDefinition": scene_def,
            "sceneHash": scene_hash,
            "view": view,
        }

    def list_batches(self, tenant_id: str) -> list[dict[str, Any]]:
        bdir = self._tenant_dir(tenant_id) / "batches"
        if not bdir.exists():
            return []
        paths = sorted(bdir.glob("*/batch.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True)
        out = []
        for p in paths[:15]:
            data = read_json(p)
            if data:
                out.append(data)
        return out

    def get_batch(self, tenant_id: str, batch_id: str) -> dict[str, Any]:
        bpath = self._tenant_dir(tenant_id) / "batches" / batch_id / "batch.json"
        data = read_json(bpath)
        if not data:
            raise KeyError("找不到此批次渲染任務")
        return data

    def start_matrix_batch(self, tenant_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        cabinet_cfg = dict(payload.get("cabinet") or CABINET_PRESETS[0])
        scene_ids = list(payload.get("sceneIds") or ["SCENE_NORDIC_LIVING"])
        theme_ids = list(payload.get("themeIds") or [cabinet_cfg.get("themeId") or "THEME_NORDIC_OAK"])
        views = list(payload.get("views") or ["THREE_QUARTER"])
        samples = max(12, min(64, int(payload.get("samples") or 24)))
        ai_style_id = str(payload.get("aiStyleId") or "AI_NORDIC_SUNLIT_LOFT")
        ai_prompt = str(payload.get("aiPrompt") or "").strip()

        if not scene_ids or not theme_ids or not views:
            raise ValueError("請至少勾選 1 個場景、1 種櫃體配色與 1 個鏡頭視角")
        total = len(scene_ids) * len(theme_ids) * len(views)
        if total > 36:
            raise ValueError("單次 Blender 光追矩陣上限為 36 張，請分批執行")

        scenes_by_id = {s["id"]: s for s in self.list_scenes(tenant_id)}
        custom_scene_inline = payload.get("currentScene")
        if isinstance(custom_scene_inline, dict) and custom_scene_inline.get("id"):
            scenes_by_id[custom_scene_inline["id"]] = custom_scene_inline

        batch_id = new_id()
        bdir = self._tenant_dir(tenant_id) / "batches" / batch_id
        bdir.mkdir(parents=True, exist_ok=True)

        items: list[dict[str, Any]] = []
        idx = 0
        for sid in scene_ids:
            scfg = scenes_by_id.get(sid) or BUILTIN_SCENES[0]
            for tid in theme_ids:
                tcfg = STYLE_THEMES.get(tid) or STYLE_THEMES["THEME_NORDIC_OAK"]
                for vw in views:
                    idx += 1
                    item_id = f"item_{idx:02d}"
                    vcfg = CAMERA_VIEWS.get(vw) or CAMERA_VIEWS["THREE_QUARTER"]
                    items.append(
                        {
                            "itemId": item_id,
                            "index": idx,
                            "sceneId": scfg["id"],
                            "sceneName": scfg["name"],
                            "themeId": tcfg["id"],
                            "themeLabel": tcfg["label"],
                            "view": vcfg["id"],
                            "viewLabel": vcfg["label"],
                            "aiStyleId": ai_style_id,
                            "state": "queued",
                            "error": None,
                            "renderTimeSec": None,
                            "blenderVersion": None,
                            "device": None,
                            "hasAiComposite": False,
                            "hasCutout": False,
                        }
                    )

        batch_doc = {
            "batchId": batch_id,
            "tenantId": tenant_id,
            "cabinetName": cabinet_cfg.get("name") or "收納王妃組合櫃",
            "cabinetSku": cabinet_cfg.get("sku") or "SQ-MOD-CABINET",
            "aiStyleId": ai_style_id,
            "aiPrompt": ai_prompt,
            "createdAt": timestamp(),
            "state": "running",
            "samples": samples,
            "total": len(items),
            "completed": 0,
            "succeeded": 0,
            "failed": 0,
            "items": items,
        }
        atomic_json(bdir / "batch.json", batch_doc)

        self.executor.submit(
            self._run_matrix_worker,
            tenant_id,
            batch_id,
            bdir,
            cabinet_cfg,
            scenes_by_id,
            items,
            samples,
            ai_style_id,
            ai_prompt,
        )
        return batch_doc

    def _run_matrix_worker(
        self,
        tenant_id: str,
        batch_id: str,
        bdir: Path,
        cabinet_cfg: dict[str, Any],
        scenes_by_id: dict[str, dict[str, Any]],
        items: list[dict[str, Any]],
        samples: int,
        ai_style_id: str = "AI_NORDIC_SUNLIT_LOFT",
        ai_prompt: str = "",
    ) -> None:
        try:
            ensure_pbr_texture_assets()
        except Exception:
            pass
        blender_ok = bool(
            not getattr(self.platform, "mock_blender", True)
            and getattr(self.platform, "runtime", None)
            and self.platform.runtime.available()
        )
        for item in items:
            item["state"] = "running"
            self._save_batch_progress(bdir, items)
            item_dir = bdir / item["itemId"]
            item_dir.mkdir(parents=True, exist_ok=True)
            try:
                cab_copy = dict(cabinet_cfg, themeId=item["themeId"])
                cab_spec = build_modular_cabinet_spec(cab_copy, tenant_id=tenant_id)
                scfg = scenes_by_id.get(item["sceneId"]) or BUILTIN_SCENES[0]
                scene_def, scene_hash = compile_custom_scene(scfg, cab_spec, view=item["view"])
                cab_spec["sceneDefinition"] = scene_def
                cab_spec["sceneHash"] = scene_hash
                cab_spec["nasScene"] = "STUDIO"

                if not blender_ok:
                    raise RuntimeError("本機 Blender 未啟用或不可用")

                job = {
                    "jobId": f"{batch_id}_{item['itemId']}",
                    "workDir": str(item_dir),
                    "recipePreview": True,
                    "goldenRecipe": True,
                    "goldenIdentity": {
                        "sku": cab_spec["sku"],
                        "packageHash": scene_hash,
                    },
                    "engineering": cab_spec,
                    "camera": scene_def["camera"],
                    "render": {
                        "width": 800,
                        "height": 800,
                        "samples": max(32, samples),
                        "device": "OPTIX",
                    },
                    "exportBlend": True,
                    "exportGlb": True,
                }
                res = self.platform.runtime.run_job(job)
                status_val = getattr(res, "status", None) or (res.get("status") if isinstance(res, dict) else None)
                outputs_val = getattr(res, "outputs", None) or (res.get("outputs") if isinstance(res, dict) else {}) or {}
                for fname in ("beauty.png", "product_cutout.png", "model.glb", "model.blend"):
                    src_p = outputs_val.get(fname)
                    if src_p and Path(src_p).exists() and Path(src_p).resolve() != (item_dir / fname).resolve():
                        shutil.copy2(src_p, item_dir / fname)
                if status_val not in ("succeeded", "completed") or not (item_dir / "beauty.png").exists():
                    err_msg = getattr(res, "error", None) or (res.get("error") if isinstance(res, dict) else None)
                    raise RuntimeError(err_msg or "Blender 算圖未產出 beauty.png")

                # Plan B: Run AI Studio Room Compositor with 100% locked cabinet cutout + shadow catcher
                try:
                    build_ai_photoreal_composite(
                        item_dir / "beauty.png",
                        item_dir / "product_cutout.png" if (item_dir / "product_cutout.png").exists() else None,
                        item_dir / "ai_composite.png",
                        ai_style_id=ai_style_id,
                        custom_prompt=ai_prompt,
                        view=item["view"],
                    )
                except Exception:
                    pass

                item["state"] = "succeeded"
                item["hasAiComposite"] = (item_dir / "ai_composite.png").exists()
                item["hasCutout"] = (item_dir / "product_cutout.png").exists()
                item["renderTimeSec"] = getattr(res, "render_time_sec", None) or (res.get("renderTimeSec") if isinstance(res, dict) else None)
                item["blenderVersion"] = getattr(res, "blender_version", None) or (res.get("blenderVersion") if isinstance(res, dict) else None)
                item["device"] = getattr(res, "device", None) or (res.get("device") if isinstance(res, dict) else None)
            except Exception as exc:
                item["state"] = "failed"
                item["error"] = str(exc)[:300]
            self._save_batch_progress(bdir, items)

    def _save_batch_progress(self, bdir: Path, items: list[dict[str, Any]]) -> None:
        doc = read_json(bdir / "batch.json") or {}
        succeeded = sum(1 for x in items if x["state"] == "succeeded")
        failed = sum(1 for x in items if x["state"] == "failed")
        completed = succeeded + failed
        total = len(items)
        doc.update(
            items=items,
            completed=completed,
            succeeded=succeeded,
            failed=failed,
            state="completed" if completed >= total else "running",
            updatedAt=timestamp(),
        )
        atomic_json(bdir / "batch.json", doc)

    def item_asset_path(self, tenant_id: str, batch_id: str, item_id: str, fmt: str) -> Path:
        files = {
            "png": "beauty.png",
            "ai_png": "ai_composite.png",
            "cutout_png": "product_cutout.png",
            "glb": "model.glb",
            "blend": "model.blend",
        }
        if fmt not in files:
            raise ValueError("支援格式：png、ai_png、cutout_png、glb、blend")
        p = self._tenant_dir(tenant_id) / "batches" / batch_id / item_id / files[fmt]
        if not p.exists() and fmt == "ai_png":
            p = self._tenant_dir(tenant_id) / "batches" / batch_id / item_id / "beauty.png"
        if not p.exists():
            raise KeyError("檔案尚未產出或不存在")
        return p

    def build_batch_zip(self, tenant_id: str, batch_id: str) -> bytes:
        batch = self.get_batch(tenant_id, batch_id)
        bdir = self._tenant_dir(tenant_id) / "batches" / batch_id
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("batch-manifest.json", json.dumps(batch, ensure_ascii=False, indent=2))
            for item in batch.get("items") or []:
                if item.get("state") != "succeeded":
                    continue
                base_prefix = f"{item['index']:02d}_{item['sceneId']}_{item['themeId']}_{item['view']}"
                png = bdir / item["itemId"] / "beauty.png"
                if png.exists():
                    zf.write(png, arcname=f"{base_prefix}_A_3D_Photoreal.png")
                ai_png = bdir / item["itemId"] / "ai_composite.png"
                if ai_png.exists():
                    zf.write(ai_png, arcname=f"{base_prefix}_B_AI_Studio.png")
                cut_png = bdir / item["itemId"] / "product_cutout.png"
                if cut_png.exists():
                    zf.write(cut_png, arcname=f"{base_prefix}_Cutout_Transparent.png")
        return buf.getvalue()
