"""Configure only the user-selected seven-family product folders, then scan read-only."""
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

def main():
    from fox3d.nas_catalog import scan
    from fox3d.recipe_3d import atomic_json
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--product-root',type=Path,required=True)
    p.add_argument('--wood-root',type=Path)
    a=p.parse_args()
    families={'coaster':['02-1杯墊','02-2軟式杯墊','02-3其他杯墊'], 'mat':['01-1地墊','01-2軟式地墊'],
        'cabinet':['08木頭櫃子'], 'curtain':['20門簾'], 'mask_box':['04-3收納-口罩收納盒'],
        'storage_box_50':['04-4收納-50入收納盒'], 'spray_bottle':['05-1噴瓶']}
    sources=[]
    for family,folders in families.items():
        for i,folder in enumerate(folders):
            path=(a.product_root/folder).resolve(strict=True)
            sources.append({'id':f'{family}-{i}','family':family,'path':str(path)})
    if a.wood_root:
        sources.append({'id':'cabinet-extra','family':'cabinet','path':str(a.wood_root.resolve(strict=True))})
    atomic_json(a.data_root/'nas-catalog-config.json',{'sources':sources})
    print(scan(a.data_root),flush=True)

if __name__=='__main__':main()
