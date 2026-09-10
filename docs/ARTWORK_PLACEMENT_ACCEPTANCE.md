# ARTWORK_PLACEMENT_ACCEPTANCE

generatedAt: 2026-09-10T16:35:23.729076+00:00
pytest mock PASS is **not** production ready. Physical print is not validated.
Artwork placement is millimetre REAL_LOGIC. Mock Blender preview is MOCK.

| Check | Status | Evidence |
|---|---|---|
| 4-door master 2400mm | REAL_LOGIC | `2400.0` |
| surfaceDecorationLogicReady | REAL_LOGIC | `True` |
| productionArtworkFileReady | REAL_LOGIC | `True` |
| realArtworkPreviewReady | MOCK | `{'engineeringHash': '35f50517995b368c0d8e3ab36c7d2b9ba97b798099d1046d2ccd746728cca323', 'surfaceHash': '4c2359115bd0929e3afdcb8415aa4f9d2860acb9f8ec4d86aec75610b88f09bd', 'artworkHash': '9b33ffc8e3d300a7697ae3afb8e136969f102a9163b856f20465dddd451baf14', 'placementHash': 'ed0018c18ab3bd09b45f5059ec0fb95db0dbf99c32ddbfa756181e23caa21f64', 'usedMock': True, 'realBlender': False, 'realArtworkPreviewReady': False, 'physicalPrintValidated': False, 'label': 'MOCK', 'productionArtworkFileReady': True, 'jobPayload': {'hasEngineering': True, 'objectName': 'DOOR_1', 'uvRect': {'u0': 0.0, 'v0': 0.0, 'u1': 0.25, 'v1': 1.0}, 'hashes': {'engineeringHash': '35f50517995b368c0d8e3ab36c7d2b9ba97b798099d1046d2ccd746728cca323', 'surfaceHash': '4c2359115bd0929e3afdcb8415aa4f9d2860acb9f8ec4d86aec75610b88f09bd', 'artworkHash': '9b33ffc8e3d300a7697ae3afb8e136969f102a9163b856f20465dddd451baf14', 'placementHash': 'ed0018c18ab3bd09b45f5059ec0fb95db0dbf99c32ddbfa756181e23caa21f64'}}}` |
| physicalPrintValidated | BLOCKED | `False` |
| keep-out BLOCK | REAL_LOGIC | `BLOCKED_PLACEMENT` |
| stale engineering | REAL_LOGIC | `STALE` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "ok": true}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `globalProductionReady=false`. `physicalPrintValidated=false`.
