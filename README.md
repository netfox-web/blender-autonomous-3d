# Blender Autonomous 3D / Product R&D Engine

Headless Blender as a **FoxStudio / GPU Fleet capability** — product digital twins,
parametric furniture, packaging, 360/AR, synthetic data, and AI Product R&D.

**0 manual Blender UI in the formal pipeline.**

## Inventory first

See [docs/INVENTORY.md](docs/INVENTORY.md). This package adds Capability / Adapter /
Worker / Recipe types. It does not rewrite the existing scheduler, queue, worker
framework, DAM, or recipe registry.

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

- 首頁 / 管理台：`http://127.0.0.1:8788/admin`
- Health：`http://127.0.0.1:8788/health`

雙擊 `start-admin.bat` 會啟動服務並打開瀏覽器。視窗不要關，關掉就等於關站。

Headless worker (when Blender is installed):

```text
blender -b --factory-startup -P scripts/blender_job.py -- job.json
```

If Blender is missing, the in-process runtime uses a deterministic mock renderer
so queue / retry / cancel / cache / QA tests still run.

## Layout

| Path | Role |
|---|---|
| `src/fox3d/` | Engine |
| `scripts/blender_job.py` | In-Blender `bpy` worker (no GUI) |
| `migrations/` | Additive SQL for FoxStudio Postgres |
| `docs/` | Inventory, architecture, acceptance |
| `tests/` | Phase 40 acceptance + unit tests |
