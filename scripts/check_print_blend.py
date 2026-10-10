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
print('PRINT_BLEND_REOPEN_PASS')
