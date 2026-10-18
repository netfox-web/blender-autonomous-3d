"""Build a separate presentation scene; canonical meshes/UVs remain untouched."""
import json
import hashlib
import math
import os

ASSET_REF_PREFIX = 'assets://'


def _assets_root():
    """Asset root shared by every machine: FOX3D_ASSETS_ROOT (GPU nodes) or <repo>/assets (workbench)."""
    from pathlib import Path
    override = os.environ.get('FOX3D_ASSETS_ROOT', '').strip()
    return Path(override) if override else Path(__file__).resolve().parents[1] / 'assets'


def resolve_asset_ref(value, root=None):
    """`assets://models/x/y.gltf` -> <assets root>/models/x/y.gltf; anything else is returned as a Path unchanged.

    Scene definitions carry these machine-independent refs so the scene hash is identical on the workbench and on
    the fleet node; `..` segments are refused so a definition can never escape the asset root.
    """
    from pathlib import Path
    if value is None:
        return None
    text = str(value)
    if not text.startswith(ASSET_REF_PREFIX):
        return Path(text)
    rel = text[len(ASSET_REF_PREFIX):].replace('\\', '/').lstrip('/')
    parts = [seg for seg in rel.split('/') if seg not in ('', '.')]
    if any(seg == '..' for seg in parts):
        raise ValueError('asset ref escapes the asset root: ' + text)
    base = Path(root) if root is not None else _assets_root()
    return base.joinpath(*parts)


