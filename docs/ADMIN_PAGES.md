# Adding an admin page

Every admin page shares one sidebar and the Ctrl+K search (`static/fox3d-shell.js`). The
list behind both is `src/fox3d/features.py`. A test fails if any HTTP route is not owned by
an entry there, so nothing can be hidden again.

## Files a new page adds (and nothing else shared)

| File | What goes in it |
|---|---|
| `src/fox3d/admin_pages/<name>.py` | `def router(provider) -> APIRouter` with one `GET /admin/<name>` route returning `page_response("<name>")`. Add API routes here only if the page needs one that does not exist yet. |
| `src/fox3d/static/pages/<name>.html` | Full HTML document. In `<head>` load `/admin/recipes/assets/fox3d-shell.css`, `/admin/recipes/assets/fox3d-shell.js` (defer), then your own `/admin/pages/assets/<name>.css` and `.js`. No inline `<script>` or `<style>`: the page CSP is `default-src 'self'`. |
| `src/fox3d/static/pages/<name>.js`, `<name>.css` | Page code and styles. Asset names must match `^[a-z0-9][a-z0-9-]*\.(js|css)$`. |
| `tests/test_admin_page_<name>.py` | Page returns 200 and loads the shell; the APIs it calls work with `X-Tenant-Id` (use the `platform` fixture from `tests/conftest.py`). |

In your module, declare which API-only features the page now covers, for example `FEATURES = {"pilot": "/admin/pilot"}`. The directory and sidebar then show those features as pages with that link. Do not edit `src/fox3d/features.py`, `api.py`, `recipe_admin_api.py` or the shell files; two pages claiming the same feature id is an error.

## Look and behaviour

- Use the workbench palette (light green): background `#f4f6f5`, surfaces `#fff`, accent `#0f6e52`, borders `#e3e7e5`, and the font stack `"Noto Sans TC","Microsoft JhengHei",system-ui,sans-serif`. Define the colours as CSS variables on `:root`, and add a dark set under `prefers-color-scheme: dark`, following `static/features.css`.
- Write all labels in Traditional Chinese, in plain words a warehouse or sales person understands. Keep API paths and codes in small monospace text only.
- Send `X-Tenant-Id` on every API call. Read the tenant from `localStorage['fox3d.tenant']`, defaulting to `sonaqueen-home`, the same key `/admin/features` uses.
- Show loading, empty and error states. Never show raw stack traces.
- Any action that changes data (approve, reserve, release, cancel) needs a confirm step on the page, because `confirm()` cannot be relied on. Show the API's answer after the action.
- Pages must work at 400 px wide with no horizontal page scroll. Wide tables go inside an `overflow-x:auto` box.
- Never claim REAL output from MOCK data. If an API returns a `MOCK`, `BLOCKED_*` or `PARTIAL` status, show it as such.

## Checks before the PR

```
pip install -e ".[dev]"
ruff check .
mypy
FOX3D_MOCK_BLENDER=1 pytest -q
```

Also open the page in a browser, or take a Playwright screenshot at 1440 and 400 px wide, and attach it to the PR.
