# ARTWORK_PLACEMENT_ACCEPTANCE

generatedAt: 2026-09-10T20:05:02.871432+00:00
pytest mock PASS is **not** production ready. Physical print is not validated.
Artwork placement is millimetre REAL_LOGIC. Mock Blender preview is MOCK.

| Check | Status | Evidence |
|---|---|---|
| 4-door master 2400mm | REAL_LOGIC | `2400.0` |
| surfaceDecorationLogicReady | REAL_LOGIC | `True` |
| productionArtworkFileReady | REAL_LOGIC | `True` |
| realArtworkPreviewReady | MOCK | `{'engineeringHash': '12c8be4ee5e423d245815a9dc3d1dad3620a78bad909711c894d413cdf8b7e08', 'surfaceHash': '5d603ab769a6f50c9d43eec1c3f7208dfb932da43e115809354112a0f8472f2e', 'artworkHash': 'f8e8fff90068a65650297de76d332909e915eae778630931d63fa3fdb6e629c7', 'placementHash': '685efae606c16fa26a0347da87c689e2fcf6edb2cf872dfbeeec3d5b1812c202', 'usedMock': True, 'realBlender': False, 'realArtworkPreviewReady': False, 'physicalPrintValidated': False, 'label': 'MOCK', 'requestedIdentity': {'placementId': 'b4f517dd-59f3-42f6-a7a5-8541a4ad2af7', 'objectName': 'DOOR_1', 'componentId': 'door_1', 'face': 'FRONT', 'relation': 'MASTER_SPLIT', 'engineeringHash': '12c8be4ee5e423d245815a9dc3d1dad3620a78bad909711c894d413cdf8b7e08', 'surfaceHash': '5d603ab769a6f50c9d43eec1c3f7208dfb932da43e115809354112a0f8472f2e', 'artworkHash': 'f8e8fff90068a65650297de76d332909e915eae778630931d63fa3fdb6e629c7', 'placementHash': '685efae606c16fa26a0347da87c689e2fcf6edb2cf872dfbeeec3d5b1812c202', 'finalUvHash': 'a576e64f1b57be57600f71e555409b45e5735e95c69f7d0f1594cef6cb772957', 'finalSampling': [[0.0, 0.0], [0.25, 0.0], [0.25, 1.0], [0.0, 1.0]], 'uvRect': {'u0': 0.0, 'v0': 0.0, 'u1': 0.25, 'v1': 1.0}}, 'productionArtworkFileReady': True, 'jobPayload': {'hasEngineering': True, 'objectName': 'DOOR_1', 'uvRect': {'u0': 0.0, 'v0': 0.0, 'u1': 0.25, 'v1': 1.0}, 'hashes': {'engineeringHash': '12c8be4ee5e423d245815a9dc3d1dad3620a78bad909711c894d413cdf8b7e08', 'surfaceHash': '5d603ab769a6f50c9d43eec1c3f7208dfb932da43e115809354112a0f8472f2e', 'artworkHash': 'f8e8fff90068a65650297de76d332909e915eae778630931d63fa3fdb6e629c7', 'placementHash': '685efae606c16fa26a0347da87c689e2fcf6edb2cf872dfbeeec3d5b1812c202'}}}` |
| physicalPrintValidated | BLOCKED | `False` |
| keep-out BLOCK | REAL_LOGIC | `BLOCKED_PLACEMENT` |
| stale engineering | REAL_LOGIC | `STALE` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "ok": true}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `globalProductionReady=false`. `physicalPrintValidated=false`.
