"""Run inside Blender after reopening the delivered .blend, not construction memory."""
import hashlib
import json
import sys
from pathlib import Path
import bpy

folder=Path(sys.argv[sys.argv.index('--')+1])
manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
objects={o['recipeComponentId']:o for o in bpy.data.objects if o.get('recipeComponentId')}
assert len(objects)==10
for component in manifest['spec']['components']:
    obj=objects[component['componentId']]
    for actual,expected in ((list(obj.dimensions),component['size']),(list(obj.matrix_world.translation),component['location'])):
        assert all(abs(a-b)<1e-5 for a,b in zip(actual,expected))
for placement in manifest['package']['placements']:
    obj=objects[placement['componentId']]
    front=[p for p in obj.data.polygons if p.normal.y < -.999]
    assert len(front)==1
    material=obj.data.materials[front[0].material_index]
    image_nodes=[n for n in material.node_tree.nodes if n.type=='TEX_IMAGE']
    assert len(image_nodes)==1 and image_nodes[0].image.packed_file
    assert hashlib.sha256(bytes(image_nodes[0].image.packed_file.data)).hexdigest()==placement['source']['fileSha256']
    for li in front[0].loop_indices:
        vertex=obj.data.vertices[obj.data.loops[li].vertex_index].co
        ci=(0 if vertex.x<0 else 1) if vertex.z<0 else (3 if vertex.x<0 else 2)
        assert all(abs(a-b)<1e-6 for a,b in zip(obj.data.uv_layers.active.data[li].uv,placement['finalSampling'][ci]))
print('GOLDEN_BLEND_REOPEN_PASS')
