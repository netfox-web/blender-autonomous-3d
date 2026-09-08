# Phase 40 acceptance

Run:

```powershell
python -m pip install -e ".[dev]"
pytest
```

| # | Check | Test |
|---|---|---|
| 1 | Headless Blender Worker | `test_01_headless_blender_worker` |
| 2 | NVIDIA GPU detection | `test_02_nvidia_gpu_detection` |
| 3 | OptiX Render | `test_03_optix_render` |
| 4 | Queue | `test_04_queue` |
| 5 | Retry | `test_05_retry` |
| 6 | Cancel | `test_06_cancel` |
| 7 | Timeout | `test_07_timeout` |
| 8 | Worker offline recovery | `test_08_worker_offline_recovery` |
| 9 | Digital Twin | `test_09_digital_twin` |
| 10 | Product Studio | `test_10_product_studio` |
| 11 | Camera Recipe | `test_11_camera_recipe` |
| 12 | Lighting Recipe | `test_12_lighting_recipe` |
| 13 | Packaging Mock | `test_13_packaging_mock` |
| 14 | Parametric Cabinet | `test_14_parametric_cabinet` |
| 15 | Cabinet resize | `test_15_cabinet_resize` |
| 16 | BOM consistency | `test_16_bom_consistency` |
| 17 | Cost Engine | `test_17_cost_engine` |
| 18 | Engineering collision | `test_18_engineering_collision` |
| 19 | 360 Render | `test_19_360_render` |
| 20 | GLB export | `test_20_glb_export` |
| 21 | Synthetic dataset | `test_21_synthetic_dataset` |
| 22 | Blender → AI Video mock | `test_22_blender_to_video_mock` |
| 23 | Vision Judge mock | `test_23_vision_judge_mock` |
| 24 | Recipe Research | `test_24_recipe_research` |
| 25 | Tenant isolation | `test_25_tenant_isolation` |
| 26 | Asset lineage | `test_26_asset_lineage` |
| 27 | Cache | `test_27_cache` |
| 28 | Scheduler | `test_28_scheduler` |
| 29 | GPU draining | `test_29_gpu_draining` |
| 30 | Security sandbox | `test_30_security_sandbox` |
