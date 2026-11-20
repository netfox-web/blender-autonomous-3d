from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fox3d.api import create_app


def test_release_page_and_assets(platform: Any) -> None:
    client = TestClient(create_app(platform))
    page = client.get('/admin/releases')
    assert page.status_code == 200
    assert '人工放行，不是 LIVE CNC' in page.text
    for name in ('releases.js', 'releases.css'):
        assert client.get('/admin/pages/assets/' + name).status_code == 200
    js = (Path(__file__).resolve().parents[1] / 'src/fox3d/static/pages/releases.js').read_text(encoding="utf-8")
    assert 'innerHTML' not in js
    assert "returnValue = ''" in js
    assert 'lockInputs(true)' in js and '網路錯誤' in js
