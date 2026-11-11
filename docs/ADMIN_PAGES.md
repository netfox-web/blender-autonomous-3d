# 後台頁面總表

以下依 `src/fox3d/features.py` 的功能目錄及頁面模組宣告整理；同一頁的錨點代表不同功能區。API 欄列出功能目錄中的路徑前綴，並非完整端點清單。

| 頁面路徑 | 用途 | 對應 API 群組 |
|---|---|---|
| `/admin` | 系統與算力總控台：查看 Blender、算圖工作與成品。 | `/api/e2e/smoke`、`/api/parametric/products`、`/api/assets` |
| `/admin/features` | 搜尋所有功能與狀態。 | `/api/admin/features` |
| `/admin/recipes` | 編輯商品規格、匯入匯出與預覽模型。 | `/api/recipe-library` |
| `/admin/recipes/scenes` | 組合櫃場景與電商圖批次製作。 | `/api/ecommerce-scenes` |
| `/admin/recipes/models` | 管理 3D 母版、場景範本與變體。 | `/api/product-models` |
| `/admin/recipes/golden` | 三層櫃多視角算圖、門片裁切與 Product DNA。 | `/api/recipe-library/golden`、`/api/product-dna` |
| `/admin/recipes/print` | 管理圖稿、印刷工單、打樣與放行。 | `/api/print-workspace` |
| `/admin/factory` | 依空間產生商品、報價與改版。 | `/api/factory`、`/api/pages/factory` |
| `/admin/factory#rd` | 從需求產生商品研發方案。 | `/api/product-rd`、`/api/pages/factory` |
| `/admin/kd` | 管理拆裝家具型錄、SKU 與就緒狀態。 | `/api/kd`、`/api/pages/kd` |
| `/admin/kd#structures` | 產生陳列架、包裝及壓克力商品參數。 | `/api/retail`、`/api/packaging`、`/api/acrylic`、`/api/pages/kd` |
| `/admin/materials` | 管理板材庫存、餘料預留與排版基準測試。 | `/api/materials`、`/api/remnants`、`/api/nesting`、`/api/pages/materials` |
| `/admin/pilot` | 查看試產工單、批次、領料、收料與請購。 | `/api/pilot/console`、`/api/pilot/work-orders`、`/api/pilot/batches`、`/api/pilot/receipts`、`/api/pilot/purchase-requests`、`/api/pilot/import`、`/api/pilot/export`、`/api/pilot/health`、`/api/pages/pilot` |
| `/admin/pilot-floor` | 管理現場站點、派工、掃碼與異常。 | `/api/pilot/operator`、`/api/pilot/scan`、`/api/pilot/stations`、`/api/pilot/dispatch`、`/api/pilot/leases`、`/api/pilot/exceptions`、`/api/pilot/scan-token`、`/api/pages/pilot-floor` |
| `/admin/render` | 送出、查詢及取消 3D 算圖工作。 | `/api/3d/jobs`、`/api/render`、`/api/pages/render` |
| `/admin/render#twins` | 建立、上傳與預覽數位分身。 | `/api/digital-twins`、`/api/pages/render` |
| `/admin/readiness` | 查看就緒狀態、證據、放行、安全評估與 KPI。 | `/api/readiness`、`/api/evidence`、`/api/release`、`/api/safety`、`/api/kpi`、`/api/pages/readiness` |
| `/admin/readiness#physical-os` | 查看實體商品家族、就緒狀態與人工核准。 | `/api/physical-os`、`/api/pages/readiness` |
| `/admin/readiness#commerce` | 匯入外部電商商品資料。 | `/api/commerce`、`/api/pages/readiness` |
| `/admin/system` | 查看健康檢查、主機偵測與 API 文件。 | `/health`、`/api/probe`、`/docs`、`/redoc`、`/openapi.json`、`/api/pages/system` |

# Adding an admin page

Every admin page shares one sidebar and the Ctrl+K search (`static/fox3d-shell.js`). The
list behind both is `src/fox3d/features.py`. A test fails if any HTTP route is not owned by
an entry there, so nothing can be hidden again.

## Files a new page adds (and nothing else shared)

| File | What goes in it |
|---|---|
| `src/fox3d/admin_pages/<name>.py` | `def router(provider) -> APIRouter` with one `GET /admin/<name>` route returning `page_response("<name>")`. Add API routes here only if the page needs one that does not exist yet, and put them under `/api/pages/<name>/` (that namespace is owned by your page automatically, so the route-coverage test stays green). |
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
