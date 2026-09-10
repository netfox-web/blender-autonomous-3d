# ARTWORK_PLACEMENT_ACCEPTANCE

generatedAt: 2026-09-10T18:37:18.058753+00:00
pytest mock PASS is **not** production ready. Physical print is not validated.
Artwork placement is millimetre REAL_LOGIC. Mock Blender preview is MOCK.

| Check | Status | Evidence |
|---|---|---|
| 4-door master 2400mm | REAL_LOGIC | `2400.0` |
| surfaceDecorationLogicReady | REAL_LOGIC | `True` |
| productionArtworkFileReady | REAL_LOGIC | `True` |
| realArtworkPreviewReady | MOCK | `{'engineeringHash': 'e5c64e1a536ccf7bacc527c9a86267737c124c04c78397a9b5a6898b61b348ba', 'surfaceHash': '0001d750989a8d3b1e398c3d4a9e1017f0d7463b5aedf6452211bb73c8272b4b', 'artworkHash': '56d19a369d598bf0d96361cec6f5ff611c324575e9a704965e4d430b19dd6ba6', 'placementHash': 'a5847f3ec32fa29a48217109424dbd4705ea21f40a558c4cf0bae43512e5c8aa', 'usedMock': True, 'realBlender': False, 'realArtworkPreviewReady': False, 'physicalPrintValidated': False, 'label': 'MOCK', 'productionArtworkFileReady': True, 'jobPayload': {'hasEngineering': True, 'objectName': 'DOOR_1', 'uvRect': {'u0': 0.0, 'v0': 0.0, 'u1': 0.25, 'v1': 1.0}, 'hashes': {'engineeringHash': 'e5c64e1a536ccf7bacc527c9a86267737c124c04c78397a9b5a6898b61b348ba', 'surfaceHash': '0001d750989a8d3b1e398c3d4a9e1017f0d7463b5aedf6452211bb73c8272b4b', 'artworkHash': '56d19a369d598bf0d96361cec6f5ff611c324575e9a704965e4d430b19dd6ba6', 'placementHash': 'a5847f3ec32fa29a48217109424dbd4705ea21f40a558c4cf0bae43512e5c8aa'}}}` |
| physicalPrintValidated | BLOCKED | `False` |
| keep-out BLOCK | REAL_LOGIC | `BLOCKED_PLACEMENT` |
| stale engineering | REAL_LOGIC | `STALE` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "ok": true}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `globalProductionReady=false`. `physicalPrintValidated=false`.
