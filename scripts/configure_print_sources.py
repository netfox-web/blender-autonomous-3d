"""Index a read-only artwork folder for the local print workbench."""
import argparse
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))

if __name__=='__main__':
    from fox3d.print_assets import scan_source
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('--data-root',type=Path,default=ROOT/'.fox3d-data')
    args=p.parse_args()
    print(f'Indexed {scan_source(args.data_root,args.source)} artwork files; source remains read-only.')