def _srgb_to_lin(c: float) -> float:
    c = max(0.0, min(1.0, float(c)))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _apply_pbr_shader(mat, obj_name, base_color, photoreal=False):
    mat.use_nodes = True
    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links
    shader = nodes.get('Principled BSDF')
    if not shader:
        return
    r, g, b = float(base_color[0]), float(base_color[1]), float(base_color[2])
    if photoreal:
        r, g, b = _srgb_to_lin(r), _srgb_to_lin(g), _srgb_to_lin(b)
    shader.inputs['Base Color'].default_value = (r, g, b, 1.0)
    if not photoreal:
        shader.inputs['Roughness'].default_value = 0.7
        return

    name_u = obj_name.upper()
    tex_coord = nodes.new('ShaderNodeTexCoord')
    mapping = nodes.new('ShaderNodeMapping')
    links.new(tex_coord.outputs['Generated'], mapping.inputs['Vector'])

    if any(k in name_u for k in ('DOOR', 'DRAWER')):
        # Smooth satin furniture lacquer / melamine finish on cabinet doors & drawers
        shader.inputs['Roughness'].default_value = 0.28
        if 'Coat Weight' in shader.inputs:
            shader.inputs['Coat Weight'].default_value = 0.28
    elif 'FLOOR' in name_u and 'LAMP' not in name_u:
        # Staggered hardwood plank floor with individual board seams + wood grain
        brick = nodes.new('ShaderNodeTexBrick')
        brick.offset = 0.5
        brick.squash = 5.5
        brick.inputs['Scale'].default_value = 9.0
        brick.inputs['Mortar Size'].default_value = 0.005
        brick.inputs['Mortar Smooth'].default_value = 0.25
        brick.inputs['Color1'].default_value = (min(1.0, r * 1.05), min(1.0, g * 1.05), min(1.0, b * 1.05), 1.0)
        brick.inputs['Color2'].default_value = (r * 0.80, g * 0.78, b * 0.75, 1.0)
        brick.inputs['Mortar'].default_value = (r * 0.22, g * 0.18, b * 0.14, 1.0)
        links.new(tex_coord.outputs['Generated'], brick.inputs['Vector'])

        mapping.inputs['Scale'].default_value = (14.0, 2.8, 2.5)
        wave = nodes.new('ShaderNodeTexWave')
        wave.wave_type = 'BANDS'
        wave.bands_direction = 'X'
        wave.inputs['Scale'].default_value = 5.0
        wave.inputs['Distortion'].default_value = 2.4
        wave.inputs['Detail'].default_value = 2.5
        links.new(mapping.outputs['Vector'], wave.inputs['Vector'])

        mix = nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 0.14
        links.new(brick.outputs['Color'], mix.inputs[6])
        links.new(wave.outputs['Color'], mix.inputs[7])
        links.new(mix.outputs[2], shader.inputs['Base Color'])

        bump = nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.08
        bump.inputs['Distance'].default_value = 0.002
        links.new(brick.outputs['Fac'], bump.inputs['Height'])
        links.new(bump.outputs['Normal'], shader.inputs['Normal'])
        shader.inputs['Roughness'].default_value = 0.30
        if 'Coat Weight' in shader.inputs:
            shader.inputs['Coat Weight'].default_value = 0.25
    elif any(k in name_u for k in ('SOFA', 'RUG', 'MAT', 'PILLOW', 'CUSHION', 'BASKET', 'MATTRESS')) and '_LEG_' not in name_u:
        # Real Poly Haven scanned fabric Normal Map + Displacement Map (Triplanar BOX projection) + Grazing Velvet Sheen
        mapping.inputs['Scale'].default_value = (4.5, 4.5, 4.5) if 'RUG' in name_u else (6.5, 6.5, 6.5)

        noise_macro = nodes.new('ShaderNodeTexNoise')
        noise_macro.inputs['Scale'].default_value = 5.2
        noise_macro.inputs['Detail'].default_value = 5.0
        noise_macro.inputs['Roughness'].default_value = 0.68
        links.new(tex_coord.outputs['Generated'], noise_macro.inputs['Vector'])

        loaded_ph_tex = False
        try:
            import bpy
            from pathlib import Path
            pbr_dir = _assets_root() / 'textures' / 'pbr'
            if 'RUG' in name_u or 'PILLOWTHROWL' in name_u:
                nor_file = pbr_dir / 'curly_teddy_nor_gl.jpg'
                disp_file = pbr_dir / 'curly_teddy_disp.jpg'
            elif 'PILLOW' in name_u or 'MATTRESS' in name_u:
                nor_file = pbr_dir / 'rough_linen_nor_gl.jpg'
                disp_file = pbr_dir / 'rough_linen_disp.jpg'
            else:
                nor_file = pbr_dir / 'wool_herringbone_nor_gl.jpg'
                disp_file = pbr_dir / 'wool_herringbone_disp.jpg'

            if nor_file.exists() and disp_file.exists():
                tex_disp = nodes.new('ShaderNodeTexImage')
                tex_disp.image = bpy.data.images.load(str(disp_file), check_existing=True)
                tex_disp.projection = 'BOX'
                tex_disp.projection_blend = 0.25
                links.new(mapping.outputs['Vector'], tex_disp.inputs['Vector'])

                tex_nor = nodes.new('ShaderNodeTexImage')
                tex_nor.image = bpy.data.images.load(str(nor_file), check_existing=True)
                try:
                    tex_nor.image.colorspace_settings.name = 'Non-Color'
                except Exception:
                    pass
                tex_nor.projection = 'BOX'
                tex_nor.projection_blend = 0.25
                links.new(mapping.outputs['Vector'], tex_nor.inputs['Vector'])

                # Blend scanned yarn weave height with two-tone thread colors
                mix_col = nodes.new('ShaderNodeMix')
                mix_col.data_type = 'RGBA'
                mix_col.blend_type = 'MIX'
                links.new(tex_disp.outputs['Color'], mix_col.inputs['Factor'])
                mix_col.inputs[6].default_value = (r * 0.66, g * 0.66, b * 0.66, 1.0)
                mix_col.inputs[7].default_value = (min(1.0, r * 1.30 + 0.02), min(1.0, g * 1.30 + 0.02), min(1.0, b * 1.28 + 0.015), 1.0)

                mix_suede = nodes.new('ShaderNodeMix')
                mix_suede.data_type = 'RGBA'
                mix_suede.blend_type = 'MULTIPLY'
                mix_suede.inputs['Factor'].default_value = 0.20
                links.new(mix_col.outputs[2], mix_suede.inputs[6])
                links.new(noise_macro.outputs['Color'], mix_suede.inputs[7])
                links.new(mix_suede.outputs[2], shader.inputs['Base Color'])

                nor_map = nodes.new('ShaderNodeNormalMap')
                nor_map.inputs['Strength'].default_value = 1.55
                links.new(tex_nor.outputs['Color'], nor_map.inputs['Color'])

                bump_fold = nodes.new('ShaderNodeBump')
                bump_fold.inputs['Strength'].default_value = 0.35 if ('CUSHION' in name_u or 'PILLOW' in name_u) else 0.18
                bump_fold.inputs['Distance'].default_value = 0.012
                links.new(noise_macro.outputs['Fac'], bump_fold.inputs['Height'])
                links.new(nor_map.outputs['Normal'], bump_fold.inputs['Normal'])
                links.new(bump_fold.outputs['Normal'], shader.inputs['Normal'])
                loaded_ph_tex = True
        except Exception:
            loaded_ph_tex = False

        if not loaded_ph_tex:
            noise_micro = nodes.new('ShaderNodeTexNoise')
            noise_micro.inputs['Scale'].default_value = 185.0
            noise_micro.inputs['Detail'].default_value = 8.0
            noise_micro.inputs['Roughness'].default_value = 0.82
            links.new(mapping.outputs['Vector'], noise_micro.inputs['Vector'])
            bump_micro = nodes.new('ShaderNodeBump')
            bump_micro.inputs['Strength'].default_value = 0.28
            bump_micro.inputs['Distance'].default_value = 0.004
            links.new(noise_micro.outputs['Fac'], bump_micro.inputs['Height'])
            links.new(bump_micro.outputs['Normal'], shader.inputs['Normal'])

        shader.inputs['Roughness'].default_value = 0.92
        if 'Sheen Weight' in shader.inputs:
            shader.inputs['Sheen Weight'].default_value = 0.96
        if 'Sheen Roughness' in shader.inputs:
            shader.inputs['Sheen Roughness'].default_value = 0.40
        if 'Sheen Tint' in shader.inputs:
            shader.inputs['Sheen Tint'].default_value = (
                min(1.0, r * 1.35 + 0.16),
                min(1.0, g * 1.32 + 0.14),
                min(1.0, b * 1.28 + 0.12),
                1.0,
            )
    elif any(k in name_u for k in ('TABLE', 'DESK', 'BENCH', 'FRAME', 'WORKTOP', 'WOOD', 'CABINET', '_LEG_')):
        # Procedural timber / hardwood grain with satin finish
        mapping.inputs['Scale'].default_value = (4.0, 1.5, 1.5)
        wave = nodes.new('ShaderNodeTexWave')
        wave.wave_type = 'BANDS'
        wave.bands_direction = 'Y'
        wave.inputs['Scale'].default_value = 4.5
        wave.inputs['Distortion'].default_value = 2.2
        wave.inputs['Detail'].default_value = 2.0
        links.new(mapping.outputs['Vector'], wave.inputs['Vector'])

        mix = nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 0.10
        mix.inputs[6].default_value = (r, g, b, 1.0)
        links.new(wave.outputs['Color'], mix.inputs[7])
        links.new(mix.outputs[2], shader.inputs['Base Color'])

        bump = nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.02
        bump.inputs['Distance'].default_value = 0.0015
        links.new(wave.outputs['Fac'], bump.inputs['Height'])
        links.new(bump.outputs['Normal'], shader.inputs['Normal'])
        shader.inputs['Roughness'].default_value = 0.36
        if 'Coat Weight' in shader.inputs:
            shader.inputs['Coat Weight'].default_value = 0.20
    elif any(k in name_u for k in ('FOLIAGE', 'LEAF')):
        # Botanical waxy leaf with subtle subsurface scattering
        shader.inputs['Roughness'].default_value = 0.32
        if 'Coat Weight' in shader.inputs:
            shader.inputs['Coat Weight'].default_value = 0.35
        if 'Subsurface Weight' in shader.inputs:
            shader.inputs['Subsurface Weight'].default_value = 0.18
    elif any(k in name_u for k in ('POT', 'VASE')):
        # Matte glazed ceramic / terracotta vessel
        shader.inputs['Roughness'].default_value = 0.38
        if 'Coat Weight' in shader.inputs:
            shader.inputs['Coat Weight'].default_value = 0.22
    elif any(k in name_u for k in ('SHADE', 'GLASS')):
        shader.inputs['Roughness'].default_value = 0.35
        if 'Emission Color' in shader.inputs and 'Emission Strength' in shader.inputs:
            shader.inputs['Emission Color'].default_value = (r, g, b, 1.0)
            shader.inputs['Emission Strength'].default_value = 2.6 if 'GLASS' in name_u else 1.6
    elif any(k in name_u for k in ('STEM', 'HANDLE', 'METAL')):
        shader.inputs['Metallic'].default_value = 0.88
        shader.inputs['Roughness'].default_value = 0.24
    elif any(k in name_u for k in ('CURTAIN', 'SHEER')):
        # Translucent linen sheer curtain with subsurface light transmission & soft sheen
        shader.inputs['Roughness'].default_value = 0.62
        if 'Subsurface Weight' in shader.inputs:
            shader.inputs['Subsurface Weight'].default_value = 0.55
        if 'Sheen Weight' in shader.inputs:
            shader.inputs['Sheen Weight'].default_value = 0.80
        if 'Transmission Weight' in shader.inputs:
            shader.inputs['Transmission Weight'].default_value = 0.25
    elif 'WALL_ART' in name_u and 'CANVAS' in name_u:
        shader.inputs['Roughness'].default_value = 0.68
        try:
            import bpy
            from pathlib import Path
            art_path = _assets_root() / 'textures' / 'pbr' / 'nordic_canvas_art.png'
            if art_path.exists():
                sep = nodes.new('ShaderNodeSeparateXYZ')
                comb = nodes.new('ShaderNodeCombineXYZ')
                links.new(tex_coord.outputs['Generated'], sep.inputs['Vector'])
                links.new(sep.outputs['X'], comb.inputs['X'])
                links.new(sep.outputs['Z'], comb.inputs['Y'])
                tex_img = nodes.new('ShaderNodeTexImage')
                tex_img.image = bpy.data.images.load(str(art_path), check_existing=True)
                links.new(comb.outputs['Vector'], tex_img.inputs['Vector'])
                links.new(tex_img.outputs['Color'], shader.inputs['Base Color'])
        except Exception:
            pass
    elif any(k in name_u for k in ('WALL',)):
        # Architectural matte plaster
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 55.0
        noise.inputs['Detail'].default_value = 4.0
        links.new(tex_coord.outputs['Object'], noise.inputs['Vector'])
        bump = nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.04
        bump.inputs['Distance'].default_value = 0.001
        links.new(noise.outputs['Fac'], bump.inputs['Height'])
        links.new(bump.outputs['Normal'], shader.inputs['Normal'])
        shader.inputs['Roughness'].default_value = 0.82
    else:
        shader.inputs['Roughness'].default_value = 0.48


