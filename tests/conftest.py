from __future__ import annotations

from pathlib import Path

import pytest

from fox3d.platform import Platform


def _gpu(name: str, vram: float) -> dict:
    return {
        "blender": True,
        "blenderVersion": "mock-4.2",
        "cuda": True,
        "optix": True,
        "gpuCount": 1,
        "gpuName": name,
        "vramGb": vram,
        "driver": "mock",
        "gpus": [{"gpuIndex": 0, "name": name, "vramGb": vram, "freeVramGb": vram}],
    }


@pytest.fixture
def platform(tmp_path: Path) -> Platform:
    plat = Platform(root=tmp_path / "data", mock_blender=True)
    plat.register_node(target_key="5080-1", name="RTX 5080 #1", detected=_gpu("NVIDIA GeForce RTX 5080", 16))
    plat.register_node(target_key="5090-1", name="RTX 5090 #1", detected=_gpu("NVIDIA GeForce RTX 5090", 32))
    return plat
