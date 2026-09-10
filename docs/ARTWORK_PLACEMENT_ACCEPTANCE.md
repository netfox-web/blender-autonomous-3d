# ARTWORK_PLACEMENT_ACCEPTANCE

generatedAt: 2026-09-10T21:35:00.793322+00:00
pytest mock PASS is **not** production ready. Physical print is not validated.
Artwork placement is millimetre REAL_LOGIC. Mock Blender preview is MOCK.

| Check | Status | Evidence |
|---|---|---|
| 4-door master 2400mm | REAL_LOGIC | `2400.0` |
| surfaceDecorationLogicReady | REAL_LOGIC | `True` |
| productionArtworkFileReady | REAL_LOGIC | `True` |
| realArtworkPreviewReady | MOCK | `{'engineeringHash': '24e82441995584a47071c0a62a511dac0d80e168f6686204be28ee3dc1cfce38', 'surfaceHash': '0b5f741e247f1beb69149ba038a562679d0c866ad3d92f0eb13896030c62e0fc', 'artworkHash': '34aa4933a4848dacc3d5a2a8693a11df63fea97f1938cbf3a52c4e8603db583a', 'placementHash': '87cc4ff02e68d8c8d9bb82159bf05ccfacc3d1b2e67e83ed3533b018e0b937a4', 'usedMock': True, 'realBlender': False, 'realArtworkPreviewReady': False, 'physicalPrintValidated': False, 'label': 'MOCK', 'requestedIdentity': {'placementId': '12b4a31e-fd0f-4061-bfe0-69da658bac3d', 'objectName': 'DOOR_1', 'componentId': 'door_1', 'face': 'FRONT', 'relation': 'MASTER_SPLIT', 'engineeringHash': '24e82441995584a47071c0a62a511dac0d80e168f6686204be28ee3dc1cfce38', 'surfaceHash': '0b5f741e247f1beb69149ba038a562679d0c866ad3d92f0eb13896030c62e0fc', 'artworkHash': '34aa4933a4848dacc3d5a2a8693a11df63fea97f1938cbf3a52c4e8603db583a', 'placementHash': '87cc4ff02e68d8c8d9bb82159bf05ccfacc3d1b2e67e83ed3533b018e0b937a4', 'finalUvHash': '66fe42028332917fff9881026decaa17a226c877f97cc5d8ede960ad8cf91d33', 'finalSampling': [[0.0, 0.0], [0.25, 0.0], [0.25, 1.0], [0.0, 1.0]], 'uvRect': {'u0': 0.0, 'v0': 0.0, 'u1': 0.25, 'v1': 1.0}}, 'productionArtworkFileReady': True, 'jobPayload': {'hasEngineering': True, 'objectName': 'DOOR_1', 'uvRect': {'u0': 0.0, 'v0': 0.0, 'u1': 0.25, 'v1': 1.0}, 'imagePath': 'E:\\projects\\開發 Blender Autonomous 3D\\.fox3d-data\\acceptance\\2936750f-8a3c-4bb5-90ab-70741ea6f21d\\live\\dam\\aw-a\\artwork\\3c80886a-c943-4fb5-96af-0a35036d0b9d_grid.png', 'artworkSha256': 'b2b74672943705affe17ec20d40f38a963c2faa330c568d7dc6c247a8d6f51d9', 'artworkId': '3c80886a-c943-4fb5-96af-0a35036d0b9d', 'hashes': {'engineeringHash': '24e82441995584a47071c0a62a511dac0d80e168f6686204be28ee3dc1cfce38', 'surfaceHash': '0b5f741e247f1beb69149ba038a562679d0c866ad3d92f0eb13896030c62e0fc', 'artworkHash': '34aa4933a4848dacc3d5a2a8693a11df63fea97f1938cbf3a52c4e8603db583a', 'placementHash': '87cc4ff02e68d8c8d9bb82159bf05ccfacc3d1b2e67e83ed3533b018e0b937a4'}}}` |
| physicalPrintValidated | BLOCKED | `False` |
| keep-out BLOCK | REAL_LOGIC | `BLOCKED_PLACEMENT` |
| stale engineering | REAL_LOGIC | `STALE` |
| caller artwork override BLOCK | REAL_LOGIC | `BLOCKED` |
| wrong artwork path BLOCK | REAL_LOGIC | `BLOCKED` |
| CONTAIN letterbox canvas | REAL_LOGIC | `{"anchor": "CENTER", "fit": "CONTAIN", "placedMm": {"xMm": 0.0, "yMm": 675.0, "widthMm": 600.0, "heightMm": 450.0}, "outputPhysicalMm": {"widthMm": 600.0, "heightMm": 1800.0}, "pixelWidth": 1200, "pixelHeight": 3600, "transformHash": "0f946e6f1376859a5c8cd86f7e534214423a14d386a68ff4947b001f45e81143", "finalUvHash": "7753743d3f127adff323afffe1bf4a93f7b1ffba26ae6c7d6e1cfe2866175c3d"}` |
| COVER anchor source crop | REAL_LOGIC | `{"leftSourceXPx": 0, "rightSourceXPx": 360}` |
| rotation/finalUv parity | REAL_LOGIC | `{"rotationDeg": 90.0, "finalUvHash": "b4e3c38e5e323f70b43bd71ec4a085c20b6a48b025419d7f97b4ebe6a17eee35", "transformHash": "951837facaa8d90cabf7f331e99e13ae35186cfac6a41e25ef29845cec3baf36"}` |
| master seam replay | REAL_LOGIC | `{"seamMm": 25.0, "seamSource": "CONFIG", "ready": true}` |
| prior REAL blender | REAL | `{"commitSha": "7a87ea5cedc5242178d7e072de1b9b89c4c60d14", "ok": true}` |
| LIVE_CNC | BLOCKED | `liveMachineControl=false` |

`fullAutonomousFactoryReady=false`. `globalProductionReady=false`. `physicalPrintValidated=false`.
