# ARTWORK_PLACEMENT_ACCEPTANCE

generatedAt: 2026-09-10T15:26:24.373099+00:00
pytest mock PASS is **not** production ready. Physical print is not validated.
Artwork placement is millimetre REAL_LOGIC. Mock Blender preview is MOCK.

| Check | Status | Evidence |
|---|---|---|
| 4-door master 2400mm | REAL_LOGIC | `2400.0` |
| surfaceDecorationLogicReady | REAL_LOGIC | `True` |
| productionArtworkFileReady | REAL_LOGIC | `True` |
| realArtworkPreviewReady | MOCK | `{'engineeringHash': '700e14733a94679df04e2a929c5bfd8cb07e8b69870c700e644727f6d4b54cf2', 'surfaceHash': '1fa4df52f64019ff5c1838c8f342fd9c0e9bf63d8c38aee6461166c7d986b7b8', 'artworkHash': '004d66ec12d1ef56389a44ead3944ea2c8bd0f35c8b5f8e91e56159aa0655bfa', 'placementHash': '82f132e5c208dea6c965d1451451ab41320a3c398641c1af064b51c4076711d4', 'usedMock': True, 'realBlender': False, 'realArtworkPreviewReady': False, 'physicalPrintValidated': False, 'label': 'MOCK', 'productionArtworkFileReady': True}` |
| physicalPrintValidated | BLOCKED | `False` |
| keep-out BLOCK | REAL_LOGIC | `BLOCKED_PLACEMENT` |
| stale engineering | REAL_LOGIC | `STALE` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "ok": true}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `globalProductionReady=false`. `physicalPrintValidated=false`.