def _smooth_polygons(obj):
    try:
        for poly in obj.data.polygons:
            poly.use_smooth = True
    except Exception:
        pass


def _import_and_fit_gltf(scene, gltf_path, group_name, px, py, pz, w, d, h, uniform_scale=False):
    """Import a Poly Haven 2K glTF or custom GLB model and fit it to (px, py, pz) with target dimensions (w, d, h)."""
    import bpy
    from mathutils import Vector

    before = set(scene.objects)
    bpy.ops.import_scene.gltf(filepath=str(gltf_path))
    imp_all = [o for o in scene.objects if o not in before]
    imp_meshes = [o for o in imp_all if o.type == 'MESH']
    if not imp_meshes:
        return False

    scene.view_layers[0].update()
    pts = [o.matrix_world @ Vector(c) for o in imp_meshes for c in o.bound_box]
    min_x, max_x = min(v.x for v in pts), max(v.x for v in pts)
    min_y, max_y = min(v.y for v in pts), max(v.y for v in pts)
    min_z, max_z = min(v.z for v in pts), max(v.z for v in pts)
    cur_w = max(0.001, max_x - min_x)
    cur_d = max(0.001, max_y - min_y)
    cur_h = max(0.001, max_z - min_z)

    root = bpy.data.objects.new(f'Environment.{group_name}.Root', None)
    root.location = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, min_z)
    scene.collection.objects.link(root)
    scene.view_layers[0].update()

    for idx_o, o in enumerate(imp_all):
        o.name = f'Environment.{group_name}.{idx_o}_{o.name}'
        if o.parent not in imp_all:
            o.parent = root
            o.matrix_parent_inverse = root.matrix_world.inverted()
        if o.type == 'MESH':
            _smooth_polygons(o)
            for mat in o.data.materials:
                if not mat or not mat.use_nodes:
                    continue
                mname = mat.name.upper()
                sh = mat.node_tree.nodes.get('Principled BSDF')
                if not sh:
                    continue
                if any(k in mname for k in ('LEAF', 'LEAVES', 'FOLIAGE', 'PLANT')):
                    if 'Subsurface Weight' in sh.inputs:
                        sh.inputs['Subsurface Weight'].default_value = 0.25
                elif any(k in mname for k in ('SOFA', 'FABRIC', 'SEAT', 'CLOTH')):
                    if 'Sheen Weight' in sh.inputs:
                        sh.inputs['Sheen Weight'].default_value = 0.85

    auto_rot = 0.0
    swap_xy = False
    if not uniform_scale:
        if (w > d * 1.15 and cur_d > cur_w * 1.15) or (d > w * 1.15 and cur_w > cur_d * 1.15):
            auto_rot = math.pi * 0.5
            swap_xy = True
    if 'sofa_02' in str(gltf_path).lower():
        auto_rot += math.pi

    root.location = (px, py, pz)
    root.rotation_euler = (0.0, 0.0, auto_rot)
    if uniform_scale:
        s_uni = h / cur_h
        root.scale = (s_uni, s_uni, s_uni)
    elif swap_xy:
        root.scale = (d / cur_w, w / cur_d, h / cur_h)
    else:
        root.scale = (w / cur_w, d / cur_d, h / cur_h)
    scene.view_layers[0].update()
    return True


