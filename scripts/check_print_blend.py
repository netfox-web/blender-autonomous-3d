"""Reopen validation for print faces and packed texture pixels, inside Blender."""
import hashlib
import json
import sys
from pathlib import Path
import bpy

folder=Path(sys.argv[sys.argv.index('--')+1])
m=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
objects={o['recipeComponentId']:o for o in bpy.data.objects if o.get('recipeComponentId')}
assert set(objects)=={p['componentId'] for p in m['spec']['components']}
for p in m['spec']['components']:
    obj=objects[p['componentId']]
    for actual,want in ((obj.dimensions,p['size']),(obj.matrix_world.translation,p['location'])):
        assert all(abs(a-b)<1e-5 for a,b in zip(actual,want))
for p in m['package']['placements']:
    obj=objects[p['componentId']];front=[f for f in obj.data.polygons if f.normal.y<-.999]
    assert len(front)==1
    mat=obj.data.materials[front[0].material_index]
    nodes=[n for n in mat.node_tree.nodes if n.type=='TEX_IMAGE']
    assert len(nodes)==1 and nodes[0].image.packed_file
    assert hashlib.sha256(bytes(nodes[0].image.packed_file.data)).hexdigest()==p['source']['fileSha256']
    for li in front[0].loop_indices:
        v=obj.data.vertices[obj.data.loops[li].vertex_index].co
        ci=(0 if v.x<0 else 1) if v.z<0 else (3 if v.x<0 else 2)
        assert all(abs(a-b)<1e-6 for a,b in zip(obj.data.uv_layers.active.data[li].uv,p['finalSampling'][ci]))
if m['spec'].get('sceneDefinition'):
    from mathutils import Matrix, Vector
    from bpy_extras.object_utils import world_to_camera_view
    definition=m['spec']['sceneDefinition']
    scene=bpy.data.scenes['ProductScene.'+definition['templateId']]
    assert scene['sceneHash']==m['sceneHash']
    assert json.loads(scene['sceneDefinition'])==definition
    clones={o['sceneComponentId']:o for o in scene.objects if o.get('sceneComponentId')}
    assert set(clones)==set(objects)
    pose=Matrix(definition['productMatrix'])
    for key,clone in clones.items():
        original=objects[key]
        assert clone.data==original.data  # exact mesh, materials and UV datablocks after reopen
        want=pose @ original.matrix_world
        assert all(abs(a-b)<1e-5 for row,wr in zip(clone.matrix_world,want) for a,b in zip(row,wr))
        assert all(abs(v-1.)<1e-5 for v in clone.matrix_world.to_scale())
    assert sum(o.name.startswith('Environment.') for o in scene.objects)==len(definition['boxes'])
    assert bpy.context.scene==scene
    assert all(abs(a-b)<1e-5 for a,b in zip(scene.camera.location,definition['camera']['location']))
    for clone in clones.values():
        for corner in clone.bound_box:
            projected=world_to_camera_view(scene,scene.camera,clone.matrix_world @ Vector(corner))
            assert .02<projected.x<.98 and .02<projected.y<.98 and projected.z>0, 'Product cropped'
    depsgraph=bpy.context.evaluated_depsgraph_get()
    for placement in m['package']['placements']:
        clone=clones[placement['componentId']]
        front=next(f for f in clone.data.polygons if f.normal.y<-.999)
        point=clone.matrix_world @ front.center
        direction=point-scene.camera.location
        hit=scene.ray_cast(depsgraph,scene.camera.location,direction.normalized())
        assert hit[0] and hit[4].get('sceneComponentId')==placement['componentId'], 'Artwork occluded'
    print('SCENE_BLEND_REOPEN_PASS')
print('PRINT_BLEND_REOPEN_PASS')
