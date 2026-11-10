"""Distribution and asynchronous system-page regressions."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_system_page_latest_load_wins():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required to exercise the page JavaScript')
    subprocess.run([node, str(ROOT / 'tests/js/system_load_order.js'),
                    str(ROOT / 'src/fox3d/static/pages/system.js')], check=True, timeout=30)


def test_installed_wheel_serves_system_page_and_assets(tmp_path):
    uv = shutil.which('uv')
    if not uv:
        pytest.skip('uv is required to build and install the wheel offline')
    wheel_dir = tmp_path / 'wheel'
    subprocess.run([uv, 'build', '--wheel', '--offline', '--out-dir', str(wheel_dir), str(ROOT)],
                   check=True, timeout=120)
    wheel = next(wheel_dir.glob('*.whl'))
    target = tmp_path / 'installed'
    subprocess.run([uv, 'pip', 'install', '--offline', '--no-deps', '--target', str(target), str(wheel)],
                   check=True, timeout=120)
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import fox3d
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fox3d.admin_pages import assets_router
from fox3d.admin_pages.system import router
assert Path(fox3d.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
app = FastAPI()
app.include_router(assets_router())
app.include_router(router(lambda: None))
client = TestClient(app)
for path in ('/admin/system', '/admin/pages/assets/system.css', '/admin/pages/assets/system.js'):
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    assert response.text
assert 'system.js' in client.get('/admin/system').text
"""
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    subprocess.run([sys.executable, '-I', '-c', script, str(target)], cwd=tmp_path,
                   env=env, check=True, timeout=30)
