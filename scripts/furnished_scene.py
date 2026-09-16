"""Build a separate presentation scene; canonical meshes/UVs remain untouched."""
import json
import hashlib


def build(created, definition, device, expected_hash):
    import bpy
    from mathutils import Matrix, Vector
    # Blender ships its own Python; do not import application dependencies here.
    digest=hashlib.sha256(json.dumps(definition,sort_keys=True,separators=(',',':'),default=str).encode('utf-8')).hexdigest()
    if digest != expected_hash:
        raise ValueError('Scene definition hash mismatch')
    original = bpy.context.scene
    scene = bpy.data.scenes.new('ProductScene.' + definition['templateId'])
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'GPU' if device == 'OPTIX' else 'CPU'
    scene.view_settings.view_transform = original.view_settings.view_transform
    scene['sceneHash'] = expected_hash
    scene['sceneDefinition'] = json.dumps(definition)
    scene.world = bpy.data.worlds.new('RoomWorld')
    scene.world.use_nodes = True
    bg=scene.world.node_tree.nodes.get('Background')
    bg.inputs['Color'].default_value=(*definition['worldColor'],1)
    bg.inputs['Strength'].default_value=definition['worldStrength']
    pose=Matrix(definition['productMatrix'])
    observations=[]
    for src in created.values():
        if not src.get('recipeComponentId'): continue
        clone=src.copy()  # linked mesh includes the exact material slots and UVs
        for key in list(clone.keys()): del clone[key]
        clone.name='SceneProduct.'+src['recipeComponentId']
        clone['sceneComponentId']=src['recipeComponentId']
        clone['canonicalObject']=src.name
        scene.collection.objects.link(clone)
        clone.matrix_world=pose @ src.matrix_world
        observations.append({'componentId':src['recipeComponentId'], 'linkedMesh':clone.data==src.data,
                             'matrixWorld':[list(row) for row in clone.matrix_world]})
    try:
        bpy.context.window.scene=scene
        for item in definition['boxes']:
            bpy.ops.mesh.primitive_cube_add(size=1,location=item['location'])
            obj=bpy.context.object;obj.name='Environment.'+item['name'];obj.dimensions=item['size']
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            mat=bpy.data.materials.new(obj.name);mat.use_nodes=True
            shader=mat.node_tree.nodes.get('Principled BSDF')
            shader.inputs['Base Color'].default_value=(*item['color'],1)
            shader.inputs['Roughness'].default_value=.7
            obj.data.materials.append(mat)
            if item['bevel']:
                bevel=obj.modifiers.new('SoftEdges','BEVEL');bevel.width=item['bevel'];bevel.segments=3
        for lamp in definition['lights']:
            data=bpy.data.lights.new(lamp['name'],'AREA');data.energy=lamp['energy'];data.size=lamp['size'];data.color=lamp['color']
            obj=bpy.data.objects.new(lamp['name'],data);scene.collection.objects.link(obj);obj.location=lamp['location']
            obj.rotation_euler=(Vector(lamp['target'])-obj.location).to_track_quat('-Z','Y').to_euler()
        cam=definition['camera'];data=bpy.data.cameras.new('RoomCamera');data.lens=cam['focalLengthMm']
        obj=bpy.data.objects.new('RoomCamera',data);scene.collection.objects.link(obj);obj.location=cam['location']
        obj.rotation_euler=(Vector(cam['lookAt'])-obj.location).to_track_quat('-Z','Y').to_euler();scene.camera=obj
        scene.view_layers[0].update()
    finally:
        bpy.context.window.scene=original
    return scene, {'sceneHash':expected_hash,'templateId':definition['templateId'],'version':definition['version'],
                   'slot':definition['slot'],'view':definition['view'],'productScale':1.,
                   'productMatrix':definition['productMatrix'],'products':observations,
                   'environmentCount':len(definition['boxes']),'physicalRoomTruth':False}