def _sculpt_upholstery_mesh(obj, name_u, sx, sy, sz, wrinkle_img=None):
    """Method 2: High-poly bmesh subdivision + superellipsoid cushion rounding + tufted cloth creases & pinched-pillow sculpting."""
    import bpy
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(obj.data)
    is_pillow = 'PILLOW' in name_u
    is_cushion = 'CUSHION' in name_u or 'MATTRESS' in name_u
    is_back = 'CUSHIONBACK' in name_u
    cuts = 12 if is_pillow else (10 if is_cushion else 8)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges, cuts=cuts, use_grid_fill=True)

    hx = max(0.001, sx * 0.5)
    hy = max(0.001, sy * 0.5)
    hz = max(0.001, sz * 0.5)
    seed = 1.7 if ('R' in name_u) else (0.6 if 'LUMBAR' in name_u else 0.0)

    for v in bm.verts:
        nx = max(-1.0, min(1.0, v.co.x / hx))
        ny = max(-1.0, min(1.0, v.co.y / hy))
        nz = max(-1.0, min(1.0, v.co.z / hz))

        if is_pillow:
            # True knife-edge pinched throw pillow with puffed belly, dog-ear corners & karate-chop indent
            belly = math.cos(nx * 1.32) * math.cos(nz * 1.32)
            edge_pinch = (1.0 - 0.78 * (nx ** 4)) * (1.0 - 0.78 * (nz ** 4))
            v.co.y = ny * hy * (0.26 + 0.98 * max(0.0, belly) * edge_pinch)
            # Dog-ear flare at the 4 corners
            corner_flare = (nx * nx) * (nz * nz)
            v.co.x *= (1.0 + 0.09 * corner_flare - 0.05 * (nz * nz) * (1.0 - nx * nx))
            v.co.z *= (1.0 + 0.09 * corner_flare - 0.05 * (nx * nx) * (1.0 - nz * nz))
            # Designer "karate-chop" indent at top center + diagonal cloth fold creases
            if nz > 0.32:
                chop = math.exp(-((nx * 3.0) ** 2) - (((nz - 0.85) * 3.4) ** 2))
                v.co.z -= chop * sz * 0.10
                v.co.y *= (1.0 - chop * 0.28)
            diag1 = math.exp(-(((nx * 0.82 + nz * 0.58 + 0.08 * math.cos(seed)) ** 2) * 16.0))
            diag2 = math.exp(-(((nx * 0.65 - nz * 0.75 - 0.10) ** 2) * 20.0))
            wrinkle = (
                math.sin(nx * 14.0 + nz * 8.0 + seed) * 0.0065
                + math.cos(nz * 12.0 - nx * 6.0) * 0.0050
            ) * (0.35 + 0.65 * max(abs(nx), abs(nz)))
            v.co.y -= math.copysign(1.0, ny if abs(ny) > 0.01 else 1.0) * (diag1 * 0.015 + diag2 * 0.011 - wrinkle)
        elif is_cushion:
            # 1. Superellipsoid soft edge & corner roll-off so subdivided cushions are plush, never boxy
            rx = max(0.0, (abs(nx) - 0.62) / 0.38)
            ry = max(0.0, (abs(ny) - 0.62) / 0.38)
            rz = max(0.0, (abs(nz) - 0.45) / 0.55)
            edge_xy = min(1.0, math.hypot(rx, ry))
            v.co.z *= (1.0 - 0.26 * (edge_xy ** 1.8))
            v.co.x *= (1.0 - 0.12 * (rx * ry) - 0.07 * (rz ** 2) * rx)
            v.co.y *= (1.0 - 0.12 * (rx * ry) - 0.09 * (rz ** 2) * ry)

            # 2. Plush overstuffed crown + gathered seam pleats
            dome = math.cos(nx * 1.18) * math.cos(ny * 1.18)
            edge_dist = max(abs(nx), abs(ny))
            seam_pleat = 0.0
            if edge_dist > 0.45:
                pleat_env = ((edge_dist - 0.45) / 0.55) * (1.0 - (edge_dist ** 6) * 0.4)
                seam_pleat = (
                    math.sin(nx * 16.0 + ny * 5.0 + seed) * 0.0075
                    + math.cos(ny * 14.0 - nx * 7.0 + seed) * 0.0065
                ) * pleat_env

            if is_back:
                # Overstuffed back pillow leaning gently backward with 2 tufted button dimples & radial pleats
                lumbar = math.cos(nz * 1.22) * math.cos(nx * 1.10)
                v.co.y += nz * 0.035 - (1.0 if ny < 0 else -0.45) * max(0.0, lumbar) * 0.028 + seam_pleat
                if nz > 0.18:
                    v.co.y *= (1.0 - 0.24 * ((nz - 0.18) / 0.82) ** 2)
                for tx in (-0.36, 0.36):
                    dx_t, dz_t = nx - tx, nz - 0.04
                    r_t = math.hypot(dx_t * 2.2, dz_t * 2.0)
                    tuft = math.exp(-(r_t ** 2) * 3.2)
                    ang_t = math.atan2(dz_t, dx_t)
                    rad_pleat = math.sin(ang_t * 6.0) * math.exp(-r_t * 1.8) * (r_t / (0.2 + r_t))
                    if ny < 0:
                        v.co.y += tuft * 0.022 - rad_pleat * 0.0065
            else:
                # Seat cushion: crowned top, 2 tufted stitch dimples + radial cloth creases, bullnose front
                tuft_sum = 0.0
                for tx in (-0.36, 0.36):
                    dx_t, dy_t = nx - tx, ny + 0.04
                    r_t = math.hypot(dx_t * 2.2, dy_t * 2.0)
                    tuft = math.exp(-(r_t ** 2) * 3.2)
                    ang_t = math.atan2(dy_t, dx_t)
                    rad_pleat = math.sin(ang_t * 6.0) * math.exp(-r_t * 1.8) * (r_t / (0.2 + r_t))
                    tuft_sum += tuft * 0.018 - rad_pleat * 0.0055
                if nz > 0:
                    v.co.z += max(0.0, dome) * 0.028 - tuft_sum + seam_pleat
                else:
                    v.co.z -= max(0.0, dome) * 0.006
                if ny < -0.35:
                    v.co.y -= math.cos(nz * 1.35) * 0.018 * abs(ny)
        else:
            # Softly tailored upholstery frame / armrest with rounded superellipsoid corners & fabric puff
            rx = max(0.0, (abs(nx) - 0.58) / 0.42)
            ry = max(0.0, (abs(ny) - 0.72) / 0.28)
            rz = max(0.0, (abs(nz) - 0.65) / 0.35)
            if nz > 0:
                v.co.z *= (1.0 - 0.16 * min(1.0, rx * rx + ry * ry))
            v.co.x *= (1.0 - 0.12 * rx * rz - 0.10 * rx * ry)
            v.co.y *= (1.0 - 0.08 * ry * rz - 0.10 * rx * ry)
            dome = math.cos(nx * 1.1) * math.cos(ny * 1.1)
            v.co.z += (1.0 if nz > 0 else -0.3) * max(0.0, dome) * 0.008

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    _smooth_polygons(obj)

    try:
        sub = obj.modifiers.new('PlushSubsurf', 'SUBSURF')
        sub.levels = 2
        sub.render_levels = 2
        if wrinkle_img is not None and (is_cushion or is_pillow):
            tex = bpy.data.textures.new(obj.name + '.WrinkleTex', type='IMAGE')
            tex.image = wrinkle_img
            disp = obj.modifiers.new('ClothWrinkleDisp', 'DISPLACE')
            disp.texture = tex
            disp.strength = 0.011 if is_pillow else 0.009
            disp.mid_level = 0.5
    except Exception:
        pass


