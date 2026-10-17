"""Build a separate presentation scene; canonical meshes/UVs remain untouched."""
import json
import hashlib
import math


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
    elif any(k in name_u for k in ('FLOOR', 'TABLE', 'DESK', 'BENCH', 'FRAME', 'WORKTOP', 'WOOD', 'CABINET')):
        # Procedural timber / hardwood grain with satin finish
        mapping.inputs['Scale'].default_value = (12.0, 2.5, 2.5) if 'FLOOR' in name_u else (4.0, 1.5, 1.5)
        wave = nodes.new('ShaderNodeTexWave')
        wave.wave_type = 'BANDS'
        wave.bands_direction = 'Y' if 'FLOOR' not in name_u else 'X'
        wave.inputs['Scale'].default_value = 4.5
        wave.inputs['Distortion'].default_value = 2.2
        wave.inputs['Detail'].default_value = 2.0
        links.new(mapping.outputs['Vector'], wave.inputs['Vector'])

        mix = nodes.new('ShaderNodeMix')
        mix.data_type = 'RGBA'
        mix.blend_type = 'MULTIPLY'
        mix.inputs['Factor'].default_value = 0.16 if 'FLOOR' in name_u else 0.10
        mix.inputs[6].default_value = (r, g, b, 1.0)
        links.new(wave.outputs['Color'], mix.inputs[7])
        links.new(mix.outputs[2], shader.inputs['Base Color'])

        bump = nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.04 if 'FLOOR' in name_u else 0.02
        bump.inputs['Distance'].default_value = 0.0015
        links.new(wave.outputs['Fac'], bump.inputs['Height'])
        links.new(bump.outputs['Normal'], shader.inputs['Normal'])
        shader.inputs['Roughness'].default_value = 0.34 if 'FLOOR' in name_u else 0.38
        if 'Coat Weight' in shader.inputs:
            shader.inputs['Coat Weight'].default_value = 0.20
    elif any(k in name_u for k in ('SOFA', 'RUG', 'MAT', 'BED', 'PILLOW', 'CUSHION')):
        # Woven fabric micro-bump & sheen
        noise = nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 160.0
        noise.inputs['Detail'].default_value = 6.0
        noise.inputs['Roughness'].default_value = 0.75
        links.new(tex_coord.outputs['Object'], noise.inputs['Vector'])

        bump = nodes.new('ShaderNodeBump')
        bump.inputs['Strength'].default_value = 0.18
        bump.inputs['Distance'].default_value = 0.003
        links.new(noise.outputs['Fac'], bump.inputs['Height'])
        links.new(bump.outputs['Normal'], shader.inputs['Normal'])
        shader.inputs['Roughness'].default_value = 0.88
        if 'Sheen Weight' in shader.inputs:
            shader.inputs['Sheen Weight'].default_value = 0.65
    elif any(k in name_u for k in ('SHADE', 'GLASS')):
        shader.inputs['Roughness'].default_value = 0.25
        if 'Emission Color' in shader.inputs and 'Emission Strength' in shader.inputs:
            shader.inputs['Emission Color'].default_value = (r, g, b, 1.0)
            shader.inputs['Emission Strength'].default_value = 2.8 if 'GLASS' in name_u else 1.8
    elif any(k in name_u for k in ('STEM', 'HANDLE', 'METAL')):
        shader.inputs['Metallic'].default_value = 0.85
        shader.inputs['Roughness'].default_value = 0.28
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
        shader.inputs['Roughness'].default_value = 0.52


def build(created, definition, device, expected_hash):
    import bpy
    from mathutils import Matrix, Vector
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
        for item in definition['boxes']:
            bpy.ops.mesh.primitive_cube_add(size=1, location=item['location'])
            obj = bpy.context.object
            obj.name = 'Environment.' + item['name']
            obj.dimensions = item['size']
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            mat = bpy.data.materials.new(obj.name)
            _apply_pbr_shader(mat, item['name'], item['color'], photoreal=photoreal)
            obj.data.materials.append(mat)
            if item['bevel']:
                bevel = obj.modifiers.new('SoftEdges', 'BEVEL')
                bevel.width = item['bevel']
                bevel.segments = 3
                try:
                    for poly in obj.data.polygons:
                        poly.use_smooth = True
                except Exception:
                    pass
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
