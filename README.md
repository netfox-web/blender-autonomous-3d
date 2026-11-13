# Blender Autonomous 3D / Product R&D Engine

Headless Blender as a **FoxStudio / GPU Fleet capability** — product digital twins,
parametric furniture, packaging, 360/AR, synthetic data, and AI Product R&D.

**0 manual Blender UI in the formal pipeline.**

## Inventory first

See [docs/INVENTORY.md](docs/INVENTORY.md). This package adds Capability / Adapter /
Worker / Recipe types. It does not rewrite the existing scheduler, queue, worker
framework, DAM, or recipe registry.

## 商品 Recipe 3D 工作台

在此電腦雙擊桌面「收納王妃 Recipe 3D 工作台」，即可從中文畫面選商品、確認預覽設定、生成並下載 PNG / GLB / Blender 專案。桌面啟動器預設入口為 [本機工作台](http://127.0.0.1:8790/admin/recipes)；它會先依 8790、8791、8788、8792 的順序尋找並重用已執行的工作台，找不到時再依相同順序選擇可用連接埠。實際入口以啟動器開啟的瀏覽器網址為準；下方連結也須使用該網址的連接埠。詳見 [操作與程式盤點](docs/SONAQUEEN_RECIPE_STUDIO.md)。預覽模型不構成製造依據。

[組合櫃 3D 場景電商工坊](http://127.0.0.1:8790/admin/recipes/scenes)：拼裝組合櫃 → AI 排景／拖拉家具 → Blender 光追＋**地端 AI 實景**（公司 GPU 艦隊 FLUX 3，櫃體像素鎖定、每組多張變化）。詳見 [docs/LOCAL_AI_SCENE_STUDIO.md](docs/LOCAL_AI_SCENE_STUDIO.md)；工作台須以 0.0.0.0 啟動讓節點抓得到參考圖。

所有後台頁面及對應 API 群組請參見 [後台頁面總表](docs/ADMIN_PAGES.md)。

三層三門櫃另有 [Golden Product 工作台](http://127.0.0.1:8790/admin/recipes/golden)，提供四 SKU、兩種校驗圖版本、真實 Blender 三視角與逐門裁圖下載；詳見 [操作手冊](docs/GOLDEN_PRODUCT_THREE_TIER_CABINET.md) 與 [驗收證據](docs/GOLDEN_PRODUCT_THREE_TIER_CABINET_ACCEPTANCE.md)。歷史原稿待補，工程／製造仍未放行。

## Run

```powershell
cd "E:\projects\開發 Blender Autonomous 3D"
python -m pip install -e ".[dev]"
pytest
.\start-admin.bat
```

或：

```powershell
$env:PYTHONPATH = (Resolve-Path .\src)
python -m fox3d.api
```

`python -m fox3d.api` 的預設連接埠是 8788（可用 `FOX3D_PORT` 覆寫），與上述桌面啟動器預設的 8790 不同。

- 首頁 / 管理台：`http://127.0.0.1:8788/admin`
- Health：`http://127.0.0.1:8788/health`

雙擊 `start-admin.bat` 會啟動服務並打開瀏覽器。視窗不要關，關掉就等於關站。

### Linux / macOS

需要 Python 3.12 以上（CI 的 `unit` 與 `legacy-admin-browser` 都用 `python-version: "3.12"`）。

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

與 CI `unit` job 相同的測試（mock Blender，並略過瀏覽器）：

```bash
FOX3D_MOCK_BLENDER=1 FOX3D_SKIP_BROWSER=1 pytest -q
```

手動啟動 API 仍是 `python -m fox3d.api`；連接埠說明見上方。

### 與 CI 相同的檢查

下列指令與 [`.github/workflows/pytest.yml`](.github/workflows/pytest.yml) 一致。`pip install -e '.[dev]'` 與 workflow 裡的 `pip install -e ".[dev]"` 是同一個 dev extra，引號只為了讓 bash 不要把方括號當成 glob。

**`unit` job**（`ubuntu-latest` 與 `windows-latest`）

```bash
pip install -e ".[dev]"
ruff check .
mypy
```

```bash
FOX3D_MOCK_BLENDER=1 FOX3D_SKIP_BROWSER=1 pytest -q
```

Workflow 把兩個環境變數設在步驟上，指令本身是 `pytest -q`。`FOX3D_MOCK_BLENDER=1` 使用 mock 算圖。`FOX3D_SKIP_BROWSER=1` 略過 Playwright 瀏覽器測試：`tests/browser/`，以及 `tests/test_admin_legacy_assets.py` 裡標成 `browser` 的案例。Windows PowerShell 請先執行 `$env:FOX3D_MOCK_BLENDER = "1"` 與 `$env:FOX3D_SKIP_BROWSER = "1"`，再執行 `pytest -q`。

**在本機跑瀏覽器測試**（不要設定 `FOX3D_SKIP_BROWSER`）：

```bash
python -m playwright install chromium
FOX3D_MOCK_BLENDER=1 pytest -q tests/browser
```

**`legacy-admin-browser` job**（僅 `ubuntu-latest`）

先安裝 Chromium。CI 使用帶系統相依套件的指令；本機系統程式庫已齊時，上面的 `python -m playwright install chromium` 即可。

```bash
pip install -e ".[dev]"
python -m playwright install --with-deps chromium
```

```bash
FOX3D_MOCK_BLENDER=1 FOX3D_REQUIRE_LEGACY_BROWSER=1 python -m pytest tests/test_admin_legacy_assets.py -q
```

Workflow 的測試指令是 `python -m pytest tests/test_admin_legacy_assets.py -q`，環境變數是 `FOX3D_MOCK_BLENDER=1` 與 `FOX3D_REQUIRE_LEGACY_BROWSER=1`。後者在 Chromium 無法啟動時讓該 job 失敗，而不是略過。

Headless worker (when Blender is installed):

```text
blender -b --factory-startup -P scripts/blender_job.py -- job.json
```

Mock rendering is explicitly enabled in tests. The production runtime and Recipe
workbench refuse to claim real output when Blender is unavailable.

## Layout

| Path | Role |
|---|---|
| `src/fox3d/` | Engine |
| `scripts/blender_job.py` | In-Blender `bpy` worker (no GUI) |
| `services/supervisor/` | Event-driven supervisor (GitHub webhook, Re-Gate; port 8791) |
| `data/` | Committed catalogs and schemas (recipe library, golden product, product DNA) |
| `assets/` | Poly Haven scene models and PBR textures |
| `migrations/` | Additive SQL for FoxStudio Postgres |
| `docs/` | Inventory, architecture, acceptance |
| `tests/` | Unit, regression, acceptance, and Playwright browser tests |
