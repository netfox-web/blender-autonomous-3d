"""Run inside Blender to verify saved product master mesh bounds against its manifest."""
import json
from pathlib import Path
import sys
import bpy

folder=Path(sys.argv[sys.argv.index('--')+1])
meta=json.loads((folder/'meta.json').read_text(encoding='utf-8'))
parts={o['recipeComponentId']:o for o in bpy.data.objects if o.type=='MESH' and o.get('recipeComponentId')}
assert len(parts)==len(meta['spec']['components'])
for p in meta['spec']['components']:
    o=parts[p['componentId']]
    for observed,expected in [(o.dimensions,p['size']),(o.matrix_world.translation,p['location'])]:
        assert all(abs(a-b)<1e-5 for a,b in zip(observed,expected)),p['componentId']
print('PRODUCT_MODEL_BLEND_REOPEN_PASS')
