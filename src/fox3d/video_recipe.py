"""Deterministic camera recipes. No provider pixels or hinge guesses are authority."""
from __future__ import annotations

import copy
import importlib.util
import math
from pathlib import Path

from fox3d.ids import stable_hash

DURATIONS = {"HERO_ORBIT_8S": 8, "DOOR_OPEN_8S": 8, "ARTWORK_DETAIL_6S": 6,
             "SMALL_ROOM_10S": 10, "ASSEMBLY_EXPLODE_10S": 10}
ROLES = {"beauty": "png", "depth": "exr", "normal": "exr", "product_mask": "png",
         "artwork_mask": "png", "alpha": "png"}


def finite(value, name="number"):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError(f"strict_finite:{name}")
    return float(value)


def integer(value, lo, hi, name):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"strict_integer:{name}")
    return value


def vector(value, n=3):
    if type(value) is not list or len(value) != n:
        raise ValueError("vector_shape")
    return [finite(v) for v in value]


def identity_matrix(location=None):
    loc = location or [0., 0., 0.]
    return [[1., 0., 0., loc[0]], [0., 1., 0., loc[1]],
            [0., 0., 1., loc[2]], [0., 0., 0., 1.]]


def camera_matrix(location, target):
    def norm(a):
        length = math.sqrt(sum(v*v for v in a))
        if length < 1e-9:
            raise ValueError("degenerate_camera")
        return [v/length for v in a]
    def cross(a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
    z = norm([a-b for a, b in zip(location, target)])
    x = norm(cross([0., 0., 1.], z)); y = cross(z, x)
    return [[x[i], y[i], z[i], location[i]] for i in range(3)] + [[0., 0., 0., 1.]]


def close_numbers(actual, expected, tolerance=2e-5):
    if isinstance(expected, list):
        return type(actual) is list and len(actual) == len(expected) and all(
            close_numbers(a, b, tolerance) for a, b in zip(actual, expected))
    try:
        return abs(finite(actual)-finite(expected)) <= tolerance
    except (ValueError, TypeError):
        return False


def expected_objects(engineering):
    """Execute the existing geometry interpreter with a data-only box sink.

    This is pre-worker authority, independently derived from frozen CabinetSpec.
    It preserves existing main's rendering conventions without redefining mm truth.
    """
    for key in ("width", "height", "depth"):
        if finite(engineering[key], key) <= 0:
            raise ValueError("engineering_dimensions")
    for part in engineering["components"]:
        for key in ("length", "width", "thickness"):
            if key in part:
                finite(part[key], key)
        for key in ("location", "size"):
            if key in part:
                vector(part[key])
    script = Path(__file__).resolve().parents[2] / "scripts/blender_job.py"
    spec = importlib.util.spec_from_file_location("_video_geometry_authority", script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    def box(name, size, location, material=None):
        return {"matrix": identity_matrix(location), "dimensions": [v/2 for v in size],
                "vertices": 8, "polygons": 6}
    module._add_box = box
    return module.add_cabinet_parts(copy.deepcopy(engineering))


def make_recipe(kind, engineering, *, fps=12, width=128, height=128, artwork_object=None):
    if kind not in DURATIONS:
        raise ValueError("unknown_video_recipe")
    integer(fps, 1, 60, "fps"); integer(width, 32, 2048, "width"); integer(height, 32, 2048, "height")
    dimensions = [finite(engineering[k], k)/1000 for k in ("width", "depth", "height")]
    if min(dimensions) <= 0:
        raise ValueError("engineering_dimensions")
    radius = max(dimensions)*2.5
    target = [0., 0., dimensions[2]*.5]
    angles = [-35., 35.] if kind != "ARTWORK_DETAIL_6S" else [-8., 8.]
    if kind == "ARTWORK_DETAIL_6S":
        objects=expected_objects(engineering)
        if artwork_object not in objects:raise ValueError("detail_artwork_surface_required")
        obj=objects[artwork_object]
        target=[row[3] for row in obj["matrix"][:3]]
        radius=max(obj["dimensions"])*3.
    camera = {"version": 1, "interpolation": "SMOOTHSTEP_ANGLE_DOLLY", "up": "+Z", "forward": "-Z",
              "lookAt": target, "focalLengthMm": 45., "sensorWidthMm": 36., "sensorFit": "HORIZONTAL",
              "clipStart": .01, "clipEnd": 100., "pixelAspect": [1., 1.],
              "keyframes": [{"t": 0., "angleDeg": angles[0], "radius": radius, "elevation": dimensions[2]*.72},
                            {"t": (DURATIONS[kind]*fps-1)/fps, "angleDeg": angles[1], "radius": radius*.94, "elevation": dimensions[2]*.72}]}
    scene = {"version": 1, "lighting": "EXISTING_CABINET_THREE_POINT", "worldColor": [.18, .18, .18],
             "worldStrength": .3, "transparent": True, "samples": 4, "engine": "CYCLES",
             "groundVisible": False, "colorManagement": "Standard", "geometryUnit": "METRE",
             "exposure": -1.5,
             "depthEncoding": "LINEAR_METRES_FLOAT32_EXR", "normalEncoding": "WORLD_XYZ_FLOAT32_EXR"}
    scene["room"] = {"width":max(dimensions)*6.,"depth":max(dimensions)*5.,"height":dimensions[2]*1.5} if kind=="SMALL_ROOM_10S" else None
    z=max(dimensions[2]*1.6,.8)
    scene["lights"]=[{"name":"Light.Key","type":"AREA","location":[1.4,-1.6,z],"energy":400.,"color":[1.,.98,.94]},
                     {"name":"Light.Fill","type":"AREA","location":[-1.6,-.9,z*.8],"energy":120.,"color":[.9,.95,1.]},
                     {"name":"Light.Rim","type":"SPOT","location":[.1,1.8,z],"energy":220.,"color":[1.,1.,1.]}]
    if scene["room"]:scene["transparent"]=False
    result = {"recipeId": kind, "version": 1, "duration": DURATIONS[kind], "fps": fps,
              "width": width, "height": height, "frameCount": DURATIONS[kind]*fps,
              "timestampConvention": "ZERO_BASED_FRAME_START_SECONDS_LAST_POSE_HELD_TO_DURATION",
              "camera": camera, "scene": scene,
              "productTimeline": [{"t": 0., "matrix": identity_matrix()},
                                  {"t": float(DURATIONS[kind]), "matrix": identity_matrix()}],
              "articulationTimeline": [], "cameraRecipeHash": stable_hash(camera), "sceneRecipeHash": stable_hash(scene)}
    result["detailObject"]=artwork_object if kind=="ARTWORK_DETAIL_6S" else None
    result["videoRecipeHash"] = stable_hash(result)
    return result


def validate_recipe(recipe, engineering):
    expected = make_recipe(recipe["recipeId"], engineering, fps=recipe["fps"], width=recipe["width"], height=recipe["height"],artwork_object=recipe.get("detailObject"))
    # Numeric coercion must not make a bool, string or NaN compare equal.
    def strict_types(a, b):
        if type(a) is not type(b):
            return False
        if isinstance(b, dict):
            return a.keys() == b.keys() and all(strict_types(a[k], b[k]) for k in b)
        if isinstance(b, list):
            return len(a) == len(b) and all(strict_types(x, y) for x, y in zip(a, b))
        return a == b
    if not strict_types(recipe, expected):
        raise ValueError("recipe_semantics_or_hash")


def frame_plan(recipe, index):
    integer(index, 0, recipe["frameCount"]-1, "frame")
    u = index/max(1, recipe["frameCount"]-1); u = u*u*(3-2*u)
    a, b = recipe["camera"]["keyframes"]
    mix = lambda k: a[k]*(1-u)+b[k]*u
    angle = math.radians(mix("angleDeg")); radius = mix("radius")
    location = [recipe["camera"]["lookAt"][0]+radius*math.sin(angle), recipe["camera"]["lookAt"][1]-radius*math.cos(angle), mix("elevation")]
    lens = recipe["camera"]["focalLengthMm"]; sensor = recipe["camera"]["sensorWidthMm"]
    f = recipe["width"]*lens/sensor
    return {"index": index, "timestamp": index/recipe["fps"], "location": location,
            "cameraMatrix": camera_matrix(location, recipe["camera"]["lookAt"]),
            "intrinsics": [[f, 0., recipe["width"]/2], [0., f, recipe["height"]/2], [0., 0., 1.]],
            "productMatrix": identity_matrix(), "articulation": []}


def articulation_gate(recipe, authority):
    # Main does not expose independently validated hinge or assembly authority.
    # Caller/worker metadata, including a claimed pivot or ready flag, cannot opt in.
    if recipe["recipeId"] == "DOOR_OPEN_8S":
        raise ValueError("BLOCKED_ARTICULATION_AUTHORITY")
    if recipe["recipeId"] == "ASSEMBLY_EXPLODE_10S":
        raise ValueError("BLOCKED_ASSEMBLY_AUTHORITY")
