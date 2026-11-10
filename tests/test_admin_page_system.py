"""System page, feature registration and its API dependencies."""
from fastapi.testclient import TestClient

from fox3d.admin_pages.system import FEATURES
from fox3d.api import create_app


def test_system_page_and_apis(platform):  # noqa: ANN001, ANN201
    client = TestClient(create_app(platform))
    page = client.get('/admin/system')
    assert page.status_code == 200
    for asset in ('fox3d-shell.css', 'fox3d-shell.js', 'system.css', 'system.js'):
        assert asset in page.text
    for asset in ('system.css', 'system.js'):
        assert client.get(f'/admin/pages/assets/{asset}').status_code == 200
    assert FEATURES == {'system': '/admin/system'}
    headers = {'X-Tenant-Id': 'sonaqueen-home'}
    for path in ('/health', '/api/probe', '/api/admin/features', '/docs', '/redoc', '/openapi.json'):
        assert client.get(path, headers=headers).status_code == 200
    index = client.get('/api/admin/features', headers=headers).json()
    system = next(feature for feature in index['features'] if feature['id'] == 'system')
    assert system['kind'] == 'page'
    assert system['href'] == '/admin/system'
    assert isinstance(index['unclaimed'], list)
    assert 'innerHTML' not in client.get('/admin/pages/assets/system.js').text