def _add_cushion_piping(scene, iname, lx, ly, lz, sx, sy, sz, mat):
    """Add 3D stitched piping cord (welt seam) around seat and back cushions."""
    import bpy
    r_pipe = 0.007
    top_z = lz + sz * 0.38
    segments = [
        ('FrontWelt', (lx, ly - sy * 0.49, top_z), (0.0, math.pi * 0.5, 0.0), sx * 0.90),
        ('LeftWelt', (lx - sx * 0.46, ly, top_z), (math.pi * 0.5, 0.0, 0.0), sy * 0.90),
        ('RightWelt', (lx + sx * 0.46, ly, top_z), (math.pi * 0.5, 0.0, 0.0), sy * 0.90),
    ]
    for s_tag, loc, rot_e, length in segments:
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=r_pipe, depth=length, location=loc, rotation=rot_e)
        p_obj = bpy.context.object
        p_obj.name = f'Environment.{iname}.{s_tag}'
        p_obj.data.materials.append(mat)
        _smooth_polygons(p_obj)



def build(created, definition, device, expected_hash):
    import bpy
    from mathutils import Matrix, Vector
    from pathlib import Path
    # Blender ships its own Python; do not import application dependencies here.
    digest = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')).hexdigest()
    if digest != expected_hash:
        raise ValueError('Scene definition hash mismatch')
    photoreal = bool(definition.get('photorealMode'))
    original = bpy.context.scene
    scene = bpy.data.scenes.new('ProductScene.' + definition['templateId'])
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'GPU' if device in ('OPTIX', 'CUDA') else 'CPU'
    try:
        scene.cycles.use_denoising = True
    except Exception:
        pass
    if photoreal:
        try:
            scene.cycles.max_bounces = 8
            scene.cycles.diffuse_bounces = 4
            scene.cycles.glossy_bounces = 4
        except Exception:
            pass
    scene.view_settings.view_transform = original.view_settings.view_transform
    if photoreal:
        try:
            scene.view_settings.look = 'Medium High Contrast'
        except Exception:
            pass
    scene['sceneHash'] = expected_hash
    scene['sceneDefinition'] = json.dumps(definition)
    scene.world = bpy.data.worlds.new('RoomWorld')
    scene.world.use_nodes = True
    bg = scene.world.node_tree.nodes.get('Background')
    bg.inputs['Color'].default_value = (*definition['worldColor'], 1)
    bg.inputs['Strength'].default_value = definition['worldStrength']
    pose = Matrix(definition['productMatrix'])
    observations = []
    for src in created.values():
        if not src.get('recipeComponentId'):
            continue
        clone = src.copy()  # linked mesh includes the exact material slots and UVs
        for key in list(clone.keys()):
            del clone[key]
        clone.name = 'SceneProduct.' + src['recipeComponentId']
        clone['sceneComponentId'] = src['recipeComponentId']
        clone['canonicalObject'] = src.name
        scene.collection.objects.link(clone)
        clone.matrix_world = pose @ src.matrix_world
        if photoreal:
            try:
                bev = clone.modifiers.new('CabinetMicroBevel', 'BEVEL')
                bev.width = 0.0015
                bev.segments = 2
                for mat in clone.data.materials:
                    if mat and mat.use_nodes:
                        sh = mat.node_tree.nodes.get('Principled BSDF')
                        if sh and not any(n.type == 'TEX_IMAGE' for n in mat.node_tree.nodes):
                            col = list(sh.inputs['Base Color'].default_value)[:3]
                            _apply_pbr_shader(mat, 'CABINET_' + clone.name, col, photoreal=True)
            except Exception:
                pass
        observations.append({'componentId': src['recipeComponentId'], 'linkedMesh': clone.data == src.data,
                             'matrixWorld': [list(row) for row in clone.matrix_world]})
    try:
        bpy.context.window.scene = scene
        root_assets = _assets_root()
        wrinkle_img = None
        if photoreal:
            wrinkle_path = root_assets / 'textures' / 'pbr' / 'cloth_wrinkle_disp.png'
            if wrinkle_path.exists():
                try:
                    wrinkle_img = bpy.data.images.load(str(wrinkle_path), check_existing=True)
                except Exception:
                    wrinkle_img = None

        # Pre-scan prop groups for Method 1 (Poly Haven 2K Photogrammetry glTF / Custom GLB) when photoreal=True
        handled_groups = set()
        if photoreal:
            prop_groups = {}
            for item in definition['boxes']:
                iname = item['name']
                parts = iname.split('_')
                if len(parts) >= 2 and parts[0].startswith('Prop'):
                    gkey = f'{parts[0]}_{parts[1]}'
                    prop_groups.setdefault(gkey, []).append(item)

            ph_dir = root_assets / 'models' / 'polyhaven'
            for gkey, gitems in prop_groups.items():
                g_upper = gkey.upper()
                explicit_glb = resolve_asset_ref(next((it.get('glbPath') for it in gitems if it.get('glbPath')), None), root_assets)
                explicit_bounds = next((it.get('propBounds') for it in gitems if it.get('propBounds')), None)

                # Calculate combined group bounds from sub-boxes
                if explicit_bounds and len(explicit_bounds) == 6:
                    gx, gy, gz, gw, gd, gh = [float(v) for v in explicit_bounds]
                else:
                    # For COFFEE_TABLE, exclude DecorBook / DecorVase when computing the table frame bounds
                    core_items = [
                        it for it in gitems
                        if not any(d_k in it['name'].upper() for d_k in ('DECORBOOK', 'DECORVASE'))
                    ] or gitems
                    min_bx = min(it['location'][0] - it['size'][0] * 0.5 for it in core_items)
                    max_bx = max(it['location'][0] + it['size'][0] * 0.5 for it in core_items)
                    min_by = min(it['location'][1] - it['size'][1] * 0.5 for it in core_items)
                    max_by = max(it['location'][1] + it['size'][1] * 0.5 for it in core_items)
                    min_bz = min(it['location'][2] - it['size'][2] * 0.5 for it in core_items)
                    max_bz = max(it['location'][2] + it['size'][2] * 0.5 for it in core_items)
                    gx, gy, gz = (min_bx + max_bx) * 0.5, (min_by + max_by) * 0.5, max(0.0, min_bz)
                    gw, gd, gh = max_bx - min_bx, max_by - min_by, max_bz - min_bz

                if explicit_glb and Path(str(explicit_glb)).exists():
                    try:
                        if _import_and_fit_gltf(scene, explicit_glb, gkey, gx, gy, gz, gw, gd, gh, uniform_scale=('_PLANT' in g_upper)):
                            handled_groups.add(gkey)
                            continue
                    except Exception:
                        pass

                # Method 1 automatic Poly Haven 2K upgrade for PLANT and COFFEE_TABLE
                if g_upper.endswith('_PLANT'):
                    ph_plant = (
                        ph_dir / 'potted_plant_01' / 'potted_plant_01_2k.gltf'
                        if gh >= 1.02
                        else ph_dir / 'potted_plant_02' / 'potted_plant_02_2k.gltf'
                    )
                    if ph_plant.exists():
                        try:
                            if _import_and_fit_gltf(scene, ph_plant, gkey, gx, gy, gz, gw, gd, gh, uniform_scale=True):
                                handled_groups.add(gkey)
                                continue
                        except Exception:
                            pass
                elif g_upper.endswith('_COFFEE'):
                    # Note: prop prefix for COFFEE_TABLE has parts[0]=PropX, parts[1]=COFFEE
                    pass

            # Also check COFFEE_TABLE groups (where parts[:3] is PropX_COFFEE_TABLE)
            ct_groups = {}
            for item in definition['boxes']:
                iname = item['name']
                if '_COFFEE_TABLE_' in iname.upper():
                    gkey = iname.split('_COFFEE_TABLE_')[0] + '_COFFEE_TABLE'
                    if not any(dk in iname.upper() for dk in ('DECORBOOK', 'DECORVASE')):
                        ct_groups.setdefault(gkey, []).append(item)
            for gkey, core_items in ct_groups.items():
                explicit_glb = resolve_asset_ref(next((it.get('glbPath') for it in core_items if it.get('glbPath')), None), root_assets)
                min_bx = min(it['location'][0] - it['size'][0] * 0.5 for it in core_items)
                max_bx = max(it['location'][0] + it['size'][0] * 0.5 for it in core_items)
                min_by = min(it['location'][1] - it['size'][1] * 0.5 for it in core_items)
                max_by = max(it['location'][1] + it['size'][1] * 0.5 for it in core_items)
                min_bz = min(it['location'][2] - it['size'][2] * 0.5 for it in core_items)
                max_bz = max(it['location'][2] + it['size'][2] * 0.5 for it in core_items)
                gx, gy, gz = (min_bx + max_bx) * 0.5, (min_by + max_by) * 0.5, max(0.0, min_bz)
                gw, gd, gh = max_bx - min_bx, max_by - min_by, max_bz - min_bz
                ph_table = (
                    Path(str(explicit_glb))
                    if explicit_glb and Path(str(explicit_glb)).exists()
                    else (
                        ph_dir / 'coffee_table_round_01' / 'coffee_table_round_01_2k.gltf'
                        if abs(gw - gd) < 0.14
                        else ph_dir / 'modern_coffee_table_01' / 'modern_coffee_table_01_2k.gltf'
                    )
                )
                if ph_table.exists():
                    try:
                        if _import_and_fit_gltf(scene, ph_table, gkey, gx, gy, gz, gw, gd, gh, uniform_scale=False):
                            handled_groups.add(gkey)
                    except Exception:
                        pass

        for item in definition['boxes']:
            iname = item['name']
            name_u = iname.upper()
            parts = iname.split('_')
            if len(parts) >= 2 and parts[0].startswith('Prop'):
                gkey_short = f'{parts[0]}_{parts[1]}'
                if gkey_short in handled_groups:
                    continue
            if '_COFFEE_TABLE_' in name_u:
                gkey_ct = iname.split('_COFFEE_TABLE_')[0] + '_COFFEE_TABLE'
                if gkey_ct in handled_groups and not any(dk in name_u for dk in ('DECORBOOK', 'DECORVASE')):
                    continue

            sx, sy, sz = [float(v) for v in item['size']]
            lx, ly, lz = [float(v) for v in item['location']]
            mat = bpy.data.materials.new('Environment.' + iname)
            _apply_pbr_shader(mat, iname, item['color'], photoreal=photoreal)

            glb_path = resolve_asset_ref(item.get('glbPath'), root_assets)
            if photoreal and glb_path and Path(str(glb_path)).exists():
                try:
                    if _import_and_fit_gltf(scene, glb_path, iname, lx, ly, max(0.0, lz - sz * 0.5), sx, sy, sz):
                        continue
                except Exception:
                    pass

            if photoreal and 'SHEERCURTAIN' in name_u:
                # Build wave-pleated floor-to-ceiling sheer linen curtain
                n_pleats = 10
                pleat_w = sx / n_pleats
                for p_i in range(n_pleats):
                    px_i = (lx - sx * 0.5) + (p_i + 0.5) * pleat_w
                    py_i = ly + (0.018 if p_i % 2 == 0 else -0.018)
                    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=pleat_w * 0.58, depth=sz, location=(px_i, py_i, lz))
                    pl = bpy.context.object
                    pl.name = f'Environment.{iname}.Pleat{p_i}'
                    pl.scale = (1.0, 0.55, 1.0)
                    pl.data.materials.append(mat)
                    _smooth_polygons(pl)
                continue

            if photoreal and ('FOLIAGE' in name_u):
                # Fallback organic multi-leaf indoor botanical plant
                bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.014, depth=sz * 0.92, location=(lx, ly, lz - sz * 0.08))
                stem = bpy.context.object
                stem.name = 'Environment.' + iname
                stem_mat = bpy.data.materials.new(stem.name + '.Stem')
                _apply_pbr_shader(stem_mat, 'PLANT_WOOD', [0.32, 0.22, 0.14], photoreal=True)
                stem.data.materials.append(stem_mat)
                _smooth_polygons(stem)
                for lf_i in range(12):
                    ang = lf_i * 2.39996
                    tier = lf_i / 11.0
                    rad_out = (sx * 0.28) * (0.55 + 0.45 * (1.0 - tier * 0.4))
                    leaf_z = (lz - sz * 0.30) + tier * (sz * 0.65)
                    leaf_x = lx + math.cos(ang) * rad_out * 0.55
                    leaf_y = ly + math.sin(ang) * rad_out * 0.55
                    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=1.0, location=(leaf_x, leaf_y, leaf_z))
                    lf = bpy.context.object
                    lf.name = f'Environment.{iname}.Leaf{lf_i}'
                    lf.scale = (sx * 0.24, sy * 0.14, 0.012)
                    tilt = 0.42 + (1.0 - tier) * 0.45
                    lf.rotation_euler = (math.sin(ang) * tilt, -math.cos(ang) * tilt, ang)
                    lf.data.materials.append(mat)
                    _smooth_polygons(lf)
                continue

            if photoreal and any(k in name_u for k in ('_POT', 'VASE')):
                rx = max(sx, sy) * 0.5
                bpy.ops.mesh.primitive_cone_add(vertices=40, radius1=rx * 0.76, radius2=rx, depth=sz, location=(lx, ly, lz))
                obj = bpy.context.object
                obj.name = 'Environment.' + iname
                obj.data.materials.append(mat)
                bevel = obj.modifiers.new('SoftEdges', 'BEVEL')
                bevel.width = 0.004
                bevel.segments = 2
                _smooth_polygons(obj)
                continue

            if photoreal and 'FLOOR_LAMP' in name_u and any(k in name_u for k in ('_BASE', '_STEM', '_SHADE')):
                rx = max(sx, sy) * 0.5
                r1 = rx * 1.08 if '_SHADE' in name_u else rx
                r2 = rx * 0.86 if '_SHADE' in name_u else rx
                bpy.ops.mesh.primitive_cone_add(vertices=48, radius1=r1, radius2=r2, depth=sz, location=(lx, ly, lz))
                obj = bpy.context.object
                obj.name = 'Environment.' + iname
                obj.data.materials.append(mat)
                _smooth_polygons(obj)
                if '_SHADE' in name_u:
                    bulb = bpy.data.lights.new(iname + '.Bulb', 'POINT')
                    bulb.energy = 32.0
                    bulb.color = (1.0, 0.84, 0.62)
                    bulb.shadow_soft_size = 0.12
                    b_obj = bpy.data.objects.new(iname + '.Bulb', bulb)
                    scene.collection.objects.link(b_obj)
                    b_obj.location = (lx, ly, lz - sz * 0.15)
                continue

            if photoreal and '_LEG_' in name_u:
                rx = max(sx, sy) * 0.5
                bpy.ops.mesh.primitive_cone_add(vertices=24, radius1=rx * 0.68, radius2=rx, depth=sz, location=(lx, ly, lz))
                obj = bpy.context.object
                obj.name = 'Environment.' + iname
                obj.data.materials.append(mat)
                _smooth_polygons(obj)
                continue

            bpy.ops.mesh.primitive_cube_add(size=1, location=item['location'])
            obj = bpy.context.object
            obj.name = 'Environment.' + iname
            obj.dimensions = item['size']
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            obj.data.materials.append(mat)

            if photoreal and any(k in name_u for k in ('CUSHION', 'PILLOW', 'MATTRESS', 'SOFA_ARM', 'SOFA_FRAME', 'SOFA_BACK')):
                _sculpt_upholstery_mesh(obj, name_u, sx, sy, sz, wrinkle_img=wrinkle_img)
                if 'CUSHIONSEAT' in name_u:
                    _add_cushion_piping(scene, iname, lx, ly, lz, sx, sy, sz, mat)
                if 'PILLOWTHROWL' in name_u:
                    obj.rotation_euler = (-0.24, 0.22, 0.28)
                elif 'PILLOWTHROWR' in name_u:
                    obj.rotation_euler = (-0.22, -0.20, -0.26)
                elif 'PILLOWLUMBAR' in name_u:
                    obj.rotation_euler = (-0.18, 0.06, -0.10)
            elif item['bevel']:
                bevel = obj.modifiers.new('SoftEdges', 'BEVEL')
                bevel.width = item['bevel']
                bevel.segments = 4 if photoreal else 3
                _smooth_polygons(obj)

        for lamp in definition['lights']:
            ltype = lamp.get('type', 'AREA')
            data = bpy.data.lights.new(lamp['name'], ltype)
            data.energy = lamp['energy']
            data.color = lamp['color']
            if ltype == 'AREA':
                data.size = lamp.get('size', 2.0)
            elif ltype == 'SUN':
                data.angle = lamp.get('angle', 0.06)
            obj = bpy.data.objects.new(lamp['name'], data)
            scene.collection.objects.link(obj)
            obj.location = lamp['location']
            obj.rotation_euler = (Vector(lamp['target']) - obj.location).to_track_quat('-Z', 'Y').to_euler()
        cam = definition['camera']
        data = bpy.data.cameras.new('RoomCamera')
        data.lens = cam['focalLengthMm']
        if photoreal:
            try:
                data.dof.use_dof = True
                data.dof.focus_distance = (Vector(cam['lookAt']) - Vector(cam['location'])).length
                data.dof.aperture_fstop = 5.6
            except Exception:
                pass
        obj = bpy.data.objects.new('RoomCamera', data)
        scene.collection.objects.link(obj)
        obj.location = cam['location']
        obj.rotation_euler = (Vector(cam['lookAt']) - obj.location).to_track_quat('-Z', 'Y').to_euler()
        scene.camera = obj
        scene.view_layers[0].update()
    finally:
        bpy.context.window.scene = original
    return scene, {'sceneHash': expected_hash, 'templateId': definition['templateId'], 'version': definition['version'],
                   'slot': definition['slot'], 'view': definition['view'], 'productScale': 1.,
                   'productMatrix': definition['productMatrix'], 'products': observations,
                   'environmentCount': len(definition['boxes']), 'physicalRoomTruth': False}

